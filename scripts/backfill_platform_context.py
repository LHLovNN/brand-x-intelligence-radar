#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters.provider_factory import get_x_source
from src.pipeline.platform_trends import (
    PLATFORM_KEY,
    apply_platform_runtime_limits,
    dedupe_contextual_items_keep_earliest,
    public_platform_items,
    public_translation_status,
    refresh_context_status_for_items,
    write_platform_payload,
)
from src.pipeline.translation import build_translation_service, translation_report
from src.pipeline.conversation_context import attach_conversation_contexts
from src.utils.config import load_project_json
from src.utils.io import read_json
from src.utils.time import beijing_label, beijing_report_date_window, now_utc, to_iso


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill conversation context for existing platform trend items.")
    parser.add_argument("--date", required=True, metavar="YYYY-MM-DD", help="Platform trend report date to backfill.")
    parser.add_argument(
        "--platform",
        default=PLATFORM_KEY,
        choices=[PLATFORM_KEY],
        help="Platform key. Currently only xiaohongshu is supported.",
    )
    return parser.parse_args()


def selected_provider() -> str:
    explicit = os.getenv("X_SOURCE_PROVIDER")
    if explicit:
        return explicit
    if os.getenv("TWITTERAPI_IO_KEY"):
        return "twitterapi_io"
    return "sample"


def context_clusters(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "post_ids": [item.get("post_id")],
            "score": {"ips": item.get("quality_score") or item.get("score_value") or 0},
        }
        for item in items
    ]


def main() -> None:
    args = parse_args()
    data_root = ROOT / "public" / "dashboard-data"
    payload_path = data_root / "platform-trends" / args.platform / "daily" / f"{args.date}.json"
    if not payload_path.exists():
        raise SystemExit(f"Missing platform trend payload: {payload_path}")

    payload = read_json(str(payload_path))
    items = list(payload.get("items") or [])
    if not items:
        raise SystemExit(f"No platform trend items found in {payload_path}")
    for item in items:
        item["is_relevant"] = True

    start, end = beijing_report_date_window(args.date)
    provider = selected_provider()
    platform_config = load_project_json("platform_trends.local.json")
    x_source = get_x_source(provider)
    runtime_limits = apply_platform_runtime_limits(x_source, platform_config)
    translation_service = build_translation_service(provider)

    context_status = attach_conversation_contexts(
        items,
        context_clusters(items),
        x_source,
        translation_service,
        to_iso(start),
        to_iso(end),
        allow_anchor_threads=True,
    )

    original_count = len(items)
    items, context_deduped = dedupe_contextual_items_keep_earliest(items)
    if context_deduped:
        context_status["deduped_after_context"] = context_deduped
        refresh_context_status_for_items(context_status, items)
    items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)

    translation_status = translation_report(items, getattr(translation_service, "provider_name", "none"))
    collection_status = dict(payload.get("collection_status") or {})
    collection_status["accepted_count"] = len(items)
    collection_status["translation"] = public_translation_status(translation_status)
    collection_status["conversation_context"] = context_status

    summary = dict(payload.get("summary") or {})
    summary["accepted"] = len(items)
    summary["conversation_deduped"] = int(summary.get("conversation_deduped") or 0) + context_deduped

    now = now_utc()
    updated = {
        **payload,
        "generated_at": to_iso(now),
        "generated_at_label": beijing_label(now),
        "items": public_platform_items(items),
        "collection_status": collection_status,
        "summary": summary,
    }
    write_platform_payload(data_root, updated)

    request_stats = {
        "context_requests_used": getattr(x_source, "context_requests_used", None),
        "max_context_requests": getattr(x_source, "max_context_requests_per_run", None),
        "context_request_budget_exhausted": bool(getattr(x_source, "context_request_budget_exhausted", False)),
    }
    print(
        {
            "date": args.date,
            "platform": args.platform,
            "original_items": original_count,
            "items": len(items),
            "context": context_status,
            "runtime_limits": runtime_limits,
            "request_stats": request_stats,
        }
    )


if __name__ == "__main__":
    main()
