#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.lazy_payloads import shard_conversation_contexts, shard_tg_replies
from src.utils.io import write_json
from scripts.sync_dt_digests import compact_digest_index_entry


def main() -> None:
    data_root = ROOT / "public" / "dashboard-data"
    changed_files = 0
    context_count = 0
    reply_threads = 0
    for path in sorted(data_root.rglob("*.json")):
        if "lazy" in path.relative_to(data_root).parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        contexts = shard_conversation_contexts(payload, data_root)
        replies = {"threads": 0, "replies": 0}
        if path.parent.name == "tg" and path.parent.parent.name == "daily":
            replies = shard_tg_replies(payload, data_root, str(payload.get("date") or path.stem))
        if contexts["contexts"] or replies["threads"]:
            write_json(str(path), payload)
            changed_files += 1
            context_count += contexts["contexts"]
            reply_threads += replies["threads"]
    index_path = data_root / "dt-digests" / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        compact_items = [compact_digest_index_entry(item) for item in index.get("items") or []]
        if compact_items != index.get("items"):
            index["items"] = compact_items
            write_json(str(index_path), index)
            changed_files += 1
    print(
        f"Lazy payload migration complete: {changed_files} files, "
        f"{context_count} context references, {reply_threads} TG reply threads."
    )


if __name__ == "__main__":
    main()
