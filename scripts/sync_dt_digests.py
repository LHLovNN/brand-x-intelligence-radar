#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
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
        return (source_dir / filename).read_text(encoding="utf-8")
    return fetch_text(f"{base_url}/{urllib.request.pathname2url(filename)}")


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
        entries.append(entry)
    entries.sort(key=lambda value: (value["date"], value["kind"]), reverse=True)
    return entries


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
    original_item_count = sum(len(section.get("items") or []) for section in parser.sections)
    sections, filter_summary = filter_digest_sections(entry["kind"], parser.sections)
    item_count = sum(len(section.get("items") or []) for section in sections)
    section_count = len(sections)
    return sanitize_payload({
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
    })


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
                self.card_links.append({"href": clean_url(href), "label": ""})

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
        if tag == "a" and self.card_links and not self.card_links[-1]["label"]:
            self.card_links.pop()
        elif tag == "div" and "card" in classes and self.current_card is not None and self.current_section is not None:
            self.finish_current_card()
        elif tag == "div" and "section" in classes and self.current_section is not None:
            self.finish_current_section()

    def handle_data(self, data: str) -> None:
        text = html.unescape(data or "")
        if not text.strip():
            return
        if self.card_links:
            self.card_links[-1]["label"] = compact_text(f"{self.card_links[-1].get('label', '')} {text}")
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
