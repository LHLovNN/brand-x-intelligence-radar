#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT))

from src.pipeline.dashboard_builder import asset_cache_token, refresh_index_asset_versions, write_data_bundle
from src.utils.io import write_json


DEFAULT_BASE_URL = "https://codew1028.github.io/dt"
DEFAULT_DETAIL_DAYS = 60
DEFAULT_BUNDLE_DETAIL_DAYS = 7
STRUCTURED_TG_JSON_START_DATE = "2026-08-19"
KIND_LABELS = {
    "ai": "AI 日报",
    "tg": "TG 日报",
}
KIND_SLUGS = {
    "ai": "ai-daily",
    "tg": "tg-daily",
}
SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(ghp|github_pat)_[A-Za-z0-9_]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}", re.IGNORECASE),
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{24,}"),
]
TG_LOW_VALUE_ADULT_PATTERNS = [
    re.compile(r"打飞机|撸管|约炮|找炮友|炮友|曰炮", re.IGNORECASE),
    re.compile(r"解决性欲|性欲成本|全民打飞机", re.IGNORECASE),
    re.compile(r"只入身体.{0,30}不入生活", re.IGNORECASE),
]
TG_SHORT_STATUS_CHATTER_RE = re.compile(
    r"(?:挂了|又挂|崩了|炸了|宕机|不能用|用不了|不可用|打不开)",
    re.IGNORECASE,
)
TG_SHORT_CHATTER_RE = re.compile(r"什么情况|真的假的|咋回事|有人知道|笑死|离谱|绷不住", re.IGNORECASE)
TG_FILTER_REASON_LABELS = {
    "low_value_adult": "低俗成人向低价值内容",
    "short_status_chatter": "无摘要短状态闲聊",
}
TG_REPLY_BLOCK_PATTERNS = [
    re.compile(r"打飞机|撸管|约炮|找炮友|炮友|裸聊|色情网|成人视频|情色|援交|招嫖|嫖娼|外围", re.IGNORECASE),
    re.compile(r"加(?:微信|薇|v|qq)|私聊.{0,12}(?:资源|福利|群)|点击.{0,10}(?:领取|下载)|博彩|网赌|现金网|返佣", re.IGNORECASE),
    re.compile(r"傻逼|脑残|滚蛋|去死|死全家", re.IGNORECASE),
    re.compile(r"买枪|卖枪|毒品|冰毒|K粉|代办身份证|洗钱", re.IGNORECASE),
]
TG_REPLY_LOW_SIGNAL_RE = re.compile(r"^(哈+|哈哈哈+|笑死|666+|顶|蹲|mark|收藏|学习了|\+1|牛+|牛逼|nb|ok|好)$", re.IGNORECASE)
TG_MARKDOWN_CHANNEL_LINK = r"\[[^\]\n]{1,40}\]\(https?://t\.me/[^)\s]+\)"
TG_MARKDOWN_CHANNEL_RECOMMENDATION_TAIL_RE = re.compile(
    rf"(?:\s*(?:[|｜]\s*)?{TG_MARKDOWN_CHANNEL_LINK}){{2,}}\s*$",
    re.IGNORECASE,
)
TG_STANDALONE_SEPARATOR_RE = re.compile(r"^\s*[-—_]{2,}\s*$")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Diting AI/TG digest pages into dashboard JSON.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL.rstrip("/"), help="Published dt site base URL.")
    parser.add_argument("--source-dir", default="", help="Optional local dt checkout for tests/backfills.")
    parser.add_argument("--output-dir", default=str(ROOT / "public" / "dashboard-data"), help="Public dashboard data directory.")
    parser.add_argument("--detail-days", type=int, default=DEFAULT_DETAIL_DAYS, help="How many recent days per kind to parse into detail JSON.")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve() if args.source_dir else None
    base_url = args.base_url.rstrip("/")
    output_dir = Path(args.output_dir)
    target = output_dir / "dt-digests"
    target.mkdir(parents=True, exist_ok=True)

    search_index = load_search_index(base_url, source_dir)
    entries = digest_entries(search_index, base_url)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    detail_entries = details_to_sync(entries, args.detail_days)
    for entry in detail_entries:
        daily = build_daily_detail(entry, base_url, source_dir, generated_at)
        daily_path = target / "daily" / entry["kind"] / f"{entry['date']}.json"
        daily = preserve_existing_detail_if_unchanged(daily_path, daily)
        write_json(str(daily_path), daily)
        entry["item_count"] = daily["item_count"]
        if daily.get("filtered_count"):
            entry["original_item_count"] = daily["original_item_count"]
            entry["filtered_count"] = daily["filtered_count"]
            entry["filter_summary"] = daily["filter_summary"]
        entry["detail_path"] = f"dashboard-data/dt-digests/daily/{entry['kind']}/{entry['date']}.json"
        entry["detail_available"] = True

    existing_details = {
        path.relative_to(output_dir).as_posix()
        for path in (target / "daily").glob("*/*.json")
    }
    for entry in entries:
        detail_path = f"dt-digests/daily/{entry['kind']}/{entry['date']}.json"
        if "detail_path" not in entry and detail_path in existing_details:
            entry["detail_path"] = f"dashboard-data/{detail_path}"
            entry["detail_available"] = True
        entry.setdefault("detail_available", False)

    index = build_digest_index(entries, generated_at, base_url, args.detail_days)
    write_json(str(target / "index.json"), index)
    update_data_bundle(output_dir)
    refresh_index_asset_versions(output_dir.parent / "index.html", asset_cache_token(index["latest_date"] or "dt-digests", generated_at))

    print(
        "Synced Diting digests: "
        f"AI {index['counts']['ai']} / TG {index['counts']['tg']} "
        f"(details {len(detail_entries)}, latest {index['latest_date']})."
    )


def load_search_index(base_url: str, source_dir: Path | None) -> list[dict[str, Any]]:
    if source_dir:
        path = source_dir / "search-index.json"
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(fetch_text(f"{base_url}/search-index.json"))


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "BrandRadarDigestSync/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def read_page(filename: str, base_url: str, source_dir: Path | None) -> str:
    if source_dir:
        return (source_dir / safe_relative_path(filename)).read_text(encoding="utf-8")
    if re.match(r"^https?://", filename, flags=re.IGNORECASE):
        return fetch_text(filename)
    return fetch_text(f"{base_url}/{urllib.request.pathname2url(filename)}")


def read_optional_page(filename: str, base_url: str, source_dir: Path | None) -> str | None:
    try:
        return read_page(filename, base_url, source_dir)
    except (FileNotFoundError, OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError):
        return None


def digest_entries(search_index: list[dict[str, Any]], base_url: str) -> list[dict[str, Any]]:
    entries = []
    for item in search_index:
        filename = str(item.get("f") or "")
        kind, date = digest_kind_and_date(filename)
        if not kind or not date:
            continue
        body = str(item.get("b") or "")
        item_count, section_count = digest_counts_from_body(body, kind)
        entry = {
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "date": date,
            "file": filename,
            "title": KIND_LABELS[kind],
            "source_url": f"{base_url}/{urllib.request.pathname2url(filename)}",
            "search_text_hash": sha256_text(body),
            "body_preview": redact_sensitive_text(compact_text(body))[:240],
            "item_count": item_count,
            "section_count": section_count,
        }
        json_url = str(item.get("json_url") or "").strip()
        if kind == "tg" and (item.get("has_json") or json_url):
            entry["has_json"] = True
            entry["json_url"] = safe_relative_path(json_url or inferred_tg_json_filename(filename))
        entries.append(entry)
    entries.sort(key=lambda value: (value["date"], value["kind"]), reverse=True)
    return entries


def preserve_existing_detail_if_unchanged(path: Path, daily: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return daily
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return daily
    if detail_without_sync_time(previous) == detail_without_sync_time(daily):
        return previous
    return daily


def detail_without_sync_time(payload: Any) -> Any:
    if isinstance(payload, dict):
        return {
            key: detail_without_sync_time(value)
            for key, value in payload.items()
            if key != "synced_at"
        }
    if isinstance(payload, list):
        return [detail_without_sync_time(value) for value in payload]
    return payload


def digest_kind_and_date(filename: str) -> tuple[str, str] | tuple[None, None]:
    ai_match = re.fullmatch(r"(\d{8})-AI日报\.html", filename)
    if ai_match:
        raw = ai_match.group(1)
        return "ai", f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    tg_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2})-tg-digest\.html", filename)
    if tg_match:
        return "tg", tg_match.group(1)
    return None, None


def details_to_sync(entries: list[dict[str, Any]], detail_days: int) -> list[dict[str, Any]]:
    result = []
    for kind in KIND_LABELS:
        kind_entries = [entry for entry in entries if entry["kind"] == kind]
        result.extend(kind_entries[: max(1, detail_days)])
    return result


def digest_counts_from_body(body: str, kind: str) -> tuple[int, int]:
    compact = compact_text(body)
    item_match = re.search(r"(\d+)\s*条内容", compact)
    if kind == "ai":
        section_match = re.search(r"(\d+)\s*个板块", compact)
    else:
        section_match = re.search(r"(\d+)\s*个频道", compact)
    item_count = int(item_match.group(1)) if item_match else 0
    section_count = int(section_match.group(1)) if section_match else 0
    return item_count, section_count


def build_daily_detail(entry: dict[str, Any], base_url: str, source_dir: Path | None, generated_at: str) -> dict[str, Any]:
    html_text = read_page(entry["file"], base_url, source_dir)
    parser = DigestPageParser(entry["kind"])
    parser.feed(html_text)
    parser.finish_open_blocks()
    sections = parser.sections
    structured_payload = load_structured_tg_payload(entry, base_url, source_dir) if entry["kind"] == "tg" else None
    if structured_payload:
        sections = merge_structured_tg_media(sections, structured_payload, base_url)
        if not sections:
            sections = structured_tg_sections(structured_payload, base_url)
    original_item_count = sum(len(section.get("items") or []) for section in sections)
    sections, filter_summary = filter_digest_sections(entry["kind"], sections)
    item_count = sum(len(section.get("items") or []) for section in sections)
    section_count = len(sections)
    payload = {
        "kind": entry["kind"],
        "kind_label": KIND_LABELS[entry["kind"]],
        "date": entry["date"],
        "file": entry["file"],
        "title": parser.hero_title or KIND_LABELS[entry["kind"]],
        "hero_date": update_hero_item_count(parser.hero_date, item_count),
        "source_url": entry["source_url"],
        "synced_at": generated_at,
        "original_item_count": original_item_count,
        "filtered_count": max(0, original_item_count - item_count),
        "filter_summary": filter_summary,
        "item_count": item_count,
        "section_count": section_count,
        "sections": sections,
    }
    if structured_payload:
        payload["has_json"] = True
        payload["json_url"] = entry.get("json_url") or inferred_tg_json_filename(entry["file"])
        if structured_payload.get("media_summary"):
            payload["source_media_summary"] = structured_payload["media_summary"]
        payload["media_summary"] = digest_media_summary(sections)
    return sanitize_payload(payload)


def load_structured_tg_payload(entry: dict[str, Any], base_url: str, source_dir: Path | None) -> dict[str, Any] | None:
    json_filename = structured_tg_json_filename(entry)
    if not json_filename:
        return None
    text = read_optional_page(json_filename, base_url, source_dir)
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or payload.get("kind") != "tg":
        return None
    return payload


def structured_tg_json_filename(entry: dict[str, Any]) -> str:
    explicit = str(entry.get("json_url") or "").strip()
    if explicit:
        return safe_relative_path(explicit)
    if entry.get("kind") != "tg":
        return ""
    if entry.get("has_json") or str(entry.get("date") or "") >= STRUCTURED_TG_JSON_START_DATE:
        return inferred_tg_json_filename(str(entry.get("file") or ""))
    return ""


def inferred_tg_json_filename(filename: str) -> str:
    return re.sub(r"\.html$", ".json", filename or "")


def merge_structured_tg_media(
    sections: list[dict[str, Any]],
    structured_payload: dict[str, Any],
    base_url: str,
) -> list[dict[str, Any]]:
    media_lookup = structured_tg_media_lookup(structured_payload, base_url)
    if not media_lookup:
        return sections
    merged_sections: list[dict[str, Any]] = []
    for section in sections:
        merged_items = []
        for item in section.get("items") or []:
            match = first_structured_match(item, media_lookup)
            if match:
                media = match.get("media") or []
                if media:
                    item = {**item, "media": media}
                for key in ("id", "message_id"):
                    if match.get(key) and not item.get(key):
                        item[key] = match[key]
                for key in ("channel_name", "channel_url"):
                    if match.get(key):
                        item[key] = match[key]
                for key in ("reply_count", "replies_fetched", "replies_visible", "replies_filtered"):
                    if key in match:
                        item[key] = match[key]
                if "replies" in match:
                    item["replies"] = match.get("replies") or []
            merged_items.append(item)
        merged_sections.append({**section, "items": merged_items})
    return merged_sections


def structured_tg_media_lookup(structured_payload: dict[str, Any], base_url: str) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for section in structured_payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            normalized = structured_tg_item(item, base_url)
            for key in structured_tg_item_keys(normalized):
                lookup.setdefault(key, normalized)
    return lookup


def first_structured_match(item: dict[str, Any], lookup: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for key in structured_tg_item_keys(item):
        if key in lookup:
            return lookup[key]
    return None


def structured_tg_item_keys(item: dict[str, Any]) -> list[str]:
    keys = []
    item_id = compact_text(str(item.get("id") or ""))
    if item_id:
        keys.append(f"id:{item_id}")
    url = normalized_tg_url(str(item.get("url") or ""))
    if url:
        keys.append(f"url:{url}")
    message_id = compact_text(str(item.get("message_id") or ""))
    channel = compact_text(str(item.get("channel") or "")).lstrip("@")
    if channel and message_id:
        keys.append(f"id:{channel}-{message_id}")
    return keys


def normalized_tg_url(value: str) -> str:
    url = clean_url(value)
    if not url:
        return ""
    return url.rstrip("/")


def structured_tg_sections(structured_payload: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    sections = []
    for section in structured_payload.get("sections") or []:
        if not isinstance(section, dict):
            continue
        items = [
            structured_tg_item(item, base_url)
            for item in section.get("items") or []
            if isinstance(item, dict)
        ]
        items = [item for item in items if item.get("title") or item.get("summary")]
        if items:
            sections.append({
                "title": compact_text(str(section.get("title") or "TG 频道精选")),
                "count_label": compact_text(str(section.get("count_label") or f"{len(items)} 条")),
                "items": items,
            })
    return sections


def structured_tg_item(item: dict[str, Any], base_url: str) -> dict[str, Any]:
    url = clean_url(str(item.get("url") or ""))
    replies = normalize_tg_replies(item.get("replies") or [], base_url, url)
    visible_replies = filter_tg_replies(replies)
    result = {
        "id": compact_text(str(item.get("id") or "")),
        "title": compact_text(strip_tg_channel_recommendations(str(item.get("title") or ""))),
        "summary": compact_text(strip_tg_channel_recommendations(str(item.get("summary") or ""))),
        "channel": compact_text(str(item.get("channel") or "")),
        "channel_name": compact_text(str(item.get("channel_name") or "")),
        "channel_url": clean_url(str(item.get("channel_url") or "")),
        "time": compact_text(str(item.get("time") or "")),
        "url": url,
        "message_id": compact_text(str(item.get("message_id") or "")),
        "media": normalize_tg_media_items(item.get("media") or [], base_url, url),
        "links": [{"href": url, "label": "查看原文"}] if url else [],
    }
    if "reply_count" in item:
        result["reply_count"] = nonnegative_int(item.get("reply_count"))
    if "replies_fetched" in item:
        result["replies_fetched"] = nonnegative_int(item.get("replies_fetched"))
    if "replies" in item:
        result["replies"] = visible_replies
        result["replies_visible"] = len(visible_replies)
        result["replies_filtered"] = max(0, len(replies) - len(visible_replies))
    return {key: value for key, value in result.items() if value not in ("", [], None)}


def normalize_tg_replies(replies: Any, base_url: str, fallback_url: str) -> list[dict[str, Any]]:
    if not isinstance(replies, list):
        return []
    normalized: list[dict[str, Any]] = []
    for reply in replies:
        if not isinstance(reply, dict):
            continue
        media = normalize_tg_media_items(reply.get("media") or [], base_url, fallback_url)
        item: dict[str, Any] = {
            "id": compact_text(str(reply.get("id") or "")),
            "text": compact_text(strip_tg_channel_recommendations(str(reply.get("text") or ""))),
            "time": compact_text(str(reply.get("time") or "")),
            "sender_name": compact_text(str(reply.get("sender_name") or "")),
            "media": media,
        }
        sender_id = reply.get("sender_id")
        if isinstance(sender_id, (int, float)) or (isinstance(sender_id, str) and sender_id.strip()):
            item["sender_id"] = sender_id
        normalized.append({key: value for key, value in item.items() if value not in ("", [], None)})
    return normalized


def filter_tg_replies(replies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [reply for reply in replies if not tg_reply_filter_reason(reply)]


def tg_reply_filter_reason(reply: dict[str, Any]) -> str | None:
    text = compact_text(str(reply.get("text") or ""))
    sender = compact_text(str(reply.get("sender_name") or ""))
    media = reply.get("media") or []
    if not text and not media:
        return "empty"
    compact = re.sub(r"\s+", "", f"{sender} {text}")
    if any(pattern.search(compact) for pattern in TG_REPLY_BLOCK_PATTERNS):
        return "blocked"
    if not media:
        signal_len = signal_char_count(text)
        if signal_len <= 1:
            return "low_signal"
        if signal_len <= 8 and TG_REPLY_LOW_SIGNAL_RE.search(compact):
            return "low_signal"
    return None


def normalize_tg_media_items(media_items: Any, base_url: str, fallback_url: str) -> list[dict[str, Any]]:
    if not isinstance(media_items, list):
        return []
    normalized = []
    for media in media_items:
        if not isinstance(media, dict):
            continue
        media_type = compact_text(str(media.get("type") or "image")).lower()
        item: dict[str, Any] = {
            "type": "video" if media_type in {"video", "gif", "animation"} else "image",
            "publish_status": compact_text(str(media.get("publish_status") or "")),
        }
        for key in ("url", "thumb_url", "poster_url", "fallback_url"):
            value = compact_text(str(media.get(key) or ""))
            if value:
                item[key] = resolve_dt_asset_url(value, base_url)
        if item["type"] == "video" and not item.get("fallback_url") and fallback_url:
            item["fallback_url"] = fallback_url
        for key in ("width", "height", "duration", "size_bytes"):
            value = media.get(key)
            if isinstance(value, (int, float)) and value >= 0:
                item[key] = value
        if "has_audio" in media:
            item["has_audio"] = bool(media.get("has_audio"))
        error = compact_text(str(media.get("error") or ""))
        if error:
            item["error"] = error
        normalized.append(item)
    return normalized


def resolve_dt_asset_url(value: str, base_url: str) -> str:
    raw = compact_text(value)
    if not raw or raw.startswith("data:"):
        return ""
    if re.match(r"^https?://", raw, flags=re.IGNORECASE):
        return raw
    relative = safe_relative_path(raw)
    return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", relative)


def safe_relative_path(value: str) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", raw, flags=re.IGNORECASE):
        raise ValueError(f"Absolute URL is not a relative path: {raw}")
    parts = [part for part in raw.lstrip("/").split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise ValueError(f"Unsafe relative path: {raw}")
    return "/".join(parts)


def digest_media_summary(sections: list[dict[str, Any]]) -> dict[str, int]:
    summary = {
        "image_count": 0,
        "video_count": 0,
        "published_video_count": 0,
        "poster_only_video_count": 0,
        "failed_count": 0,
    }
    for section in sections:
        for item in section.get("items") or []:
            for media in item.get("media") or []:
                media_type = str(media.get("type") or "").lower()
                status = str(media.get("publish_status") or "").lower()
                if status == "failed":
                    summary["failed_count"] += 1
                if media_type == "video":
                    summary["video_count"] += 1
                    if status == "published":
                        summary["published_video_count"] += 1
                    elif status == "poster_only":
                        summary["poster_only_video_count"] += 1
                elif media_type == "image":
                    summary["image_count"] += 1
    return summary


def filter_digest_sections(kind: str, sections: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if kind != "tg":
        return sections, []

    reason_counts: dict[str, int] = {}
    filtered_sections: list[dict[str, Any]] = []
    for section in sections:
        kept_items = []
        for item in section.get("items") or []:
            reason = tg_item_filter_reason(item)
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
                continue
            kept_items.append(item)
        if kept_items:
            filtered_sections.append({
                **section,
                "count_label": f"{len(kept_items)} 条",
                "items": kept_items,
            })

    summary = [
        {
            "reason": reason,
            "label": TG_FILTER_REASON_LABELS[reason],
            "count": reason_counts[reason],
        }
        for reason in TG_FILTER_REASON_LABELS
        if reason_counts.get(reason)
    ]
    return filtered_sections, summary


def tg_item_filter_reason(item: dict[str, Any]) -> str | None:
    full_text = compact_text(" ".join(digest_item_text_parts(item)))
    compact_full_text = re.sub(r"\s+", "", full_text)
    if any(pattern.search(compact_full_text) for pattern in TG_LOW_VALUE_ADULT_PATTERNS):
        return "low_value_adult"

    title = compact_text(str(item.get("title") or ""))
    summary = compact_text(str(item.get("summary") or ""))
    title_signal_length = signal_char_count(title)
    if not summary and title_signal_length <= 18 and TG_SHORT_STATUS_CHATTER_RE.search(title):
        return "short_status_chatter"
    if not summary and title_signal_length <= 12 and (
        title.rstrip().endswith(("?", "？")) or TG_SHORT_CHATTER_RE.search(title)
    ):
        return "short_status_chatter"
    return None


def digest_item_text_parts(item: dict[str, Any]) -> list[str]:
    parts = [
        str(item.get("title") or ""),
        str(item.get("summary") or ""),
        str(item.get("source") or ""),
        str(item.get("channel") or ""),
    ]
    for link in item.get("links") or []:
        if isinstance(link, dict):
            parts.append(str(link.get("label") or ""))
    return parts


def signal_char_count(value: str) -> int:
    without_urls = re.sub(r"https?://\S+", "", value or "", flags=re.IGNORECASE)
    return len(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", without_urls))


def update_hero_item_count(hero_date: str, item_count: int) -> str:
    if not hero_date:
        return hero_date
    return re.sub(r"\d+\s*条内容", f"{item_count} 条内容", hero_date)


class DigestPageParser(HTMLParser):
    def __init__(self, kind: str) -> None:
        super().__init__(convert_charrefs=True)
        self.kind = kind
        self.stack: list[dict[str, Any]] = []
        self.hero_title = ""
        self.hero_date = ""
        self.sections: list[dict[str, Any]] = []
        self.current_section: dict[str, Any] | None = None
        self.current_card: dict[str, Any] | None = None
        self.card_links: list[dict[str, str]] = []
        self.current_link: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        frame = {"tag": tag, "classes": classes, "attrs": attrs_dict}
        self.stack.append(frame)

        if tag == "div" and "section" in classes:
            if self.current_card is not None and self.current_section is not None:
                self.finish_current_card()
            if self.current_section is not None:
                self.finish_current_section()
            self.current_section = {"title": "", "count_label": "", "items": []}
        elif tag == "div" and "card" in classes:
            if self.current_card is not None and self.current_section is not None:
                self.finish_current_card()
            self.current_card = {
                "title": "",
                "summary": "",
                "source": "",
                "channel": "",
                "time": "",
                "url": "",
                "links": [],
            }
            self.card_links = []
        elif tag == "a" and self.current_card is not None:
            href = attrs_dict.get("href", "").strip()
            if href:
                if self.has_class("card-title") and not self.current_card.get("url"):
                    self.current_card["url"] = clean_url(href)
                if self.kind == "tg" and self.has_class("channel-links"):
                    return
                self.current_link = {"href": clean_url(href), "label": ""}
                self.card_links.append(self.current_link)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack:
            return
        frame = None
        while self.stack:
            candidate = self.stack.pop()
            if candidate.get("tag") == tag:
                frame = candidate
                break
        if frame is None:
            return
        classes = frame.get("classes", set())
        if tag == "a" and self.current_link is not None:
            if not self.current_link.get("label") and self.current_link in self.card_links:
                self.card_links.remove(self.current_link)
            self.current_link = None
        elif tag == "div" and "card" in classes and self.current_card is not None and self.current_section is not None:
            self.finish_current_card()
        elif tag == "div" and "section" in classes and self.current_section is not None:
            self.finish_current_section()

    def handle_data(self, data: str) -> None:
        text = html.unescape(data or "")
        if not text.strip():
            return
        if self.current_link is not None:
            self.current_link["label"] = compact_text(f"{self.current_link.get('label', '')} {text}")
        if self.has_class("hero-title"):
            self.hero_title = compact_text(f"{self.hero_title} {text}")
        elif self.has_class("hero-date"):
            self.hero_date = compact_text(f"{self.hero_date} {text}")
        elif self.current_section is not None and self.has_class("section-title"):
            self.current_section["title"] = compact_text(f"{self.current_section.get('title', '')} {text}")
        elif self.current_section is not None and self.has_class("section-count"):
            self.current_section["count_label"] = compact_text(f"{self.current_section.get('count_label', '')} {text}")
        elif self.current_card is not None and self.has_class("card-title"):
            self.current_card["title"] = f"{self.current_card.get('title', '')} {text}"
        elif self.current_card is not None and self.has_class("card-summary"):
            self.current_card["summary"] = f"{self.current_card.get('summary', '')} {text}"
        elif self.current_card is not None and self.has_class("source-tag"):
            self.current_card["source"] = f"{self.current_card.get('source', '')} {text}"
        elif self.current_card is not None and self.has_class("source-text"):
            self.current_card["source"] = f"{self.current_card.get('source', '')} {text}"
        elif self.current_card is not None and self.has_class("channel-tag"):
            self.current_card["channel"] = compact_text(f"{self.current_card.get('channel', '')} {text}")
        elif self.current_card is not None and self.has_class("time-tag"):
            self.current_card["time"] = compact_text(f"{self.current_card.get('time', '')} {text}")

    def has_class(self, class_name: str) -> bool:
        return any(class_name in frame.get("classes", set()) for frame in self.stack)

    def finish_open_blocks(self) -> None:
        if self.current_card is not None and self.current_section is not None:
            self.finish_current_card()
        if self.current_section is not None:
            self.finish_current_section()

    def finish_current_card(self) -> None:
        if self.current_card is None or self.current_section is None:
            return
        self.current_card["summary"] = compact_text(self.current_card.get("summary", ""))
        self.current_card["title"] = compact_text(self.current_card.get("title", ""))
        self.current_card["source"] = compact_text(self.current_card.get("source", ""))
        if self.card_links:
            self.current_card["links"] = [
                link for link in dedupe_links(self.card_links)
                if link.get("href") and link.get("label")
            ][:8]
        if not self.current_card.get("url") and self.current_card.get("links"):
            self.current_card["url"] = self.current_card["links"][0]["href"]
        self.current_card = {key: value for key, value in self.current_card.items() if value}
        if self.current_card.get("title") or self.current_card.get("summary"):
            self.current_section["items"].append(self.current_card)
        self.current_card = None
        self.card_links = []
        self.current_link = None

    def finish_current_section(self) -> None:
        if self.current_section is None:
            return
        self.current_section["title"] = compact_text(self.current_section.get("title", "")) or "日报内容"
        if self.current_section["items"]:
            self.sections.append(self.current_section)
        self.current_section = None


def clean_url(url: str) -> str:
    return url.strip().rstrip(")")


def dedupe_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    seen = set()
    result = []
    for link in links:
        href = link.get("href", "")
        label = compact_text(link.get("label", ""))
        key = (href, label)
        if not href or key in seen:
            continue
        seen.add(key)
        result.append({"href": href, "label": label or href})
    return result


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def strip_tg_channel_recommendations(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = TG_MARKDOWN_CHANNEL_RECOMMENDATION_TAIL_RE.sub("", text).rstrip()
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and TG_STANDALONE_SEPARATOR_RE.fullmatch(lines[-1]):
        lines.pop()
    return "\n".join(lines).strip()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def redact_sensitive_text(value: str) -> str:
    result = value
    for pattern in SENSITIVE_TEXT_PATTERNS:
        result = pattern.sub("[redacted]", result)
    return result


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_payload(child) for key, child in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(child) for child in value]
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def build_digest_index(entries: list[dict[str, Any]], generated_at: str, base_url: str, detail_days: int) -> dict[str, Any]:
    counts = {kind: sum(1 for entry in entries if entry["kind"] == kind) for kind in KIND_LABELS}
    latest = {
        kind: next((entry["date"] for entry in entries if entry["kind"] == kind), "")
        for kind in KIND_LABELS
    }
    latest_date = max([date for date in latest.values() if date] or [""])
    return {
        "generated_at": generated_at,
        "generated_at_label": beijing_label_from_iso(generated_at),
        "source": "codew1028/dt",
        "source_base_url": base_url,
        "detail_days": detail_days,
        "latest": latest,
        "latest_date": latest_date,
        "counts": counts,
        "items": entries,
    }


def beijing_label_from_iso(value: str) -> str:
    raw = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw).astimezone(ZoneInfo("Asia/Shanghai"))
    return dt.strftime("%Y-%m-%d %H:%M BJT")


def update_data_bundle(output_dir: Path) -> None:
    bundle_path = output_dir.parent / "dashboard-data-bundle.js"
    bundle = load_bundle(bundle_path)
    for key in list(bundle):
        if key.startswith("dashboard-data/dt-digests/"):
            del bundle[key]
    dt_dir = output_dir / "dt-digests"
    bundled_detail_paths = bundled_diting_detail_paths(dt_dir / "index.json")
    candidate_paths = [dt_dir / "index.json", *sorted((dt_dir / "daily").glob("*/*.json"))]
    for path in candidate_paths:
        if path.exists():
            key = f"dashboard-data/{path.relative_to(output_dir).as_posix()}"
            if path.name != "index.json" and key not in bundled_detail_paths:
                continue
            bundle[key] = json.loads(path.read_text(encoding="utf-8"))
    write_data_bundle(bundle_path, bundle)


def bundled_diting_detail_paths(index_path: Path) -> set[str]:
    if not index_path.exists():
        return set()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    allowed: set[str] = set()
    for kind in KIND_LABELS:
        kind_items = [
            item for item in index.get("items", [])
            if item.get("kind") == kind and item.get("detail_available") and item.get("detail_path")
        ]
        kind_items.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
        for item in kind_items[:DEFAULT_BUNDLE_DETAIL_DAYS]:
            allowed.add(str(item["detail_path"]))
    return allowed


def load_bundle(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.__DASHBOARD_DATA__ = "
    if not text.startswith(prefix):
        return {}
    payload = text[len(prefix):]
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


if __name__ == "__main__":
    main()
