#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.content_policy import platform_noise_reason, tg_reply_policy_reason
from src.pipeline.platform_trends import platform_index
from src.utils.io import write_json


def main() -> None:
    data_root = ROOT / "public" / "dashboard-data"
    platform_dir = data_root / "platform-trends" / "xiaohongshu"
    changed = 0
    removed = 0
    paths = [platform_dir / "latest.json", *sorted((platform_dir / "daily").glob("*.json"))]
    for path in paths:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("items") or []
        kept = [item for item in items if platform_noise_reason(platform_item_policy_text(item)) is None]
        if len(kept) == len(items):
            continue
        removed += len(items) - len(kept)
        payload["items"] = kept
        if isinstance(payload.get("summary"), dict):
            payload["summary"]["accepted"] = len(kept)
        if isinstance(payload.get("collection_status"), dict):
            payload["collection_status"]["accepted_count"] = len(kept)
        write_json(str(path), payload)
        changed += 1

    latest_path = platform_dir / "latest.json"
    if latest_path.exists():
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        write_json(str(platform_dir / "index.json"), platform_index(platform_dir, latest))
    tg_changed, tg_removed = reapply_tg_reply_policy(data_root)
    print(
        "Reapplied public content policy: "
        f"{removed} Xiaohongshu items removed from {changed} payloads; "
        f"{tg_removed} TG replies removed from {tg_changed} threads."
    )


def platform_item_policy_text(item: dict) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("text", "clean_text", "original_text", "translation_zh", "author_name", "author_handle", "author_bio")
    )


def reapply_tg_reply_policy(data_root: Path) -> tuple[int, int]:
    changed_threads = 0
    removed_replies = 0
    daily_root = data_root / "dt-digests" / "daily" / "tg"
    for daily_path in sorted(daily_root.glob("*.json")):
        daily = json.loads(daily_path.read_text(encoding="utf-8"))
        daily_changed = False
        for section in daily.get("sections") or []:
            for item in section.get("items") or []:
                relative_path = str(item.get("replies_path") or "").strip()
                if not relative_path:
                    continue
                reply_path = ROOT / "public" / relative_path
                if not reply_path.exists():
                    continue
                payload = json.loads(reply_path.read_text(encoding="utf-8"))
                replies = payload.get("replies") or []
                kept = [reply for reply in replies if not tg_reply_policy_reason(
                    str(reply.get("text") or ""),
                    str(reply.get("sender_name") or ""),
                    bool(reply.get("media")),
                )]
                if len(kept) == len(replies):
                    continue
                removed_replies += len(replies) - len(kept)
                changed_threads += 1
                payload["replies"] = kept
                payload["count"] = len(kept)
                write_json(str(reply_path), payload)
                item["replies_visible"] = len(kept)
                fetched = int(item.get("replies_fetched") or len(replies))
                item["replies_filtered"] = max(0, fetched - len(kept))
                daily_changed = True
        if daily_changed:
            write_json(str(daily_path), daily)
    return changed_threads, removed_replies


if __name__ == "__main__":
    main()
