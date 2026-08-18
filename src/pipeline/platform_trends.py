from __future__ import annotations

import html
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from src.adapters.x_source_base import ProviderBudgetExceeded
from src.pipeline.conversation_context import (
    attach_conversation_contexts,
    dedupe_contextual_items_keep_earliest,
    dedupe_conversation_items_keep_earliest,
)
from src.pipeline.dashboard_builder import write_data_bundle
from src.pipeline.translation import apply_translations, translation_report
from src.utils.config import load_project_json
from src.utils.io import read_json, write_json
from src.utils.time import beijing_label, now_utc, to_iso


PLATFORM_KEY = "xiaohongshu"
DEFAULT_MAX_ITEMS = 20
DEFAULT_MAX_CANDIDATES = 200
DEFAULT_MAX_REQUESTS = 8
DEFAULT_MIN_VIEWS = 500
DEFAULT_MIN_LIKES = 10
PLATFORM_DATA_ROOT = Path("platform-trends")


TOPIC_TERMS = {
    "账号冷启动": [
        "养号",
        "起号",
        "冷启动",
        "涨粉",
        "account growth",
        "grow account",
        "cold start",
        "followers",
    ],
    "爆文与内容结构": [
        "爆文",
        "笔记",
        "选题",
        "标题",
        "封面",
        "内容定位",
        "viral",
        "content",
        "post structure",
        "hook",
    ],
    "流量机制": [
        "流量",
        "算法",
        "推荐",
        "曝光",
        "traffic",
        "algorithm",
        "distribution",
        "reach",
    ],
    "变现": [
        "变现",
        "变现路径",
        "商单",
        "带货",
        "店铺",
        "电商",
        "monetization",
        "make money",
        "affiliate",
        "commerce",
    ],
    "私域引流": [
        "引流",
        "私域",
        "社群",
        "微信",
        "leads",
        "funnel",
        "community",
        "private domain",
    ],
    "案例复盘": [
        "案例",
        "复盘",
        "拆解",
        "实操",
        "case study",
        "playbook",
        "breakdown",
        "experiment",
        "results",
    ],
}

PLATFORM_TAG_ALIASES = {
    "养号": "账号冷启动",
    "起号": "账号冷启动",
    "冷启动": "账号冷启动",
    "涨粉": "账号冷启动",
    "爆文": "爆文与内容结构",
    "笔记": "爆文与内容结构",
    "选题": "爆文与内容结构",
    "标题": "爆文与内容结构",
    "封面": "爆文与内容结构",
    "内容定位": "爆文与内容结构",
    "流量": "流量机制",
    "算法": "流量机制",
    "推荐": "流量机制",
    "曝光": "流量机制",
    "变现路径": "变现",
    "商单": "变现",
    "带货": "变现",
    "店铺": "变现",
    "电商": "变现",
    "引流": "私域引流",
    "私域": "私域引流",
    "社群": "私域引流",
    "微信": "私域引流",
    "案例": "案例复盘",
    "复盘": "案例复盘",
    "拆解": "案例复盘",
    "实操": "案例复盘",
}

NOISE_TERMS = [
    "tiktok refugee",
    "refugees",
    "spy app",
    "privacy",
    "ccp",
    "ban",
    "download rednote",
    "coupon code",
    "promo code",
]

HARD_NOISE_TERMS = [
    "@abuincrease",
    "@pichai666",
    "51平台",
    "删帖",
    "删除微信公众号文章",
    "删除微博",
    "删除推特",
    "负面信息",
    "负面内容",
    "清除负面",
    "消除差评",
    "差评处理",
    "账号解封",
    "微信解封",
    "电报号解封",
    "封号处理",
    "封禁解除",
    "店铺封禁",
    "视频下架",
    "笔记下架",
    "商品屏蔽",
    "代举报",
    "投诉链接",
    "聊天记录查询",
    "酒店入住记录",
    "手机定位",
    "定位追踪",
    "老牌服务商",
    "老字号服务",
    "专业品牌客服",
]

STRUCTURE_SIGNALS = [
    "how to",
    "step",
    "steps",
    "thread",
    "guide",
    "playbook",
    "framework",
    "checklist",
    "经验",
    "方法",
    "步骤",
    "复盘",
    "拆解",
    "总结",
    "实操",
]


def platform_trends_enabled() -> bool:
    raw = str(os.getenv("BRAND_RADAR_PLATFORM_TRENDS") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def load_platform_config() -> dict[str, Any]:
    return load_project_json("platform_trends.local.json")


def apply_platform_runtime_limits(x_source: Any, config: dict[str, Any]) -> dict[str, Any]:
    platform = platform_config(config)
    configured = int(platform.get("max_source_requests_per_run") or DEFAULT_MAX_REQUESTS)
    max_requests = optional_int_env("BRAND_RADAR_PLATFORM_MAX_SOURCE_REQUESTS", configured)
    max_context_requests = optional_int_env("BRAND_RADAR_PLATFORM_MAX_CONTEXT_REQUESTS", None)
    if hasattr(x_source, "max_requests_per_run"):
        x_source.max_requests_per_run = max_requests
    if hasattr(x_source, "max_context_requests_per_run"):
        x_source.max_context_requests_per_run = max_context_requests
    return {
        "max_source_requests": max_requests,
        "max_context_requests": max_context_requests,
    }


def collect_platform_trends(
    x_source: Any,
    translation_service: Any,
    provider: str,
    start: Any,
    end: Any,
    report_date: str,
    window_label: str,
    output_dir: str,
) -> dict[str, Any]:
    config = load_platform_config()
    platform = platform_config(config)
    runtime_limits = apply_platform_runtime_limits(x_source, config)
    max_items = optional_int_env("BRAND_RADAR_PLATFORM_MAX_ITEMS", int(platform.get("max_items_per_day") or DEFAULT_MAX_ITEMS))
    max_candidates = optional_int_env(
        "BRAND_RADAR_PLATFORM_MAX_CANDIDATES",
        int(platform.get("max_candidates_per_day") or DEFAULT_MAX_CANDIDATES),
    )
    min_views = optional_int_env("BRAND_RADAR_PLATFORM_MIN_VIEWS", int(platform.get("min_views_per_item") or DEFAULT_MIN_VIEWS))
    min_likes = optional_int_env("BRAND_RADAR_PLATFORM_MIN_LIKES", int(platform.get("min_likes_per_item") or DEFAULT_MIN_LIKES))
    max_items = max(1, max_items or DEFAULT_MAX_ITEMS)
    max_candidates = max(max_items, max_candidates or DEFAULT_MAX_CANDIDATES)
    min_views = max(0, min_views or 0)
    min_likes = max(0, min_likes or 0)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    candidates_seen = 0
    metric_filtered = 0
    conversation_deduped = 0
    warnings: list[str] = []
    query_stats: list[dict[str, Any]] = []

    for query in build_platform_queries(platform):
        if len(selected) >= max_items or candidates_seen >= max_candidates:
            break
        limit = max_candidates - candidates_seen
        try:
            rows = x_source.search_posts(query, to_iso(start), to_iso(end), limit, query_type="Top")
        except ProviderBudgetExceeded as error:
            warnings.append(str(error))
            break
        except RuntimeError as error:
            warnings.append(f"Platform trend collection stopped after error: {str(error)[:180]}")
            break

        accepted_for_query = 0
        inspected_for_query = 0
        metric_filtered_for_query = 0
        for row in rows:
            post_id = str(row.get("post_id") or row.get("url") or "")
            if not post_id or post_id in seen:
                continue
            seen.add(post_id)
            candidates_seen += 1
            inspected_for_query += 1
            if not passes_platform_metric_gate(row, min_views, min_likes):
                metric_filtered += 1
                metric_filtered_for_query += 1
                if candidates_seen >= max_candidates:
                    break
                continue
            item = normalize_platform_post(row, platform)
            decision = score_platform_post(item, platform)
            if decision["accepted"]:
                item.update(decision["item"])
                selected.append(item)
                selected, removed_duplicates = dedupe_conversation_items_keep_earliest(selected)
                conversation_deduped += removed_duplicates
                accepted_for_query += 1
            if len(selected) >= max_items or candidates_seen >= max_candidates:
                break
        query_stats.append(
            {
                "query_label": query_label(query),
                "fetched": len(rows),
                "inspected": inspected_for_query,
                "metric_filtered": metric_filtered_for_query,
                "metric_eligible": inspected_for_query - metric_filtered_for_query,
                "accepted": accepted_for_query,
            }
        )

    selected.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    translation_status = apply_translations(selected, translation_service)
    context_status = attach_platform_context(selected, x_source, translation_service, start, end)
    selected, context_deduped = dedupe_contextual_items_keep_earliest(selected)
    if context_deduped:
        conversation_deduped += context_deduped
        context_status["deduped_after_context"] = context_deduped
        refresh_context_status_for_items(context_status, selected)
        selected.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        translation_status = translation_report(selected, getattr(translation_service, "provider_name", "none"))
    status = collection_status(
        selected,
        candidates_seen,
        max_items,
        max_candidates,
        warnings,
        min_views=min_views,
        min_likes=min_likes,
        metric_filtered=metric_filtered,
        conversation_deduped=conversation_deduped,
    )

    payload = {
        "platform": PLATFORM_KEY,
        "display_name": platform.get("display_name", "小红书"),
        "topic_label": platform.get("topic_label", "小红书增长方法"),
        "date": report_date,
        "generated_at": to_iso(now_utc()),
        "generated_at_label": beijing_label(now_utc()),
        "window_label": window_label,
        "items": public_platform_items(selected),
        "collection_status": {
            **status,
            "translation": public_translation_status(translation_status),
            "conversation_context": context_status,
        },
        "summary": {
            "accepted": len(selected),
            "candidates_inspected": candidates_seen,
            "metric_filtered": metric_filtered,
            "conversation_deduped": conversation_deduped,
            "max_items": max_items,
            "max_candidates": max_candidates,
            "min_views": min_views,
            "min_likes": min_likes,
        },
    }
    write_platform_payload(Path(output_dir), payload)
    return {
        "status": status["status"],
        "accepted": len(selected),
        "candidates_inspected": candidates_seen,
        "metric_filtered": metric_filtered,
        "conversation_deduped": conversation_deduped,
        "warnings": warnings[:5],
        "provider": provider,
        "request_stats": platform_request_stats(x_source),
        "runtime_limits": runtime_limits,
        "query_stats": query_stats,
        "translation": translation_status,
        "conversation_context": context_status,
    }


def platform_config(config: dict[str, Any]) -> dict[str, Any]:
    platforms = config.get("platforms") or {}
    platform = platforms.get(PLATFORM_KEY) or {}
    if not platform:
        raise RuntimeError(f"Missing platform trend config for {PLATFORM_KEY}")
    return platform


def build_platform_queries(platform: dict[str, Any]) -> list[str]:
    if platform.get("query_groups"):
        queries = []
        for group in platform["query_groups"]:
            aliases = group.get("aliases") or platform.get("aliases") or []
            intents = group.get("intent_terms") or platform.get("intent_terms") or []
            excludes = group.get("exclude_terms") or platform.get("exclude_terms") or []
            queries.append(f"({_or_clause(aliases)}) ({_or_clause(intents)}) -filter:retweets {_negative_clause(excludes)}".strip())
        return [query for query in queries if query]
    aliases = platform.get("aliases") or []
    intents = platform.get("intent_terms") or []
    excludes = platform.get("exclude_terms") or []
    return [f"({_or_clause(aliases)}) ({_or_clause(intents)}) -filter:retweets {_negative_clause(excludes)}".strip()]


def normalize_platform_post(post: dict[str, Any], platform: dict[str, Any]) -> dict[str, Any]:
    clean_text = clean_post_text(post)
    metrics = {
        "likes": int(post.get("like_count") or 0),
        "reposts": int(post.get("repost_count") or 0),
        "replies": int(post.get("reply_count") or 0),
        "quotes": int(post.get("quote_count") or 0),
        "bookmarks": post.get("bookmark_count"),
        "views": post.get("view_count"),
    }
    return {
        "post_id": post.get("post_id"),
        "created_at": post.get("created_at"),
        "time": post.get("created_at"),
        "url": post.get("url"),
        "external_href": post.get("url"),
        "language": post.get("language") or "und",
        "text": post.get("text") or "",
        "clean_text": clean_text,
        "original_text": clean_text,
        "translation_zh": "",
        "translation_status": "pending",
        "summary_zh": "X 上关于小红书增长、运营或变现的方法论分享。",
        "platform": PLATFORM_KEY,
        "brand": "platform_xiaohongshu",
        "source_type": platform.get("topic_label", "平台流变"),
        "badge": "小红书",
        "author_id": post.get("author_id"),
        "author_name": post.get("author_name"),
        "author_handle": post.get("author_handle"),
        "author_avatar_url": post.get("author_avatar_url"),
        "author_followers": post.get("author_followers") or 0,
        "author_following": post.get("author_following") or 0,
        "author_bio": post.get("author_bio") or "",
        "author_location": post.get("author_location") or "",
        "author_joined_at": post.get("author_joined_at") or "",
        "author_verified": bool(post.get("author_verified")),
        "reply_to_post_id": post.get("reply_to_post_id"),
        "reply_to_handle": post.get("reply_to_handle"),
        "quoted_post_id": post.get("quoted_post_id"),
        "conversation_id": post.get("conversation_id"),
        "media": post.get("media") or [],
        "links": post.get("links") or [],
        "metrics": metrics,
        "post_metrics": metrics,
        "is_relevant": True,
    }


def passes_platform_metric_gate(post: dict[str, Any], min_views: int, min_likes: int) -> bool:
    views = raw_metric(post, "views", "view_count", "total_views")
    likes = raw_metric(post, "likes", "like_count")
    return views >= min_views and likes >= min_likes


def raw_metric(post: dict[str, Any], *keys: str) -> int:
    metrics = post.get("metrics") or post.get("post_metrics") or {}
    for key in keys:
        value = post.get(key)
        if value is None:
            value = metrics.get(key)
        if value is None:
            continue
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            continue
    return 0


def score_platform_post(item: dict[str, Any], platform: dict[str, Any]) -> dict[str, Any]:
    text = combined_text(item)
    lower = text.lower()
    aliases = [str(term).lower() for term in platform.get("aliases") or []]
    intent_terms = [str(term).lower() for term in platform.get("intent_terms") or []]
    exclude_terms = [str(term).lower() for term in [*NOISE_TERMS, *(platform.get("exclude_terms") or [])]]
    alias_hits = matched_terms(lower, aliases)
    intent_hits = matched_terms(lower, intent_terms)
    if not alias_hits or not intent_hits:
        return {"accepted": False, "item": {}}
    if matched_terms(lower, HARD_NOISE_TERMS):
        return {"accepted": False, "item": {}}
    if matched_terms(lower, exclude_terms) and not strong_method_signal(lower):
        return {"accepted": False, "item": {}}

    topics = matched_topics(lower)
    structure_score = method_structure_score(lower)
    metric_score = propagation_score(item)
    topic_score = min(30, len(intent_hits) * 6 + len(topics) * 4)
    score = min(100, 35 + topic_score + structure_score + metric_score)
    if score < 62:
        return {"accepted": False, "item": {}}

    topic = topics[0] if topics else "小红书方法论"
    return {
        "accepted": True,
        "item": {
            "topic": topic,
            "quality_score": score,
            "score_value": score,
            "score_label": "GQS",
            "quality_label": "黄金内容",
            "selected_reason": selection_reason(topic, structure_score, metric_score),
            "reusable_takeaway": reusable_takeaway(topic),
            "tags": platform_item_tags(topic, topics),
        },
    }


def attach_platform_context(items: list[dict[str, Any]], x_source: Any, translation_service: Any, start: Any, end: Any) -> dict[str, Any]:
    clusters = [
        {
            "post_ids": [item.get("post_id")],
            "score": {"ips": item.get("quality_score", 0)},
        }
        for item in items
    ]
    return attach_conversation_contexts(
        items,
        clusters,
        x_source,
        translation_service,
        to_iso(start),
        to_iso(end),
        allow_anchor_threads=True,
    )


def refresh_context_status_for_items(context_status: dict[str, Any], items: list[dict[str, Any]]) -> None:
    attached = sum(1 for item in items if isinstance(item.get("conversation_context"), dict) and item["conversation_context"].get("posts"))
    attempted = int(context_status.get("attempted") or len(items))
    deduped = int(context_status.get("deduped_after_context") or 0)
    context_status["attached"] = attached
    context_status["unresolved"] = max(0, attempted - deduped - attached)


def collection_status(
    items: list[dict[str, Any]],
    candidates_seen: int,
    max_items: int,
    max_candidates: int,
    warnings: list[str],
    min_views: int = DEFAULT_MIN_VIEWS,
    min_likes: int = DEFAULT_MIN_LIKES,
    metric_filtered: int = 0,
    conversation_deduped: int = 0,
) -> dict[str, Any]:
    status = "complete"
    if len(items) >= max_items:
        reason = "daily_item_target_reached"
    elif candidates_seen >= max_candidates:
        reason = "candidate_cap_reached"
    else:
        reason = "candidate_source_exhausted"
    if warnings:
        status = "partial"
    return {
        "status": status,
        "completion_reason": reason,
        "warnings": warnings[:5],
        "accepted_count": len(items),
        "candidates_inspected": candidates_seen,
        "metric_filtered": metric_filtered,
        "conversation_deduped": conversation_deduped,
        "max_items": max_items,
        "max_candidates": max_candidates,
        "min_views": min_views,
        "min_likes": min_likes,
    }


def write_platform_payload(target: Path, payload: dict[str, Any]) -> None:
    platform_dir = target / PLATFORM_DATA_ROOT / PLATFORM_KEY
    platform_dir.mkdir(parents=True, exist_ok=True)
    write_json(str(platform_dir / "latest.json"), payload)
    write_json(str(platform_dir / "index.json"), platform_index(platform_dir, payload))
    write_json(str(platform_dir / "daily" / f"{payload['date']}.json"), payload)
    update_bundle(target.parent / "dashboard-data-bundle.js", target)


def platform_index(platform_dir: Path, current: dict[str, Any]) -> dict[str, Any]:
    daily_dir = platform_dir / "daily"
    records: dict[str, dict[str, Any]] = {}
    if daily_dir.exists():
        for path in daily_dir.glob("*.json"):
            try:
                record = read_json(str(path))
            except Exception:
                continue
            if record.get("date"):
                records[record["date"]] = record
    records[current["date"]] = current
    return {
        "latest_date": current["date"],
        "generated_at": current["generated_at"],
        "items": [
            {
                "date": record.get("date"),
                "generated_at_label": record.get("generated_at_label"),
                "window_label": record.get("window_label"),
                "accepted": len(record.get("items") or []),
                "candidates_inspected": record.get("summary", {}).get("candidates_inspected", 0),
                "collection_status": record.get("collection_status", {}).get("status", "unknown"),
            }
            for record in sorted(records.values(), key=lambda item: item.get("date", ""), reverse=True)
        ],
    }


def update_bundle(bundle_path: Path, data_dir: Path) -> None:
    bundle = load_bundle(bundle_path)
    platform_dir = data_dir / PLATFORM_DATA_ROOT / PLATFORM_KEY
    for path in [platform_dir / "latest.json", platform_dir / "index.json", *sorted((platform_dir / "daily").glob("*.json"))]:
        if not path.exists():
            continue
        key = f"dashboard-data/{path.relative_to(data_dir).as_posix()}"
        bundle[key] = read_json(str(path))
    write_data_bundle(bundle_path, bundle)


def load_bundle(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.__DASHBOARD_DATA__ = "
    if text.startswith(prefix):
        text = text[len(prefix) :]
    if text.endswith(";"):
        text = text[:-1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def public_platform_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {
        "post_id",
        "created_at",
        "time",
        "url",
        "external_href",
        "language",
        "text",
        "clean_text",
        "original_text",
        "translation_zh",
        "translation_status",
        "summary_zh",
        "platform",
        "brand",
        "source_type",
        "badge",
        "topic",
        "quality_score",
        "quality_label",
        "score_value",
        "score_label",
        "selected_reason",
        "reusable_takeaway",
        "tags",
        "author_id",
        "author_name",
        "author_handle",
        "author_avatar_url",
        "author_followers",
        "author_following",
        "author_bio",
        "author_location",
        "author_joined_at",
        "author_verified",
        "reply_to_post_id",
        "reply_to_handle",
        "quoted_post_id",
        "conversation_id",
        "conversation_context",
        "media",
        "links",
        "metrics",
        "post_metrics",
    }
    return [{key: value for key, value in item.items() if key in allowed} for item in items]


def public_translation_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(status.get("configured", True)),
        "counts": status.get("counts", {}),
        "missing_count": status.get("missing_count", 0),
        "fallback_original_count": status.get("fallback_original_count", 0),
    }


def platform_request_stats(x_source: Any) -> dict[str, Any]:
    return {
        "api_requests_used": getattr(x_source, "requests_used", None),
        "max_api_requests": getattr(x_source, "max_requests_per_run", None),
        "request_budget_exhausted": bool(getattr(x_source, "request_budget_exhausted", False)),
        "context_requests_used": getattr(x_source, "context_requests_used", None),
        "max_context_requests": getattr(x_source, "max_context_requests_per_run", None),
        "context_request_budget_exhausted": bool(getattr(x_source, "context_request_budget_exhausted", False)),
    }


def clean_post_text(post: dict[str, Any]) -> str:
    text = html.unescape(str(post.get("text") or ""))
    return re.sub(r"[ \t]+", " ", text).strip()


def combined_text(item: dict[str, Any]) -> str:
    links = " ".join(str(link) for link in item.get("links") or [])
    return f"{item.get('clean_text') or item.get('text') or ''} {links}".strip()


def matched_terms(lower: str, terms: list[str]) -> list[str]:
    matches = []
    padded = f" {lower} "
    for term in terms:
        value = term.strip().lower()
        if not value:
            continue
        if len(value) <= 3 and value.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", padded):
                matches.append(term)
        elif value in lower:
            matches.append(term)
    return matches


def matched_topics(lower: str) -> list[str]:
    topics = []
    for topic, terms in TOPIC_TERMS.items():
        if matched_terms(lower, [term.lower() for term in terms]):
            topics.append(topic)
    return topics


def method_structure_score(lower: str) -> int:
    score = 0
    if matched_terms(lower, STRUCTURE_SIGNALS):
        score += 12
    if re.search(r"(^|\n|\s)(\d+[\.、)]|[一二三四五六七八九十]+[、.])", lower):
        score += 10
    if len(lower) >= 260:
        score += 8
    if len(lower) >= 600:
        score += 6
    return min(28, score)


def strong_method_signal(lower: str) -> bool:
    return method_structure_score(lower) >= 12 or bool(matched_topics(lower))


def propagation_score(item: dict[str, Any]) -> int:
    metrics = item.get("metrics") or {}
    interactions = sum(int(metrics.get(key) or 0) for key in ("likes", "reposts", "replies", "quotes"))
    views = int(metrics.get("views") or 0)
    followers = int(item.get("author_followers") or 0)
    score = 0
    if interactions:
        score += min(14, round(math.log10(interactions + 1) * 7))
    if views:
        score += min(8, round(math.log10(views + 1) * 2))
    if followers >= 1000:
        score += 4
    if followers >= 10000:
        score += 4
    return min(22, score)


def selection_reason(topic: str, structure_score: int, metric_score: int) -> str:
    method = "内容包含可复用的方法、步骤或复盘结构" if structure_score >= 12 else "内容命中明确的小红书运营/增长意图"
    spread = "且已有一定传播反馈" if metric_score >= 8 else "，适合进入当日方法论样本池"
    return f"{method}，主题归为「{topic}」{spread}。"


def reusable_takeaway(topic: str) -> str:
    mapping = {
        "账号冷启动": "关注账号启动阶段的定位、互动和初始内容节奏。",
        "爆文与内容结构": "提炼选题、标题、封面、正文结构中的可复用写法。",
        "流量机制": "观察作者对推荐、曝光和互动反馈机制的判断。",
        "变现": "记录从内容到商单、带货、店铺或服务成交的闭环。",
        "私域引流": "关注从小红书内容到社群、私域或线索承接的路径。",
        "案例复盘": "优先提取案例前提、动作、结果和可迁移限制。",
    }
    return mapping.get(topic, "提炼可迁移的小红书运营动作。")


def platform_item_tags(topic: str, topics: list[str]) -> list[str]:
    tags = unique_tags([canonical_platform_tag(value) for value in [topic, *topics]])
    return tags or ["小红书方法论"]


def canonical_platform_tag(value: str) -> str:
    tag = re.sub(r"\s+", "_", str(value or "").strip())
    if not tag:
        return ""
    if tag in TOPIC_TERMS:
        return tag
    return PLATFORM_TAG_ALIASES.get(tag, "")


def unique_tags(values: list[str]) -> list[str]:
    tags = []
    for value in values:
        tag = re.sub(r"\s+", "_", str(value).strip())
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def query_label(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()[:120]


def optional_int_env(name: str, fallback: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    if value < 0:
        return fallback
    return value


def _or_clause(terms: list[str]) -> str:
    return " OR ".join(_format_term(term) for term in terms if str(term).strip())


def _format_term(term: str) -> str:
    value = str(term).strip()
    if " " in value or "." in value:
        return f'"{value}"'
    return value


def _negative_clause(terms: list[str]) -> str:
    return " ".join(f"-{_format_term(term)}" for term in terms if str(term).strip())
