from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from src.utils.io import write_json


LAZY_DATA_DIR = "lazy"
CONVERSATION_DIR = "conversations"
TG_REPLIES_DIR = "tg-replies"


def shard_conversation_contexts(payload: Any, data_root: Path) -> dict[str, int]:
    stats = {"contexts": 0, "posts": 0}
    for owner in walk_dicts(payload):
        context = owner.get("conversation_context")
        if not isinstance(context, dict):
            continue
        posts = context.get("posts")
        if not isinstance(posts, list) or not posts:
            continue

        context_id = stable_payload_id(
            context.get("anchor_post_id") or owner.get("post_id") or owner.get("id") or "conversation",
            context,
        )
        relative_path = f"dashboard-data/{LAZY_DATA_DIR}/{CONVERSATION_DIR}/{context_id}.json"
        target_path = data_root / LAZY_DATA_DIR / CONVERSATION_DIR / f"{context_id}.json"
        write_json(str(target_path), context)

        owner["conversation_context"] = {
            **{key: value for key, value in context.items() if key != "posts"},
            "post_count": len(posts),
            "detail_path": relative_path,
        }
        stats["contexts"] += 1
        stats["posts"] += len(posts)
    return stats


def shard_tg_replies(payload: Any, data_root: Path, date: str = "") -> dict[str, int]:
    stats = {"threads": 0, "replies": 0}
    report_date = str(date or (payload.get("date") if isinstance(payload, dict) else "") or "unknown")
    for owner in walk_dicts(payload):
        replies = owner.get("replies")
        if not isinstance(replies, list):
            continue
        owner.pop("replies", None)
        owner["replies_visible"] = len(replies)
        if not replies:
            continue

        thread_id = stable_payload_id(
            owner.get("message_id") or owner.get("id") or owner.get("url") or "thread",
            replies,
        )
        relative_path = f"dashboard-data/{LAZY_DATA_DIR}/{TG_REPLIES_DIR}/{report_date}/{thread_id}.json"
        target_path = data_root / LAZY_DATA_DIR / TG_REPLIES_DIR / report_date / f"{thread_id}.json"
        write_json(
            str(target_path),
            {
                "schema_version": 1,
                "date": report_date,
                "thread_id": str(owner.get("message_id") or owner.get("id") or ""),
                "count": len(replies),
                "replies": replies,
            },
        )
        owner["replies_path"] = relative_path
        stats["threads"] += 1
        stats["replies"] += len(replies)
    return stats


def shard_json_file(path: Path, data_root: Path, *, shard_replies: bool = False) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    context_stats = shard_conversation_contexts(payload, data_root)
    reply_stats = shard_tg_replies(payload, data_root) if shard_replies else {"threads": 0, "replies": 0}
    if context_stats["contexts"] or reply_stats["threads"]:
        write_json(str(path), payload)
    return {**context_stats, **reply_stats}


def prune_unreferenced_lazy_payloads(data_root: Path) -> int:
    referenced: set[str] = set()
    for path in data_root.rglob("*.json"):
        if LAZY_DATA_DIR in path.relative_to(data_root).parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for owner in walk_dicts(payload):
            for key in ("detail_path", "replies_path"):
                relative_path = normalized_lazy_path(owner.get(key))
                if relative_path:
                    referenced.add(relative_path)

    removed = 0
    lazy_root = data_root / LAZY_DATA_DIR
    if not lazy_root.exists():
        return removed
    for path in lazy_root.rglob("*.json"):
        relative_path = path.relative_to(data_root.parent).as_posix()
        if relative_path not in referenced:
            path.unlink()
            removed += 1
    return removed


def normalized_lazy_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").lstrip("./")
    if not path.startswith(f"dashboard-data/{LAZY_DATA_DIR}/") or ".." in path.split("/"):
        return ""
    return path


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def stable_payload_id(seed: Any, payload: Any) -> str:
    label = re.sub(r"[^A-Za-z0-9_-]+", "-", str(seed or "item")).strip("-")[:48] or "item"
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:12]
    return f"{label}-{digest}"
