#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.lazy_payloads import prune_unreferenced_lazy_payloads, shard_conversation_contexts, shard_tg_replies


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        data_root = Path(temp_dir) / "dashboard-data"
        payload = {
            "date": "2026-09-07",
            "items": [
                {
                    "post_id": "anchor-1",
                    "conversation_context": {
                        "anchor_post_id": "anchor-1",
                        "summary_zh": "上下文摘要",
                        "posts": [
                            {"post_id": "parent", "text": "parent"},
                            {"post_id": "anchor-1", "text": "anchor"},
                        ],
                    },
                    "message_id": "42",
                    "replies": [{"id": "1", "text": "评论", "media": []}],
                }
            ],
        }

        context_stats = shard_conversation_contexts(payload, data_root)
        reply_stats = shard_tg_replies(payload, data_root)
        item = payload["items"][0]

        assert context_stats == {"contexts": 1, "posts": 2}
        assert reply_stats == {"threads": 1, "replies": 1}
        assert "posts" not in item["conversation_context"]
        assert item["conversation_context"]["post_count"] == 2
        assert "replies" not in item
        assert item["replies_visible"] == 1

        context_path = data_root.parent / item["conversation_context"]["detail_path"]
        replies_path = data_root.parent / item["replies_path"]
        assert json.loads(context_path.read_text(encoding="utf-8"))["posts"][0]["post_id"] == "parent"
        assert json.loads(replies_path.read_text(encoding="utf-8"))["replies"][0]["id"] == "1"

        orphan_path = data_root / "lazy" / "conversations" / "orphan.json"
        orphan_path.write_text("{}", encoding="utf-8")
        owner_path = data_root / "owner.json"
        owner_path.write_text(json.dumps(payload), encoding="utf-8")
        assert prune_unreferenced_lazy_payloads(data_root) == 1
        assert context_path.exists()
        assert replies_path.exists()
        assert not orphan_path.exists()

        assert shard_conversation_contexts(payload, data_root)["contexts"] == 0
        assert shard_tg_replies(payload, data_root)["threads"] == 0

    print("Lazy payload tests passed.")


if __name__ == "__main__":
    main()
