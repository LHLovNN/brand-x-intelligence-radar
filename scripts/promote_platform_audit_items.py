#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.platform_trends import (  # noqa: E402
    PLATFORM_KEY,
    normalize_platform_post,
    passes_platform_metric_gate,
    platform_config,
    platform_index,
    public_platform_items,
    public_translation_status,
    score_platform_post,
)
from src.pipeline.conversation_context import (  # noqa: E402
    build_context_for_post,
    filter_context_noise,
    filter_thread_context_rows,
    prepare_context_rows,
)
from src.pipeline.dashboard_builder import write_data_bundle  # noqa: E402
from src.pipeline.lazy_payloads import shard_json_file  # noqa: E402
from src.pipeline.translation import build_translation_service, needs_translation, translation_report  # noqa: E402
from src.utils.config import load_project_json  # noqa: E402
from src.utils.io import read_json  # noqa: E402
from src.utils.time import beijing_label, now_utc, to_iso  # noqa: E402


class PromotionError(RuntimeError):
    pass


class AtomicWriteError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote user-reviewed platform items from the local rejection audit without recollecting data."
    )
    parser.add_argument("--date", required=True, metavar="YYYY-MM-DD", help="Report date to correct.")
    parser.add_argument(
        "--post-id",
        action="append",
        required=True,
        dest="post_ids",
        help="Post ID to promote. Repeat this option for multiple posts.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate and print the result without writing files.")
    parser.add_argument(
        "--source-threads-json",
        type=Path,
        help=(
            "Optional provider thread data keyed by post ID. When supplied, promoted cards retain "
            "author profiles, media URLs and available conversation context."
        ),
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=ROOT / "public" / "dashboard-data",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=ROOT / "data" / "audits" / "platform-trends" / PLATFORM_KEY / "daily",
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    requested_ids = unique_nonempty(args.post_ids)
    if not requested_ids:
        raise SystemExit("At least one non-empty --post-id is required.")

    data_root = args.data_root.resolve()
    platform_dir = data_root / "platform-trends" / PLATFORM_KEY
    daily_path = platform_dir / "daily" / f"{args.date}.json"
    latest_path = platform_dir / "latest.json"
    index_path = platform_dir / "index.json"
    audit_path = args.audit_dir.resolve() / f"{args.date}.json"
    for path, label in (
        (daily_path, "platform daily payload"),
        (latest_path, "platform latest payload"),
        (index_path, "platform index payload"),
        (audit_path, "platform rejection audit"),
    ):
        if not path.exists():
            raise SystemExit(f"Missing {label}: {path}")

    daily = read_json(str(daily_path))
    latest = read_json(str(latest_path))
    audit = read_json(str(audit_path))
    if str(daily.get("date") or "") != args.date:
        raise SystemExit(f"Daily payload date does not match --date: {daily.get('date')}")
    if str(latest.get("date") or "") != args.date:
        raise SystemExit(
            "Offline promotion only updates the current platform day; "
            f"latest is {latest.get('date') or 'unknown'}, requested {args.date}."
        )
    if daily != latest:
        raise SystemExit("Platform daily and latest payloads differ; reconcile them before promoting audit items.")
    if str(audit.get("date") or "") != args.date:
        raise SystemExit(f"Audit date does not match --date: {audit.get('date')}")

    config = load_project_json("platform_trends.local.json")
    platform = platform_config(config)
    source_threads = load_source_threads(args.source_threads_json) if args.source_threads_json else None
    summary_service = build_translation_service("twitterapi_io") if source_threads is not None else None
    now = now_utc()
    try:
        plan = build_promotion_plan(
            daily,
            audit,
            platform,
            requested_ids,
            generated_at=to_iso(now),
            generated_at_label=beijing_label(now),
            source_threads=source_threads,
            summary_service=summary_service,
        )
    except PromotionError as error:
        raise SystemExit(str(error)) from error

    result = {
        "date": args.date,
        "requested_ids": requested_ids,
        "promoted_ids": plan["promoted_ids"],
        "already_present_ids": plan["already_present_ids"],
        "accepted_count": len(plan["payload"].get("items") or []),
        "audit_rejected_count": len(plan["audit"].get("items") or []),
        "dry_run": bool(args.dry_run),
    }
    if args.dry_run or not plan["changed"]:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    index = platform_index(platform_dir, plan["payload"])
    pending_files = {
        daily_path: encoded_json(plan["payload"]),
        latest_path: encoded_json(plan["payload"]),
        index_path: encoded_json(index),
        audit_path: encoded_json(plan["audit"]),
    }
    try:
        atomic_replace_files(pending_files)
    except AtomicWriteError as error:
        raise SystemExit(str(error)) from error
    shard_json_file(daily_path, data_root)
    shard_json_file(latest_path, data_root)
    write_data_bundle(data_root.parent / "dashboard-data-bundle.js", {})
    print(json.dumps(result, ensure_ascii=False, indent=2))


def build_promotion_plan(
    payload: dict[str, Any],
    audit: dict[str, Any],
    platform: dict[str, Any],
    requested_ids: list[str],
    *,
    generated_at: str,
    generated_at_label: str,
    source_threads: dict[str, list[dict[str, Any]]] | None = None,
    summary_service: Any | None = None,
) -> dict[str, Any]:
    requested_ids = unique_nonempty(requested_ids)
    items = deepcopy(list(payload.get("items") or []))
    existing_by_id = unique_records_by_id(items, "public platform payload")
    audit_items = deepcopy(list(audit.get("items") or []))
    audit_by_id = unique_records_by_id(audit_items, "platform rejection audit")

    missing_ids = [post_id for post_id in requested_ids if post_id not in existing_by_id and post_id not in audit_by_id]
    if missing_ids:
        raise PromotionError("Requested post IDs are absent from both public data and audit: " + ", ".join(missing_ids))

    already_present_ids = [post_id for post_id in requested_ids if post_id in existing_by_id]
    pending_ids = [post_id for post_id in requested_ids if post_id not in existing_by_id]
    restored_items: list[dict[str, Any]] = []
    failures: list[str] = []
    promoted_context_attempted = 0
    promoted_context_attached = 0
    promoted_context_filtered_noise = 0
    promoted_context_summary_counts: Counter[str] = Counter()
    min_views = int((payload.get("collection_status") or {}).get("min_views") or platform.get("min_views_per_item") or 0)
    min_likes = int((payload.get("collection_status") or {}).get("min_likes") or platform.get("min_likes_per_item") or 0)

    for post_id in pending_ids:
        audit_item = audit_by_id[post_id]
        source_rows = list((source_threads or {}).get(post_id) or [])
        source_post = audit_item_as_source_post(audit_item)
        if source_threads is not None:
            if not source_rows:
                failures.append(f"{post_id}: source thread data is missing")
                continue
            source_post = next(
                (row for row in source_rows if str(row.get("post_id") or "") == post_id),
                None,
            )
            if not source_post:
                failures.append(f"{post_id}: source thread data does not contain the anchor post")
                continue
            source_error = enriched_source_error(audit_item, source_post)
            if source_error:
                failures.append(f"{post_id}: {source_error}")
                continue

        normalized = normalize_platform_post(source_post, platform)
        if not passes_platform_metric_gate(normalized, min_views, min_likes):
            failures.append(f"{post_id}: no longer meets the public metric gate")
            continue
        decision = score_platform_post(normalized, platform)
        if not decision.get("accepted"):
            failures.append(f"{post_id}: current rule score rejected it ({decision.get('reason_code') or 'unknown'})")
            continue
        normalized.update(decision.get("item") or {})
        if needs_translation(normalized):
            failures.append(f"{post_id}: audit has no Chinese translation, so it cannot be promoted offline")
            continue
        display_text = str(normalized.get("clean_text") or normalized.get("text") or "").strip()
        if not display_text:
            failures.append(f"{post_id}: audit text is empty")
            continue
        normalized["translation_zh"] = display_text
        normalized["translation_status"] = "source_chinese"
        normalized["conversation_context"] = {}
        if source_rows:
            promoted_context_attempted += 1
            context_rows = filter_thread_context_rows(normalized, source_rows)
            context_rows, removed = filter_context_noise(context_rows)
            promoted_context_filtered_noise += removed
            prepared_rows = prepare_context_rows(context_rows, summary_service)
            context = build_context_for_post(normalized, prepared_rows, summary_service)
            if context and len(context.get("posts") or []) > 1:
                normalized["conversation_context"] = context
                promoted_context_attached += 1
                promoted_context_summary_counts[str(context.get("summary_status") or "fallback")] += 1
        restored_items.extend(public_platform_items([normalized]))

    if failures:
        raise PromotionError("Offline promotion validation failed: " + "; ".join(failures))

    items.extend(restored_items)
    items.sort(key=lambda item: str(item.get("created_at") or item.get("time") or ""), reverse=True)
    if len({str(item.get("post_id") or "") for item in items}) != len(items):
        raise PromotionError("Promotion would create duplicate post IDs in the public payload.")

    resolved_audit_ids = {post_id for post_id in requested_ids if post_id in audit_by_id}
    remaining_audit_items = [item for item in audit_items if str(item.get("post_id") or "") not in resolved_audit_ids]
    changed = bool(restored_items or resolved_audit_ids)
    if not changed:
        return {
            "payload": deepcopy(payload),
            "audit": deepcopy(audit),
            "promoted_ids": [],
            "already_present_ids": already_present_ids,
            "changed": False,
        }

    updated_payload = deepcopy(payload)
    updated_payload["generated_at"] = generated_at
    updated_payload["generated_at_label"] = generated_at_label
    updated_payload["items"] = items
    collection_status = deepcopy(updated_payload.get("collection_status") or {})
    collection_status["accepted_count"] = len(items)
    configured = bool((collection_status.get("translation") or {}).get("configured", True))
    translation_status = public_translation_status(
        translation_report(items, "offline_audit_promotion" if configured else "none")
    )
    translation_status["configured"] = configured
    collection_status["translation"] = translation_status

    if promoted_context_attempted:
        context_status = deepcopy(collection_status.get("conversation_context") or {})
        context_status["attempted"] = int(context_status.get("attempted") or 0) + promoted_context_attempted
        context_status["eligible"] = max(
            int(context_status.get("eligible") or 0) + promoted_context_attempted,
            context_status["attempted"],
        )
        context_status["attached"] = int(context_status.get("attached") or 0) + promoted_context_attached
        context_status["unresolved"] = int(context_status.get("unresolved") or 0) + (
            promoted_context_attempted - promoted_context_attached
        )
        context_status["filtered_noise"] = int(context_status.get("filtered_noise") or 0) + promoted_context_filtered_noise
        summary_counts = Counter(context_status.get("summary") or {})
        summary_counts.update(promoted_context_summary_counts)
        context_status["summary"] = dict(summary_counts)
        collection_status["conversation_context"] = context_status

    semantic_rejections = [
        item for item in remaining_audit_items if str((item.get("rejection") or {}).get("stage") or "") == "semantic_review"
    ]
    semantic_review = deepcopy(collection_status.get("semantic_review") or {})
    if semantic_review or semantic_rejections:
        semantic_review["rejected_count"] = len(semantic_rejections)
        semantic_input_count = int(semantic_review.get("reviewed_count") or 0) + int(
            semantic_review.get("fallback_count") or 0
        )
        semantic_review["accepted_count"] = max(0, semantic_input_count - len(semantic_rejections))
        semantic_review["rejection_reasons"] = count_rejection_values(semantic_rejections, "reason_code")
        collection_status["semantic_review"] = semantic_review
    collection_status["semantic_filtered"] = len(semantic_rejections)
    updated_payload["collection_status"] = collection_status

    summary = deepcopy(updated_payload.get("summary") or {})
    summary["accepted"] = len(items)
    summary["semantic_filtered"] = len(semantic_rejections)
    updated_payload["summary"] = summary

    updated_audit = deepcopy(audit)
    updated_audit["generated_at"] = generated_at
    updated_audit["items"] = remaining_audit_items
    audit_summary = deepcopy(updated_audit.get("summary") or {})
    metric_eligible_count = int(
        audit_summary.get("metric_eligible_count")
        or int(audit_summary.get("accepted_count") or 0) + int(audit_summary.get("rejected_count") or len(audit_items))
    )
    audit_summary["metric_eligible_count"] = metric_eligible_count
    audit_summary["accepted_count"] = len(items)
    audit_summary["rejected_count"] = len(remaining_audit_items)
    audit_summary["expected_rejected_count"] = max(0, metric_eligible_count - len(items))
    audit_summary["count_matches"] = len(remaining_audit_items) == audit_summary["expected_rejected_count"]
    audit_summary["stage_counts"] = count_rejection_values(remaining_audit_items, "stage")
    audit_summary["reason_counts"] = count_rejection_values(remaining_audit_items, "reason_code")
    if not audit_summary["count_matches"]:
        raise PromotionError(
            "Audit invariant failed after promotion: "
            f"metric eligible {metric_eligible_count}, accepted {len(items)}, rejected {len(remaining_audit_items)}."
        )
    updated_audit["summary"] = audit_summary

    return {
        "payload": updated_payload,
        "audit": updated_audit,
        "promoted_ids": pending_ids,
        "already_present_ids": already_present_ids,
        "changed": True,
    }


def audit_item_as_source_post(item: dict[str, Any]) -> dict[str, Any]:
    author = item.get("author") or {}
    metrics = item.get("metrics") or {}
    return {
        "post_id": str(item.get("post_id") or ""),
        "created_at": item.get("created_at"),
        "url": item.get("url"),
        "language": item.get("language") or "und",
        "text": item.get("text") or "",
        "author_id": author.get("id"),
        "author_name": author.get("name"),
        "author_handle": author.get("handle"),
        "author_avatar_url": "",
        "author_followers": 0,
        "author_following": 0,
        "author_bio": "",
        "author_location": "",
        "author_joined_at": "",
        "author_verified": False,
        "reply_to_post_id": None,
        "reply_to_handle": None,
        "quoted_post_id": None,
        "conversation_id": None,
        # The rejection audit intentionally stores only media counts/types. Reusing those
        # as media objects would create broken cards, so offline promotion leaves media empty.
        "media": [],
        "links": item.get("links") or [],
        "like_count": metrics.get("likes"),
        "repost_count": metrics.get("reposts"),
        "reply_count": metrics.get("replies"),
        "quote_count": metrics.get("quotes"),
        "bookmark_count": metrics.get("bookmarks"),
        "view_count": metrics.get("views"),
    }


def load_source_threads(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        payload = read_json(str(path.resolve()))
    except Exception as error:
        raise SystemExit(f"Unable to read source thread data: {path}") from error
    if not isinstance(payload, dict):
        raise SystemExit("Source thread data must be a JSON object keyed by post ID.")
    result: dict[str, list[dict[str, Any]]] = {}
    for post_id, rows in payload.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise SystemExit(f"Source thread data for {post_id} must be a list of post objects.")
        result[str(post_id)] = rows
    return result


def enriched_source_error(audit_item: dict[str, Any], source_post: dict[str, Any]) -> str:
    if not str(source_post.get("author_avatar_url") or "").strip():
        return "source post is missing the author avatar"
    if source_post.get("author_followers") is None or source_post.get("author_following") is None:
        return "source post is missing author follower/following counts"
    if not str(source_post.get("conversation_id") or "").strip():
        return "source post is missing its conversation ID"
    expected_media = int(((audit_item.get("media") or {}).get("count") or 0))
    actual_media = len(source_post.get("media") or [])
    if actual_media < expected_media:
        return f"source post has {actual_media} media item(s), expected at least {expected_media}"
    return ""


def unique_records_by_id(items: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for item in items:
        post_id = str(item.get("post_id") or "").strip()
        if not post_id:
            raise PromotionError(f"{label} contains an item without post_id.")
        if post_id in records:
            raise PromotionError(f"{label} contains duplicate post_id {post_id}.")
        records[post_id] = item
    return records


def count_rejection_values(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = Counter(
        str((item.get("rejection") or {}).get(key) or "final_filter")
        for item in items
    )
    return dict(values)


def unique_nonempty(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def encoded_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic_replace_files(
    pending_files: dict[Path, bytes],
    replace_func: Callable[[str, str], Any] = os.replace,
) -> None:
    if not pending_files:
        return
    new_temps: dict[Path, Path] = {}
    backup_temps: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for target, content in pending_files.items():
            if not target.exists():
                raise AtomicWriteError(f"Atomic promotion target is missing: {target}")
            mode = target.stat().st_mode & 0o777
            new_temps[target] = write_sibling_temp(target, content, mode, "new")
            backup_temps[target] = write_sibling_temp(target, target.read_bytes(), mode, "backup")

        for target in pending_files:
            replace_func(str(new_temps[target]), str(target))
            replaced.append(target)
    except Exception as error:
        rollback_errors: list[str] = []
        for target in reversed(replaced):
            backup = backup_temps.get(target)
            if not backup or not backup.exists():
                rollback_errors.append(f"missing backup for {target}")
                continue
            try:
                replace_func(str(backup), str(target))
            except Exception as rollback_error:
                rollback_errors.append(f"{target}: {rollback_error}")
        detail = f"Atomic platform promotion failed and was rolled back: {error}"
        if rollback_errors:
            detail += "; rollback errors: " + "; ".join(rollback_errors)
        raise AtomicWriteError(detail) from error
    finally:
        for temp_path in [*new_temps.values(), *backup_temps.values()]:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def write_sibling_temp(target: Path, content: bytes, mode: int, label: str) -> Path:
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.{label}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temp_path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temp_path, mode)
        return temp_path
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temp_path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
