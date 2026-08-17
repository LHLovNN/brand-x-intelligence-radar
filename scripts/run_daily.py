#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters.x_source_base import ProviderBudgetExceeded
from src.adapters.provider_factory import get_x_source
from src.pipeline.clusterer import cluster_posts
from src.pipeline.conversation_context import attach_conversation_contexts
from src.pipeline.dashboard_builder import build_dashboard_data, public_collection_status_payload
from src.pipeline.evidence_chain import attach_evidence_chains
from src.pipeline.fermentation import update_fermentation
from src.pipeline.normalizer import normalize_posts
from src.pipeline.platform_trends import collect_platform_trends, platform_trends_enabled
from src.pipeline.query_builder import build_x_search_queries
from src.pipeline.scoring import score_clusters
from src.pipeline.translation import (
    apply_translations,
    build_translation_service,
)
from src.utils.config import load_project_json
from src.utils.io import read_json, write_json, write_jsonl
from src.utils.time import (
    BEIJING,
    beijing_daily_window,
    beijing_label,
    beijing_report_date_window,
    from_iso,
    now_utc,
    to_iso,
)


CHECKPOINT_PATH = ROOT / "data" / "checkpoints" / "daily" / "latest.json"


def report_date_arg(value: str) -> str:
    try:
        beijing_report_date_window(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Brand X Intelligence Radar daily dashboard data.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--resume-from-checkpoint",
        action="store_true",
        help="Resume from the latest local collection checkpoint without calling the X provider.",
    )
    mode.add_argument(
        "--report-date",
        type=report_date_arg,
        metavar="YYYY-MM-DD",
        help="Generate a historical daily report ending at 08:00 BJT on this date.",
    )
    parser.add_argument(
        "--attach-context-from-provider",
        action="store_true",
        help="When resuming from checkpoint, fetch only eligible conversation context without rerunning collection.",
    )
    args = parser.parse_args()
    if args.attach_context_from_provider and not args.resume_from_checkpoint:
        parser.error("--attach-context-from-provider requires --resume-from-checkpoint")
    return args


def selected_provider(source_config: dict[str, Any]) -> str:
    explicit = os.getenv("X_SOURCE_PROVIDER")
    if explicit:
        return explicit
    if os.getenv("TWITTERAPI_IO_KEY"):
        return "twitterapi_io"
    sources = source_config.get("social_sources") or source_config.get("x_sources") or {"primary": "sample"}
    return sources["primary"]


def limit_from_env(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        return max(0, int(raw))
    except ValueError:
        return fallback


def optional_limit_from_env(name: str, fallback: int | None) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    if value < 0:
        return fallback
    return value


def limit_setting(limits: dict[str, Any], generic_name: str, legacy_name: str, fallback: int | None = None) -> int | None:
    return limits.get(generic_name, limits.get(legacy_name, fallback))


def apply_runtime_limits(x_source: Any, source_config: dict[str, Any]) -> dict[str, Any]:
    limits = source_config["limits"]
    configured_limit = limit_setting(limits, "max_source_requests_per_run", "max_x_api_requests_per_run")
    max_api_requests = optional_limit_from_env(
        "BRAND_RADAR_MAX_SOURCE_REQUESTS",
        optional_limit_from_env("X_MAX_API_REQUESTS", configured_limit),
    )
    configured_context_limit = limit_setting(
        limits,
        "max_context_requests_per_run",
        "max_conversation_context_requests_per_run",
    )
    max_context_requests = optional_limit_from_env(
        "BRAND_RADAR_MAX_CONTEXT_REQUESTS",
        optional_limit_from_env("CONVERSATION_CONTEXT_MAX_REQUESTS", configured_context_limit),
    )
    if hasattr(x_source, "max_requests_per_run"):
        x_source.max_requests_per_run = max_api_requests
    if hasattr(x_source, "max_context_requests_per_run"):
        x_source.max_context_requests_per_run = max_context_requests
    return {
        "max_api_requests": max_api_requests,
        "max_context_requests": max_context_requests,
    }


def source_request_stats(x_source: Any) -> dict[str, Any]:
    return {
        "api_requests_used": getattr(x_source, "requests_used", None),
        "max_api_requests": getattr(x_source, "max_requests_per_run", None),
        "request_budget_exhausted": bool(getattr(x_source, "request_budget_exhausted", False)),
        "context_requests_used": getattr(x_source, "context_requests_used", None),
        "max_context_requests": getattr(x_source, "max_context_requests_per_run", None),
        "context_request_budget_exhausted": bool(getattr(x_source, "context_request_budget_exhausted", False)),
    }


def configured_search_modes(source_config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_modes = source_config.get("social_search_modes") or source_config.get("x_search_modes") or [{"query_type": "Latest", "ratio": 1}]
    modes: list[dict[str, Any]] = []
    for mode in raw_modes:
        if isinstance(mode, str):
            query_type = mode
            ratio = 1
        else:
            query_type = mode.get("query_type", "Latest")
            ratio = mode.get("ratio", 1)
        query_type = "Top" if str(query_type).strip().lower() == "top" else "Latest"
        try:
            ratio_value = float(ratio)
        except (TypeError, ValueError):
            ratio_value = 1
        if ratio_value <= 0:
            continue
        modes.append({"query_type": query_type, "ratio": ratio_value})
    return modes or [{"query_type": "Latest", "ratio": 1}]


def query_limit_for_mode(brand_limit: int, query_count: int, modes: list[dict[str, Any]], mode: dict[str, Any]) -> int:
    total_ratio = sum(item["ratio"] for item in modes) or 1
    mode_brand_limit = brand_limit * mode["ratio"] / total_ratio
    return max(1, math.ceil(mode_brand_limit / max(1, query_count)))


def merge_duplicate_collection_context(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    for query_type in incoming.get("collection_query_types", []):
        existing.setdefault("collection_query_types", [])
        if query_type not in existing["collection_query_types"]:
            existing["collection_query_types"].append(query_type)


def apply_collection_caps(
    posts: list[dict[str, Any]],
    brand_limits: dict[str, int],
    max_total: int,
) -> list[dict[str, Any]]:
    capped: list[dict[str, Any]] = []
    brand_counts = {brand: 0 for brand in brand_limits}
    for post in posts:
        if len(capped) >= max_total:
            break
        brand = post.get("brand_candidate", "")
        brand_limit = brand_limits.get(brand, max_total)
        if brand_counts.get(brand, 0) >= brand_limit:
            continue
        capped.append(post)
        brand_counts[brand] = brand_counts.get(brand, 0) + 1
    return capped


def collect_real_posts(
    x_source: Any,
    keyword_config: dict[str, Any],
    source_config: dict[str, Any],
    start: Any,
    end: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limits = source_config["limits"]
    brand_limits = {
        "joybuy": limit_from_env(
            "BRAND_RADAR_PRIMARY_DAILY_LIMIT",
            limit_from_env("X_JOYBUY_DAILY_LIMIT", int(limit_setting(limits, "max_primary_posts_per_day", "max_joybuy_posts_per_day", 120) or 120)),
        ),
        "temu": limit_from_env(
            "BRAND_RADAR_COMPETITOR_DAILY_LIMIT",
            limit_from_env("X_TEMU_DAILY_LIMIT", int(limit_setting(limits, "max_competitor_posts_per_day", "max_temu_posts_per_day", 60) or 60)),
        ),
    }
    raw_posts: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    stopped_early = False
    search_modes = configured_search_modes(source_config)

    for brand_key in ("joybuy", "temu"):
        if stopped_early:
            break
        brand_limit = brand_limits.get(brand_key, 0)
        if brand_limit <= 0:
            continue
        queries = build_x_search_queries(keyword_config, brand_key)
        for mode in search_modes:
            if stopped_early:
                break
            query_type = mode["query_type"]
            per_query_limit = query_limit_for_mode(brand_limit, len(queries), search_modes, mode)
            for query in queries:
                try:
                    posts = x_source.search_posts(query, to_iso(start), to_iso(end), per_query_limit, query_type=query_type)
                except ProviderBudgetExceeded as error:
                    warnings.append(str(error))
                    stopped_early = True
                    break
                except RuntimeError as error:
                    warnings.append(f"Provider collection stopped after error: {str(error)[:240]}")
                    stopped_early = True
                    break
                for post in posts:
                    enriched = {
                        **post,
                        "brand_candidate": brand_key,
                        "collection_query_type": query_type,
                        "collection_query_types": [query_type],
                    }
                    post_id = enriched["post_id"]
                    existing = seen.get(post_id)
                    if existing and existing.get("brand_candidate") == "joybuy":
                        merge_duplicate_collection_context(existing, enriched)
                        continue
                    if existing and brand_key != "joybuy":
                        merge_duplicate_collection_context(existing, enriched)
                        continue
                    if existing:
                        merge_duplicate_collection_context(enriched, existing)
                    seen[post_id] = enriched

    max_total = limit_from_env("X_DAILY_LIMIT", limits["max_posts_per_day"])
    raw_posts = apply_collection_caps(list(seen.values()), brand_limits, max_total)
    request_stats = source_request_stats(x_source)
    return raw_posts, {
        "status": "partial" if warnings or request_stats["request_budget_exhausted"] else "complete",
        "warnings": warnings,
        "limits": {
            "max_posts": max_total,
            "max_primary_posts": brand_limits["joybuy"],
            "max_competitor_posts": brand_limits["temu"],
            "max_api_requests": request_stats["max_api_requests"],
        },
        "search_modes": search_modes,
        **request_stats,
    }


def checkpoint_payload(
    provider: str,
    raw_posts: list[dict[str, Any]],
    collection_status: dict[str, Any],
    start: Any,
    end: Any,
    today: str,
    window_label: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": to_iso(now_utc()),
        "provider": provider,
        "report_date": today,
        "window_start": to_iso(start),
        "window_end": to_iso(end),
        "window_label": window_label,
        "raw_posts": raw_posts,
        "collection_status": collection_status,
    }


def write_collection_checkpoint(
    provider: str,
    raw_posts: list[dict[str, Any]],
    collection_status: dict[str, Any],
    start: Any,
    end: Any,
    today: str,
    window_label: str,
) -> None:
    payload = checkpoint_payload(provider, raw_posts, collection_status, start, end, today, window_label)
    write_json(str(CHECKPOINT_PATH), payload)
    write_json(str(ROOT / "data" / "checkpoints" / "daily" / f"{today}.json"), payload)


def read_collection_checkpoint() -> dict[str, Any]:
    if not CHECKPOINT_PATH.exists():
        raise SystemExit(f"No local daily checkpoint found at {CHECKPOINT_PATH}. Run a normal local daily job first.")
    checkpoint = read_json(str(CHECKPOINT_PATH))
    if not checkpoint.get("raw_posts"):
        raise SystemExit(f"Local daily checkpoint has no raw posts: {CHECKPOINT_PATH}")
    return checkpoint


def main() -> None:
    args = parse_args()
    keyword_config = load_project_json("keywords.local.json")
    scoring_config = load_project_json("scoring.json")
    source_config = load_project_json("sources.local.json")
    if args.report_date:
        start, end = beijing_report_date_window(args.report_date)
    else:
        start, end = beijing_daily_window(now_utc())
    today = end.astimezone(BEIJING).strftime("%Y-%m-%d")
    window_label = f"{beijing_label(start)} - {beijing_label(end)}"
    x_source = None

    if args.resume_from_checkpoint:
        checkpoint = read_collection_checkpoint()
        provider = checkpoint["provider"]
        raw_posts = checkpoint["raw_posts"]
        collection_status = checkpoint["collection_status"]
        today = checkpoint["report_date"]
        window_label = checkpoint["window_label"]
        start = from_iso(checkpoint["window_start"])
        end = from_iso(checkpoint["window_end"])
        if args.attach_context_from_provider:
            x_source = get_x_source(provider)
            runtime_limits = apply_runtime_limits(x_source, source_config)
            collection_status["context_runtime_limits"] = runtime_limits
    else:
        provider = selected_provider(source_config)
        x_source = get_x_source(provider)
        runtime_limits = apply_runtime_limits(x_source, source_config)
        if hasattr(x_source, "all_posts"):
            raw_posts = x_source.all_posts()
            collection_status = {
                "status": "sample",
                "warnings": [],
                "limits": runtime_limits,
                "api_requests_used": 0,
                "max_api_requests": runtime_limits["max_api_requests"],
                "request_budget_exhausted": False,
            }
        else:
            raw_posts, collection_status = collect_real_posts(x_source, keyword_config, source_config, start, end)
            write_collection_checkpoint(provider, raw_posts, collection_status, start, end, today, window_label)

    translation_service = build_translation_service(provider)
    normalized = normalize_posts(raw_posts, keyword_config)
    translation_status = apply_translations(normalized, translation_service)
    collection_status["translation"] = translation_status
    if translation_status.get("missing_count"):
        message = (
            f"Chinese translation unavailable for {translation_status['missing_count']} "
            "non-Chinese posts; original text was used as fallback."
        )
        collection_status.setdefault("warnings", []).append(message)
    joybuy_clusters = cluster_posts(normalized, "joybuy")
    joybuy_clusters = score_clusters(joybuy_clusters, scoring_config)
    joybuy_clusters = attach_evidence_chains(joybuy_clusters)
    joybuy_clusters = update_fermentation(joybuy_clusters)
    conversation_status = attach_conversation_contexts(
        normalized,
        joybuy_clusters,
        x_source,
        translation_service,
        to_iso(start),
        to_iso(end),
    )
    collection_status["conversation_context"] = conversation_status
    if x_source:
        collection_status.update(source_request_stats(x_source))
    if conversation_status.get("warnings"):
        collection_status.setdefault("warnings", []).extend(conversation_status["warnings"])

    write_jsonl(str(ROOT / "data" / "raw" / "x" / f"{provider}-posts.jsonl"), raw_posts)
    write_jsonl(str(ROOT / "data" / "processed" / "normalized-posts.jsonl"), normalized)
    write_json(str(ROOT / "data" / "clusters" / "joybuy-clusters.json"), joybuy_clusters)

    overview = build_dashboard_data(
        joybuy_clusters,
        normalized,
        str(ROOT / "public" / "dashboard-data"),
        provider_hint=provider,
        report_date=today,
        window_label=window_label,
        collection_status=collection_status,
    )
    platform_trend_status = None
    if platform_trends_enabled() and not args.resume_from_checkpoint:
        try:
            platform_source = get_x_source(provider)
            platform_trend_status = collect_platform_trends(
                platform_source,
                translation_service,
                provider,
                start,
                end,
                today,
                window_label,
                str(ROOT / "public" / "dashboard-data"),
            )
        except Exception as error:
            platform_trend_status = {
                "status": "partial",
                "accepted": 0,
                "candidates_inspected": 0,
                "warnings": [f"Platform trend collection failed: {str(error)[:180]}"],
            }
    run_log = {
        "status": "ok",
        "generated_at": to_iso(now_utc()),
        "window_start": to_iso(start),
        "window_end": to_iso(end),
        "window_label": window_label,
        "provider": provider,
        "raw_posts": len(raw_posts),
        "normalized_posts": len(normalized),
        "joybuy_clusters": len(joybuy_clusters),
        "collection_status": collection_status,
        "translation_status": translation_status,
        "platform_trends": platform_trend_status,
        "dashboard_metrics": overview["metrics"],
    }
    public_run_log = {
        "status": run_log["status"],
        "generated_at": run_log["generated_at"],
        "window_start": run_log["window_start"],
        "window_end": run_log["window_end"],
        "window_label": run_log["window_label"],
        "raw_posts": run_log["raw_posts"],
        "normalized_posts": run_log["normalized_posts"],
        "primary_signals": run_log["joybuy_clusters"],
        "collection_status": public_collection_status_payload(collection_status),
        "platform_trends": {
            "status": platform_trend_status.get("status"),
            "accepted": platform_trend_status.get("accepted"),
            "candidates_inspected": platform_trend_status.get("candidates_inspected"),
            "warnings": platform_trend_status.get("warnings", []),
        } if platform_trend_status else None,
        "dashboard_metrics": overview["metrics"],
    }
    write_json(str(ROOT / "public" / "dashboard-data" / "run-status.json"), public_run_log)
    write_json(str(ROOT / "data" / "logs" / f"daily-{today}.json"), run_log)
    print(f"Generated dashboard data: {overview['generated_at_label']}")
    print(f"Primary signals: {len(joybuy_clusters)}")
    print(f"Raw posts: {len(raw_posts)}")
    print(f"Collection status: {collection_status['status']}")
    print(f"Translation missing: {translation_status.get('missing_count', 0)}")
    if collection_status.get("warnings"):
        print(f"Collection warnings: {len(collection_status['warnings'])}")
    if platform_trend_status:
        print(
            "Platform trends: "
            f"{platform_trend_status.get('accepted', 0)} accepted / "
            f"{platform_trend_status.get('candidates_inspected', 0)} candidates"
        )


if __name__ == "__main__":
    main()
