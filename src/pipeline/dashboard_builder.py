from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.pipeline.competitor_radar import build_competitor_radar
from src.utils.io import write_json
from src.utils.time import BEIJING, beijing_label, now_utc, to_iso


FEATURED_IPS_THRESHOLD = 55

PUBLIC_KEY_REPLACEMENTS = {
    "joybuy_volume": "primary_volume",
    "joybuy_candidate_volume": "primary_candidate_volume",
    "temu_volume": "competitor_volume",
    "joybuy_candidates": "primary_candidates",
    "joybuy_effective": "primary_effective",
    "temu_candidates": "competitor_candidates",
    "temu_effective": "competitor_effective",
    "joybuy_clusters": "primary_signals",
}

PUBLIC_DROP_KEYS = {
    "provider",
    "providers",
    "source_provider",
    "translation_provider",
    "query",
    "api_requests_used",
    "max_api_requests",
    "estimated_cost_usd",
    "limits",
    "search_modes",
    "request_budget_exhausted",
    "missing_examples",
    "error",
    "fermenting",
    "fermentation",
    "fermentation_snapshot",
    "tracking_eligible",
    "tracking_reason",
    "archive_note",
}

SOURCE_TEXT_KEYS = {
    "text",
    "clean_text",
    "original_text",
    "translation_zh",
    "links",
    "url",
    "post_url",
    "external_href",
    "expanded_url",
    "media_url",
    "media_url_https",
    "preview_image_url",
    "author_name",
    "author_handle",
    "author_bio",
    "author_location",
    "author_avatar_url",
    "avatar_url",
}


def build_dashboard_data(
    joybuy_clusters: list[dict[str, Any]],
    normalized_posts: list[dict[str, Any]],
    output_dir: str,
    provider_hint: str | None = None,
    report_date: str | None = None,
    window_label: str | None = None,
    collection_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    current = now_utc()
    report_date = report_date or current.astimezone(BEIJING).strftime("%Y-%m-%d")
    competitor = build_competitor_radar(normalized_posts)
    fermentation_items = [cluster for cluster in joybuy_clusters if cluster.get("tracking_eligible")]
    high_risk = [cluster for cluster in joybuy_clusters if cluster["score"]["level"] in {"urgent", "high"}]
    negative = [cluster for cluster in joybuy_clusters if cluster["score"]["sentiment"] == "negative"]
    positive = [cluster for cluster in joybuy_clusters if cluster["score"]["sentiment"] == "positive"]
    joybuy_posts = [post for post in normalized_posts if post.get("brand") == "joybuy"]
    joybuy_effective_posts = [post for post in joybuy_posts if post.get("is_relevant")]
    source = source_status(normalized_posts, provider_hint)
    public_collection_status = public_collection_status_payload(collection_status or {})
    featured_items = build_featured_items(joybuy_clusters, competitor)
    hot_topics = build_hot_topics(joybuy_clusters, featured_items)
    effective_feed_items = build_effective_feed_items(normalized_posts, joybuy_clusters)

    overview = {
        "title": "Brand X Intelligence Radar",
        "generated_at": to_iso(current),
        "generated_at_label": beijing_label(current),
        "report_date": report_date,
        "report_window": "Past 24 hours",
        "window_label": window_label,
        "health": "normal",
        "metrics": {
            "effective_intelligence": len(joybuy_clusters),
            "high_risk": len(high_risk),
            "fermenting": sum(1 for item in fermentation_items if item["fermentation"]["status"] in {"升温中", "发酵中"}),
            "needs_review": sum(1 for item in joybuy_clusters if item["score"]["recommended_action"] in {"人工核查", "PR 准备回应", "高层同步"}),
            "primary_volume": len(joybuy_effective_posts),
            "primary_candidate_volume": len(joybuy_posts),
            "competitor_volume": competitor["volume"],
            "negative_share": round(len(negative) / max(1, len(joybuy_clusters)) * 100),
        },
        "executive_summary": build_executive_summary(joybuy_clusters, competitor),
        "top_intelligence": [cluster_summary(cluster) for cluster in joybuy_clusters[:10]],
        "negative_top": [cluster_summary(cluster) for cluster in negative[:10]],
        "opportunity_top": [cluster_summary(cluster) for cluster in positive[:10]],
        "fermentation_snapshot": [cluster_summary(cluster) for cluster in fermentation_items[:8]],
        "featured_items": featured_items,
        "hot_topics": hot_topics,
        "competitor": competitor,
        "source_status": source,
        "routes": {
            "daily": "dashboard-data/daily/latest.json",
            "fermentation": "dashboard-data/fermentation.json",
            "competitor": "dashboard-data/competitor.json",
            "source_status": "dashboard-data/source-status.json",
        },
    }

    daily = {
        "date": report_date,
        "generated_at": overview["generated_at"],
        "generated_at_label": overview["generated_at_label"],
        "window_label": window_label,
        "metrics": overview["metrics"],
        "source_status": overview["source_status"],
        "collection_status": public_collection_status,
        "executive_summary": overview["executive_summary"],
        "competitor": competitor,
        "featured_items": featured_items,
        "hot_topics": hot_topics,
        "effective_posts": effective_feed_items,
        "summary_only": False,
        "clusters": [cluster_summary(cluster, include_posts=False) for cluster in joybuy_clusters],
    }
    fermentation = {
        "generated_at": overview["generated_at"],
        "items": [cluster_summary(cluster, include_posts=False) for cluster in fermentation_items],
    }

    public_overview = public_dashboard_payload(overview)
    public_daily = public_dashboard_payload(daily)
    public_fermentation = {"generated_at": overview["generated_at"], "items": []}
    public_competitor = public_dashboard_payload(competitor)
    public_source = public_dashboard_payload(overview["source_status"])

    write_json(str(target / "latest.json"), public_overview)
    write_json(str(target / "daily" / "latest.json"), public_daily)
    write_daily_history(target, public_daily)
    write_json(str(target / "fermentation.json"), public_fermentation)
    write_json(str(target / "competitor.json"), public_competitor)
    write_json(str(target / "source-status.json"), public_source)
    data_bundle = {
        "dashboard-data/latest.json": public_overview,
        "dashboard-data/daily/latest.json": public_daily,
        "dashboard-data/fermentation.json": public_fermentation,
        "dashboard-data/competitor.json": public_competitor,
        "dashboard-data/source-status.json": public_source,
        "clusters": {},
    }
    for path, payload in daily_history_files(target).items():
        data_bundle[path] = payload
    write_data_bundle(target.parent / "dashboard-data-bundle.js", data_bundle)
    return public_overview


def public_dashboard_payload(value: Any, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in PUBLIC_DROP_KEYS:
                continue
            public_key = PUBLIC_KEY_REPLACEMENTS.get(key, key)
            result[public_key] = public_dashboard_payload(item, public_key)
        return result
    if isinstance(value, list):
        return [public_dashboard_payload(item, parent_key) for item in value]
    if isinstance(value, str):
        return public_string(value, parent_key)
    return value


def public_string(value: str, key: str = "") -> str:
    if key in SOURCE_TEXT_KEYS:
        return value
    if value == "joybuy":
        return "primary"
    if value == "temu":
        return "competitor"
    replacements = {
        "featured-joybuy-": "featured-primary-",
        "featured-temu-": "featured-competitor-",
        "joybuy-cluster-": "primary-signal-",
        "fallback-temu-": "fallback-competitor-",
        "all-temu-": "all-competitor-",
        "Joybuy / JD": "主品牌",
        "Joybuy/JD": "主品牌",
        "Joybuy": "主品牌",
        "JD.com": "主品牌",
        "Jingdong": "主品牌",
        "京东": "主品牌",
        "Temu": "样例竞品",
        "X 上": "公开社媒上",
        "X 原帖": "公开原帖",
        "X 舆情": "公开舆情",
        "during bake-off": "regularly",
        "Review duplicate rate and relevance during bake-off.": "Review duplicate rate and relevance regularly.",
        "No meaningful 主品牌 signal detected today.": "今日暂未发现有效主品牌舆情。",
        "Today's highest-priority 主品牌 signal is": "今日最高优先级主品牌舆情为",
        "Continue monitoring.": "继续监测。",
        "Recommended action": "建议动作",
        "baseline shows overlap around": "基线讨论涉及",
    }
    result = value
    for before, after in replacements.items():
        result = result.replace(before, after)
    return result


def write_daily_history(target: Path, current_daily: dict[str, Any]) -> None:
    daily_dir = target / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, Any]] = {}
    for record in load_existing_daily_records(daily_dir):
        records[record["date"]] = public_dashboard_payload(record)
    records[current_daily["date"]] = public_dashboard_payload(current_daily)

    for record in records.values():
        write_json(str(daily_dir / f"{record['date']}.json"), record)

    index = {
        "latest_date": current_daily["date"],
        "generated_at": current_daily["generated_at"],
        "items": [daily_index_item(record) for record in sorted(records.values(), key=lambda item: item["date"], reverse=True)],
    }
    write_json(str(daily_dir / "index.json"), index)


def load_existing_daily_records(daily_dir: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(daily_dir.glob("*.json")):
        if path.name in {"latest.json", "index.json"}:
            continue
        try:
            with open(path, "r", encoding="utf-8") as file:
                record = json.load(file)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(record, dict) and record.get("date"):
            records.append(record)
    return records


def daily_history_files(target: Path) -> dict[str, Any]:
    daily_dir = target / "daily"
    files: dict[str, Any] = {}
    for path in sorted(daily_dir.glob("*.json")):
        try:
            with open(path, "r", encoding="utf-8") as file:
                files[f"dashboard-data/daily/{path.name}"] = json.load(file)
        except (OSError, json.JSONDecodeError):
            continue
    return files


def daily_index_item(record: dict[str, Any]) -> dict[str, Any]:
    metrics = record.get("metrics", {})
    source_status = record.get("source_status", {})
    collection = record.get("collection_status", {})
    summary = record.get("executive_summary", {})
    clusters = record.get("clusters", [])
    top_cluster = clusters[0] if clusters else record.get("top_cluster", {})
    score = top_cluster.get("score", {})
    return {
        "date": record.get("date"),
        "generated_at_label": record.get("generated_at_label"),
        "window_label": record.get("window_label"),
        "title": top_cluster.get("title") or summary.get("headline") or "今日暂未发现有效主品牌舆情",
        "cluster_count": len(clusters) if clusters else metrics.get("effective_intelligence", 0),
        "primary_effective": source_status.get("brand_breakdown", {}).get(
            "primary_effective",
            source_status.get("brand_breakdown", {}).get("joybuy_effective", metrics.get("primary_volume", metrics.get("joybuy_volume", 0))),
        ),
        "competitor_effective": source_status.get("brand_breakdown", {}).get(
            "competitor_effective",
            source_status.get("brand_breakdown", {}).get("temu_effective", metrics.get("competitor_volume", metrics.get("temu_volume", 0))),
        ),
        "high_risk": metrics.get("high_risk", 0),
        "needs_review": metrics.get("needs_review", 0),
        "collection_status": collection.get("status", "unknown"),
        "ips": score.get("ips"),
        "level": score.get("level"),
        "summary_only": bool(record.get("summary_only")),
    }


def write_data_bundle(path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        file.write("window.__DASHBOARD_DATA__ = ")
        file.write(payload.replace("</", "<\\/"))
        file.write(";\n")


def build_executive_summary(clusters: list[dict[str, Any]], competitor: dict[str, Any]) -> dict[str, str]:
    top = clusters[0] if clusters else None
    if not top:
        return {
            "headline": "今日暂未发现有效主品牌舆情。",
            "risk": "Low",
            "action": "继续监测。",
        }
    shared = "refund and delivery" if any(term["term"] in {"refund", "delivery"} for term in competitor["top_terms"]) else "general shopping experience"
    return {
        "headline": f"今日最高优先级主品牌舆情为：{top['title']}。",
        "risk": f"Overall risk is {top['score']['level']} with IPS {top['score']['ips']}.",
        "action": f"建议动作：{top['score']['recommended_action']}。样例竞品基线讨论涉及 {shared}。",
    }


def build_effective_feed_items(posts: list[dict[str, Any]], clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cluster_by_post: dict[str, dict[str, Any]] = {}
    for cluster in clusters:
        for post_id in cluster.get("post_ids", []):
            cluster_by_post[str(post_id)] = cluster

    items = []
    for post in posts:
        if not post.get("is_relevant"):
            continue
        cluster = cluster_by_post.get(str(post.get("post_id", "")))
        items.append(effective_feed_item(post, cluster))
    return sorted(items, key=lambda item: str(item.get("created_at") or ""), reverse=True)


def effective_feed_item(post: dict[str, Any], cluster: dict[str, Any] | None = None) -> dict[str, Any]:
    brand = post.get("brand", "")
    topic = cluster.get("topic") if cluster else "competitor_baseline"
    score = cluster.get("score", {}) if cluster else {}
    sentiment = score.get("sentiment") if score else competitor_post_sentiment(post)
    risk_terms = cluster.get("risk_types", []) if cluster else post.get("risk_terms", [])
    opportunity_terms = cluster.get("opportunity_types", []) if cluster else post.get("opportunity_terms", [])
    matched_terms = dedupe_strings([*risk_terms, *opportunity_terms, topic])
    return {
        "post_id": post.get("post_id"),
        "brand": brand,
        "cluster_id": cluster.get("cluster_id", "") if cluster else "",
        "topic": topic,
        "url": post.get("url", ""),
        "text": post.get("clean_text") or post.get("text") or "",
        "original_text": post.get("text", ""),
        "links": post.get("links", []),
        "translation_zh": post.get("translation_zh") or post.get("clean_text") or post.get("text") or "",
        "translation_status": post.get("translation_status", "unknown"),
        "summary_zh": post.get("summary_zh", ""),
        "author_name": post.get("author", {}).get("name") or post.get("author_name"),
        "author_handle": post.get("author", {}).get("handle") or post.get("author_handle"),
        "author_avatar_url": post.get("author", {}).get("avatar_url") or post.get("author_avatar_url"),
        "author_followers": post.get("author", {}).get("followers", post.get("author_followers", 0)),
        "author_following": post.get("author", {}).get("following", post.get("author_following", 0)),
        "author_bio": post.get("author", {}).get("bio", post.get("author_bio", "")),
        "author_location": post.get("author", {}).get("location", post.get("author_location", "")),
        "author_joined_at": post.get("author", {}).get("joined_at", post.get("author_joined_at", "")),
        "author_verified": post.get("author", {}).get("verified", post.get("author_verified", False)),
        "created_at": post.get("created_at"),
        "reply_to_post_id": post.get("reply_to_post_id", ""),
        "reply_to_handle": post.get("reply_to_handle", ""),
        "quoted_post_id": post.get("quoted_post_id", ""),
        "conversation_id": post.get("conversation_id", ""),
        "language": post.get("language", "und"),
        "media": media_items(post),
        "metrics": post.get("metrics", {}),
        "sentiment": sentiment or "neutral",
        "level": score.get("level", "low"),
        "score_value": score.get("ips"),
        "score_label": "IPS" if cluster else "互动",
        "matched_terms": matched_terms,
    }


def competitor_post_sentiment(post: dict[str, Any]) -> str:
    text = str(post.get("clean_text") or post.get("text") or "").lower()
    positive_terms = {"quick", "solved", "good", "fast", "arrived", "discount", "lower price"}
    negative_terms = {"refund", "scam", "fake", "damaged", "slow", "missing", "customer service"}
    if any(term in text for term in positive_terms) and not any(term in text for term in negative_terms):
        return "positive"
    if any(term in text for term in negative_terms):
        return "negative"
    return "neutral"


def build_featured_items(joybuy_clusters: list[dict[str, Any]], competitor: dict[str, Any]) -> list[dict[str, Any]]:
    items = [featured_item_for_cluster(cluster) for cluster in joybuy_clusters if is_featured_cluster(cluster)]
    items = [item for item in items if item]
    items.extend(featured_item_for_competitor_post(post) for post in competitor.get("top_posts", []) if is_featured_competitor_post(post))
    return finalize_featured_items([item for item in items if item])


def finalize_featured_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    joybuy_items = sorted([item for item in items if item.get("brand") != "temu"], key=featured_priority_score, reverse=True)[:5]
    competitor_limit = 2 if joybuy_items else 3
    competitor_items = sorted([item for item in items if item.get("brand") == "temu"], key=featured_priority_score, reverse=True)[:competitor_limit]
    return sorted([*joybuy_items, *competitor_items], key=featured_priority_score, reverse=True)[:7]


def is_featured_cluster(cluster: dict[str, Any]) -> bool:
    score = cluster.get("score", {})
    post = representative_post(cluster)
    if not post or not post.get("url"):
        return False
    reason = analysis_reason_for_post(
        post,
        "joybuy",
        topic=cluster.get("topic", "general"),
        aggregate_metrics=cluster.get("metrics", {}),
        source_count=cluster.get("post_count", 1),
        score=score,
    )
    return (
        score.get("ips", 0) >= FEATURED_IPS_THRESHOLD
        or score.get("level") in {"urgent", "high"}
        or score.get("future_potential", 0) >= 65
        or score.get("current_impact", 0) >= 50
        or cluster.get("metrics", {}).get("max_author_followers", 0) >= 20_000
        or cluster.get("post_count", 0) > 1
        or bool(reason)
    )


def is_featured_competitor_post(post: dict[str, Any]) -> bool:
    metrics = post.get("metrics", {})
    interactions = public_interactions(metrics)
    views = int(metrics.get("views") or metrics.get("total_views") or 0)
    followers = int(post.get("author_followers") or post.get("author", {}).get("followers") or 0)
    text = source_text_for_reason(post).lower()
    focus = temu_focus_signal(text, post)
    if not focus["central"]:
        return False
    reason = analysis_reason_for_post(post, "temu", source_count=1)
    hard_risk_terms = {"refund", "scam", "fake", "damaged", "slow", "missing", "customer service"}
    sensitive = any(term in hard_risk_terms for term in post.get("matched_terms", []))
    return bool(reason) and (
        (sensitive and not focus["negative_trope"] and (views >= 50 or interactions > 0))
        or (focus["negative_trope"] and (views >= 1000 or interactions >= 5 or followers >= 20_000))
        or (focus["strong"] and (views >= 1000 or interactions >= 5 or followers >= 20_000))
        or views >= 2000
        or interactions >= 8
    )


def featured_item_for_cluster(cluster: dict[str, Any]) -> dict[str, Any] | None:
    post = representative_post(cluster)
    if not post:
        return None
    score = cluster.get("score", {})
    return {
        "id": f"featured-{cluster['cluster_id']}",
        "brand": cluster.get("brand", "joybuy"),
        "cluster_id": cluster["cluster_id"],
        "source_type": "公开舆情",
        "source_name": source_name_for_post(post, "主品牌"),
        "author_name": post.get("author", {}).get("name") or post.get("author_name") or post.get("author_handle"),
        "author_handle": post.get("author", {}).get("handle") or post.get("author_handle"),
        "author_avatar_url": post.get("author", {}).get("avatar_url") or post.get("author_avatar_url"),
        "author_followers": post.get("author", {}).get("followers", post.get("author_followers", 0)),
        "author_following": post.get("author", {}).get("following", post.get("author_following", 0)),
        "author_bio": post.get("author", {}).get("bio", post.get("author_bio", "")),
        "author_location": post.get("author", {}).get("location", post.get("author_location", "")),
        "author_joined_at": post.get("author", {}).get("joined_at", post.get("author_joined_at", "")),
        "author_verified": post.get("author", {}).get("verified", post.get("author_verified", False)),
        "post_url": post.get("url", ""),
        "reply_to_post_id": post.get("reply_to_post_id", ""),
        "reply_to_handle": post.get("reply_to_handle", ""),
        "quoted_post_id": post.get("quoted_post_id", ""),
        "conversation_id": post.get("conversation_id", ""),
        "created_at": post.get("created_at") or cluster.get("first_seen_at"),
        "language": post.get("language", "und"),
        "title": cluster["title"],
        "display_title": cluster.get("summary_zh") or cluster["title"],
        "original_text": post.get("text") or post.get("clean_text") or cluster.get("summary", ""),
        "translation_zh": post.get("translation_zh") or post.get("clean_text") or post.get("text") or cluster.get("summary_zh", ""),
        "translation_status": post.get("translation_status", "unknown"),
        "summary_zh": cluster.get("summary_zh", ""),
        "links": post.get("links", []),
        "media": media_items(post),
        "score": score,
        "score_value": score.get("ips", 0),
        "score_label": "IPS",
        "tags": featured_tags(cluster),
        "metrics": cluster.get("metrics", {}),
        "post_metrics": post.get("metrics", {}),
        "source_count": cluster.get("post_count", 1),
        "related_sources": max(0, cluster.get("post_count", 1) - 1),
        "selected_reason": selected_reason_for_cluster(cluster),
        "recommended_action": score.get("recommended_action", "持续监测"),
        "href": "",
        "external_href": post.get("url", ""),
        "sentiment": score.get("sentiment", "neutral"),
        "level": score.get("level", "low"),
    }


def featured_item_for_competitor_post(post: dict[str, Any]) -> dict[str, Any] | None:
    interactions = public_interactions(post.get("metrics", {}))
    score_value = min(100, 55 + round(interactions / 8))
    title = competitor_focus_title(post)
    return {
        "id": f"featured-temu-{post.get('post_id', '')}",
        "brand": "temu",
        "cluster_id": "",
        "source_type": "竞品异常",
        "source_name": source_name_for_post(post, "样例竞品"),
        "author_name": post.get("author_name") or post.get("author_handle"),
        "author_handle": post.get("author_handle"),
        "author_avatar_url": post.get("author_avatar_url"),
        "author_followers": post.get("author_followers", 0),
        "author_following": post.get("author_following", 0),
        "author_bio": post.get("author_bio", ""),
        "author_location": post.get("author_location", ""),
        "author_joined_at": post.get("author_joined_at", ""),
        "author_verified": post.get("author_verified", False),
        "post_url": post.get("url", ""),
        "reply_to_post_id": post.get("reply_to_post_id", ""),
        "reply_to_handle": post.get("reply_to_handle", ""),
        "quoted_post_id": post.get("quoted_post_id", ""),
        "conversation_id": post.get("conversation_id", ""),
        "created_at": post.get("created_at"),
        "language": post.get("language", "und"),
        "title": title,
        "display_title": title,
        "original_text": post.get("text", ""),
        "translation_zh": post.get("translation_zh") or post.get("clean_text") or post.get("text") or "",
        "translation_status": post.get("translation_status", "unknown"),
        "summary_zh": post.get("summary_zh", ""),
        "links": post.get("links", []),
        "media": media_items(post),
        "score": {"ips": score_value, "level": "medium", "sentiment": post.get("sentiment", "neutral")},
        "score_value": score_value,
        "score_label": "CSI",
        "tags": ["竞品", post.get("sentiment", "neutral"), *post.get("matched_terms", [])],
        "metrics": post.get("metrics", {}),
        "post_metrics": post.get("metrics", {}),
        "source_count": 1,
        "related_sources": 0,
        "selected_reason": analysis_reason_for_post(post, "temu", source_count=1),
        "recommended_action": "纳入竞品基线观察",
        "href": "",
        "external_href": post.get("url", ""),
        "sentiment": post.get("sentiment", "neutral"),
        "level": "medium",
    }


def representative_post(cluster: dict[str, Any]) -> dict[str, Any] | None:
    posts = cluster.get("posts", [])
    if not posts:
        return None
    return sorted(posts, key=representative_post_rank, reverse=True)[0]


def representative_post_rank(post: dict[str, Any]) -> tuple[int, int, int, str]:
    text = f"{post.get('clean_text') or post.get('text') or ''} {post.get('translation_zh') or ''}".lower()
    matched_terms = [str(term).lower() for term in post.get("matched_brand_terms", [])]
    explicit_joybuy = "joybuy" in text or any("joybuy" in term for term in matched_terms)
    ecommerce_context = any(
        term in text
        for term in [
            "order",
            "ordered",
            "delivery",
            "shipping",
            "parcel",
            "package",
            "refund",
            "return",
            "customer service",
            "coupon",
            "discount",
            "promo",
            "warehouse",
            "checkout",
            "下单",
            "订单",
            "物流",
            "配送",
            "包裹",
            "退款",
            "退货",
            "客服",
            "优惠",
            "仓库",
        ]
    )
    direct_score = 2 if explicit_joybuy else 0
    context_score = 1 if ecommerce_context else 0
    return (direct_score, context_score, public_interactions(post.get("metrics", {})), str(post.get("created_at") or ""))


def public_interactions(metrics: dict[str, Any]) -> int:
    return (
        int(metrics.get("likes") or metrics.get("total_likes") or 0)
        + int(metrics.get("reposts") or metrics.get("total_reposts") or 0)
        + int(metrics.get("replies") or metrics.get("total_replies") or 0)
        + int(metrics.get("quotes") or metrics.get("total_quotes") or 0)
    )


def analysis_reason_for_post(
    post: dict[str, Any],
    brand: str,
    topic: str = "",
    aggregate_metrics: dict[str, Any] | None = None,
    source_count: int = 1,
    score: dict[str, Any] | None = None,
) -> str:
    text = source_text_for_reason(post)
    signal = signal_context(text, brand, topic)
    metrics = post.get("metrics", {}) or aggregate_metrics or {}
    impact = impact_context(metrics, post)
    interactions = public_interactions(metrics)
    views = int(metrics.get("views") or metrics.get("total_views") or 0)
    followers = int(post.get("author_followers") or post.get("author", {}).get("followers") or 0)
    ips = int((score or {}).get("ips") or 0)
    temu_focus = temu_focus_signal(text, post) if brand == "temu" else {"central": True, "strong": False}
    if brand == "temu" and not temu_focus["central"]:
        return ""
    sensitive_enough = signal.get("sensitive") and (brand != "temu" or views >= 50 or interactions > 0)
    signal_has_evidence = signal["useful"] and (
        brand != "temu"
        or sensitive_enough
        or followers >= 20_000
        or views >= 1000
        or interactions >= 3
        or (views >= 50 and interactions > 0)
    )
    if brand == "temu":
        useful = signal_has_evidence or (
            temu_focus["strong"] and (followers >= 20_000 or views >= 1000 or interactions >= 5)
        )
    else:
        useful = (
            signal_has_evidence
            or source_count > 1
            or followers >= 20_000
            or views >= 1000
            or interactions >= 3
            or ips >= 65
        )
    if not useful:
        return ""
    count_phrase = f"，同日相似讨论 {source_count} 条" if source_count and source_count > 1 else ""
    return f"内容指向{signal['name']}：{signal['angle']}；{impact}{count_phrase}；研判：{signal['implication']}"


def source_text_for_reason(post: dict[str, Any]) -> str:
    return str(post.get("translation_zh") or post.get("clean_text") or post.get("text") or post.get("summary_zh") or "")


def has_term(text: str, terms: list[str]) -> bool:
    lower = text.lower()
    return any(term.lower() in lower or term in text for term in terms)


def signal_context(text: str, brand: str, topic: str = "") -> dict[str, Any]:
    brand_label = "竞品侧" if brand == "temu" else "主品牌"
    if topic == "positive_experience":
        return {
            "name": "正向购物体验",
            "angle": "用户主动提到价格、配送或购物体验上的正向感受",
            "implication": "可作为主品牌海外口碑和履约卖点的证据样本。",
            "useful": True,
        }
    if topic == "competitor_comparison":
        return {
            "name": "竞品对照与替代选择",
            "angle": "用户把主品牌与其他平台进行价格、配送或品类对比",
            "implication": "适合观察主品牌在海外用户购物选择中的竞争位置。",
            "useful": True,
        }
    if topic == "channel_activity":
        return {
            "name": "渠道合作与活动",
            "angle": "内容涉及渠道接入、商家合作、直播活动或站点更新",
            "implication": "可作为市场扩展和货架露出的背景信号。",
            "useful": True,
        }
    if topic == "company_market":
        return {
            "name": "公司/资本市场信息",
            "angle": "内容涉及公司战略、资本市场、行业报告或管理层动态",
            "implication": "对品牌心智有间接影响，应与消费者体验类舆情分开阅读。",
            "useful": True,
        }
    if topic in {"price_opportunity", "product_deal"}:
        return {
            "name": "价格促销与导购",
            "angle": "内容强调优惠、低价、券包或导购入口",
            "implication": "有助于观察样例竞品拉新促销话术及垃圾推广占比。" if brand == "temu" else "可评估是否存在可借势传播的价格/活动卖点。",
            "useful": True,
        }
    if topic == "regulatory":
        return {
            "name": "监管/并购风险",
            "angle": "内容涉及海外监管审查、并购交易或市场准入风险",
            "implication": "这类舆情可能影响管理层判断、市场信任和欧洲业务推进，应从普通消费体验中单独拎出。",
            "useful": True,
            "sensitive": True,
        }
    if topic == "fulfillment_risk" or topic == "refund" or has_term(text, ["refund", "退款", "退货", "售后", "chargeback"]):
        return {
            "name": "退款/售后体验",
            "angle": "用户明确提到退款、退货或售后处理",
            "implication": f"{brand_label}的信任成本会被放大，需关注是否出现更多相似投诉。",
            "useful": True,
            "sensitive": True,
        }
    if topic == "delivery" or has_term(text, ["delivery", "shipping", "parcel", "warehouse", "ships from", "发货", "配送", "物流", "包裹", "本地仓", "仓库", "transporteur", "commande"]):
        return {
            "name": "履约与物流心智",
            "angle": "原帖围绕发货、仓库、配送或包裹进度展开",
            "implication": "可作为样例竞品履约卖点/槽点的竞品参照。" if brand == "temu" else "需要判断这是正向履约口碑还是潜在配送投诉。",
            "useful": True,
        }
    if has_term(text, ["coupon", "discount", "promo", "deal", "save", "ultra-low", "优惠", "折扣", "券", "低价", "省钱", "促销"]):
        return {
            "name": "价格促销与导购",
            "angle": "内容强调优惠、低价、券包或导购入口",
            "implication": "有助于观察样例竞品拉新促销话术及垃圾推广占比。" if brand == "temu" else "可评估是否存在可借势传播的价格/活动卖点。",
            "useful": True,
        }
    if has_term(text, ["regulator", "regulatory", "investigation", "foreign subsidies", "subsidy", "charge sheet", "european commission", "ceconomy", "takeover", "acquisition", "antitrust", "欧盟", "监管", "收购", "并购", "补贴", "反垄断"]):
        return {
            "name": "监管/并购风险",
            "angle": "内容涉及海外监管审查、并购交易或市场准入风险",
            "implication": "这类舆情可能影响管理层判断、市场信任和欧洲业务推进，应从普通消费体验中单独拎出。",
            "useful": True,
            "sensitive": True,
        }
    if has_term(text, ["amazon", "fnac", "cdiscount", "micromania", "shein", "jd.com", "京东"]):
        return {
            "name": "多平台比价/货架露出",
            "angle": "原帖把品牌与其他电商平台并列展示",
            "implication": "适合观察品牌在海外用户心智中的货架位置和竞品集合。",
            "useful": True,
        }
    if brand == "temu" and has_term(text, ["cheap", "low quality", "knockoff", "lazy", "temu version", "temu-looking", "temu looking", "敷衍", "低质", "山寨", "乱七八糟"]):
        return {
            "name": "竞品低价/低质心智",
            "angle": "原帖把样例竞品作为低价、低质或山寨感的表达符号",
            "implication": "这类内容可作为竞品品牌心智参照，但只有出现较高传播时才需要进入焦点。",
            "useful": True,
            "sensitive": True,
        }
    if has_term(text, ["order", "cart", "shop", "buy", "下单", "订单", "购物车", "购买", "想试试"]):
        return {
            "name": "购买意向与日常购物",
            "angle": "用户表达下单、加购或尝试购买意向",
            "implication": "可作为竞品自然需求与用户使用场景样本，需结合互动与浏览判断是否异常。" if brand == "temu" else "可用于判断主品牌是否被真实用户纳入购买选择。",
            "useful": True,
        }
    if has_term(text, ["scam", "fake", "damaged", "stupid", "lazy", "nonsense", "蠢", "假", "坏了", "差", "敷衍", "乱七八糟"]):
        return {
            "name": "负向情绪/玩梗表达",
            "angle": "文本带有吐槽、嘲讽或低信任表达",
            "implication": "短期未必是正式投诉，但容易在高互动场景下转化为品牌负面语境。",
            "useful": True,
            "sensitive": True,
        }
    return {
        "name": "竞品日常声量" if brand == "temu" else "品牌日常声量",
        "angle": "原帖没有明显投诉或处置线索，主要体现日常提及",
        "implication": "适合进入声量基线，用于和后续异常波动做对照。",
        "useful": False,
    }


def impact_context(metrics: dict[str, Any], post: dict[str, Any]) -> str:
    interactions = public_interactions(metrics)
    replies = int(metrics.get("replies") or metrics.get("total_replies") or 0)
    reposts = int(metrics.get("reposts") or metrics.get("total_reposts") or 0)
    quotes = int(metrics.get("quotes") or metrics.get("total_quotes") or 0)
    views = int(metrics.get("views") or metrics.get("total_views") or 0)
    followers = int(post.get("author_followers") or post.get("author", {}).get("followers") or 0)
    if followers >= 20_000:
        return f"作者具备较高影响力（{followers} followers），当前 {interactions} 次赞评转引、{views} 浏览"
    if reposts + quotes >= 5:
        return f"转引信号相对突出，当前 {interactions} 次赞评转引、{views} 浏览"
    if replies >= 3:
        return f"评论参与高于普通样本，当前 {interactions} 次赞评转引、{views} 浏览"
    if views >= 1000 and interactions <= 3:
        return f"已有千级浏览但互动偏低，当前 {interactions} 次赞评转引、{views} 浏览"
    if interactions == 0:
        return f"当前传播仍弱，{views} 浏览且暂无赞评转引" if views else "当前尚未形成可见互动"
    return f"当前 {interactions} 次赞评转引、{views} 浏览"


def temu_focus_signal(text: str, post: dict[str, Any] | None = None) -> dict[str, bool]:
    raw = str(text or "")
    lower = raw.lower()
    post_data = post or {}
    matched_terms = post_data.get("matched_terms") or []
    tags_value = post_data.get("tags") or []
    tags = {str(tag).lower() for tag in [*matched_terms, *tags_value]}
    has_temu = bool(re.search(r"\btemu\b", lower))
    platform_phrases = bool(
        re.search(r"\b(order(?:ed|ing)?|buy|bought|shop|shopping|cart|coupon|discount|deal|gift|delivery|shipping|warehouse|app|ads?|haul|refund|return)\b.{0,36}\btemu\b", lower)
        or re.search(r"\btemu\b.{0,36}\b(order(?:ed|ing)?|buy|bought|shop|shopping|cart|coupon|discount|deal|gift|delivery|shipping|warehouse|app|ads?|haul|refund|return)\b", lower)
        or re.search(r"\b(from|off|on|via|through)\s+temu\b", lower)
        or has_term(raw, ["Temu 上", "Temu下", "Temu 订单", "Temu订单", "Temu 快递", "Temu快递", "Temu 配送", "Temu配送", "Temu 优惠", "Temu优惠", "Temu 折扣", "Temu折扣", "Temu App", "Temu 广告", "Temu广告", "Temu 购物车", "Temu购物车", "本地仓", "来自 Temu", "从 Temu"])
    )
    negative_trope = has_term(raw, ["cheap", "low quality", "knockoff", "fake", "lazy", "stupid", "temu version", "temu-looking", "temu looking", "敷衍", "低质", "山寨", "假", "蠢", "乱七八糟"])
    matched_topic = bool(tags & {"delivery", "refund", "return", "scam", "fake", "damaged", "slow", "missing", "customer service"})
    return {
        "central": has_temu and (platform_phrases or matched_topic or negative_trope),
        "strong": has_temu and (platform_phrases or matched_topic or negative_trope),
        "negative_trope": has_temu and negative_trope,
    }


def competitor_focus_title(post: dict[str, Any]) -> str:
    text = source_text_for_reason(post)
    signal = signal_context(text, "temu")
    if signal.get("sensitive"):
        return f"样例竞品{signal['name']}出现传播信号"
    if signal.get("useful"):
        return f"样例竞品{signal['name']}进入竞品观察"
    return "样例竞品异常讨论"


def source_name_for_post(post: dict[str, Any], fallback: str) -> str:
    handle = post.get("author", {}).get("handle") or post.get("author_handle")
    if handle:
        return f"{fallback} · @{handle}"
    return fallback


def featured_tags(cluster: dict[str, Any]) -> list[str]:
    score = cluster.get("score", {})
    tags = [cluster.get("topic", "general"), *cluster.get("risk_types", []), *cluster.get("opportunity_types", [])]
    if score.get("future_potential", 0) >= 75:
        tags.append("高潜传播")
    if cluster.get("metrics", {}).get("max_author_followers", 0) >= 20_000:
        tags.append("高影响力账号")
    if score.get("recommended_action") in {"人工核查", "PR 准备回应", "高层同步"}:
        tags.append("需处置")
    return dedupe_strings([tag for tag in tags if tag])


def selected_reason_for_cluster(cluster: dict[str, Any]) -> str:
    post = representative_post(cluster)
    if post:
        return analysis_reason_for_post(
            post,
            "joybuy",
            topic=cluster.get("topic", "general"),
            aggregate_metrics=cluster.get("metrics", {}),
            source_count=cluster.get("post_count", 1),
            score=cluster.get("score", {}),
        )
    score = cluster.get("score", {})
    base = score.get("explanation") or "该舆情达到焦点阈值，建议结合原帖证据持续观察。"
    source_count = cluster.get("post_count", 0)
    if source_count > 1:
        base += f" 当前关联到 {source_count} 条同日相似讨论。"
    if cluster.get("metrics", {}).get("max_author_followers", 0) >= 20_000:
        base += " 其中包含高影响力账号信号。"
    return base


def media_items(post: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for item in post.get("media", []) or []:
        if isinstance(item, str):
            items.append({"url": item, "type": "image"})
        elif isinstance(item, dict):
            url = (
                item.get("media_url_https")
                or item.get("media_url")
                or item.get("mediaUrlHttps")
                or item.get("mediaUrl")
                or item.get("preview_image_url")
                or item.get("previewImageUrl")
                or item.get("thumbnail_url")
                or item.get("thumbnailUrl")
                or item.get("image_url")
                or item.get("imageUrl")
                or item.get("url")
                or item.get("src")
            )
            if url:
                media_type = str(item.get("type") or item.get("media_type") or "image")
                payload: dict[str, Any] = {
                    "url": url,
                    "type": media_type,
                }
                preview_url = (
                    item.get("media_url_https")
                    or item.get("media_url")
                    or item.get("preview_image_url")
                    or item.get("previewImageUrl")
                    or item.get("thumbnail_url")
                    or item.get("thumbnailUrl")
                )
                if preview_url:
                    payload["preview_image_url"] = preview_url
                    payload["media_url_https"] = preview_url
                video_info = item.get("video_info") or item.get("videoInfo")
                if video_info:
                    payload["video_info"] = video_info
                expanded_url = item.get("expanded_url") or item.get("expandedUrl")
                if expanded_url:
                    payload["expanded_url"] = expanded_url
                items.append(payload)
    return items[:4]


def dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def featured_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    brand_priority = 1 if item.get("brand") != "temu" else 0
    return (brand_priority, int(item.get("score_value") or 0), str(item.get("created_at") or ""))


def featured_priority_score(item: dict[str, Any]) -> int:
    metrics = item.get("post_metrics") or item.get("metrics") or {}
    views = int(metrics.get("views") or metrics.get("total_views") or 0)
    interactions = public_interactions(metrics)
    followers = int(item.get("author_followers") or 0)
    source_count = int(item.get("source_count") or 1)
    tags = {str(tag).lower() for tag in item.get("tags", [])}
    score = int(item.get("score", {}).get("ips") or item.get("score_value") or 0)
    value = 0
    if item.get("brand") != "temu":
        value += 40
    if tags & {"refund", "delivery", "customer_service", "fulfillment_risk", "trust_safety", "regulatory"}:
        value += 16
    if tags & {"positive_value", "delivery_strength", "price_opportunity", "positive_experience", "product_deal", "competitor_comparison"}:
        value += 10
    value += min(40, score)
    value += min(20, source_count * 4)
    value += min(24, interactions * 3)
    value += min(16, len(str(max(1, views))) * 4)
    value += min(16, len(str(max(1, followers))) * 3)
    return value


def build_hot_topics(joybuy_clusters: list[dict[str, Any]], featured_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topics = []
    for rank, item in enumerate(featured_items[:5], start=1):
        topics.append(
            {
                "rank": rank,
                "title": item.get("display_title") or item.get("title", "Intelligence signal"),
                "cluster_id": item.get("cluster_id", ""),
                "score_value": item.get("score_value"),
                "level": item.get("level"),
                "source_count": item.get("source_count", 1),
                "count_label": f"{item.get('source_count', 1)} 条同日相似讨论" if item.get("source_count", 1) > 1 else item.get("source_type", "1 条原帖"),
                "reason": item.get("selected_reason", ""),
            }
        )
    if topics:
        return topics
    for rank, cluster in enumerate(joybuy_clusters[:3], start=1):
        score = cluster.get("score", {})
        topics.append(
            {
                "rank": rank,
                "title": cluster.get("summary_zh") or cluster.get("title", "Joybuy intelligence signal"),
                "cluster_id": cluster.get("cluster_id", ""),
                "score_value": score.get("ips"),
                "level": score.get("level"),
                "source_count": cluster.get("post_count", 0),
                "count_label": f"{cluster.get('post_count', 0)} 条同日相似讨论",
                "reason": score.get("explanation", ""),
            }
        )
    return topics


def cluster_summary(cluster: dict[str, Any], include_posts: bool = False) -> dict[str, Any]:
    post = representative_post(cluster)
    data = {
        "cluster_id": cluster["cluster_id"],
        "title": cluster["title"],
        "summary": cluster["summary"],
        "summary_zh": cluster["summary_zh"],
        "lead_post": lead_post_summary(post) if post else {},
        "topic": cluster["topic"],
        "risk_types": cluster["risk_types"],
        "opportunity_types": cluster["opportunity_types"],
        "post_count": cluster["post_count"],
        "first_seen_at": cluster["first_seen_at"],
        "last_seen_at": cluster["last_seen_at"],
        "metrics": cluster["metrics"],
        "score": cluster["score"],
        "fermentation": cluster["fermentation"],
        "tracking_eligible": cluster["tracking_eligible"],
        "tracking_reason": cluster["tracking_reason"],
        "evidence_counts": {key: len(value) for key, value in cluster["evidence_chain"].items()},
    }
    if include_posts:
        data["posts"] = cluster["posts"]
    return data


def lead_post_summary(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_id": post.get("post_id"),
        "created_at": post.get("created_at"),
        "author": post.get("author", {}),
        "author_name": post.get("author", {}).get("name") or post.get("author_name"),
        "author_handle": post.get("author", {}).get("handle") or post.get("author_handle"),
        "author_avatar_url": post.get("author", {}).get("avatar_url") or post.get("author_avatar_url"),
        "author_followers": post.get("author", {}).get("followers", post.get("author_followers", 0)),
        "author_following": post.get("author", {}).get("following", post.get("author_following", 0)),
        "author_bio": post.get("author", {}).get("bio", post.get("author_bio", "")),
        "author_location": post.get("author", {}).get("location", post.get("author_location", "")),
        "author_joined_at": post.get("author", {}).get("joined_at", post.get("author_joined_at", "")),
        "author_verified": post.get("author", {}).get("verified", post.get("author_verified", False)),
        "url": post.get("url", ""),
        "reply_to_post_id": post.get("reply_to_post_id", ""),
        "reply_to_handle": post.get("reply_to_handle", ""),
        "quoted_post_id": post.get("quoted_post_id", ""),
        "conversation_id": post.get("conversation_id", ""),
        "language": post.get("language", "und"),
        "text": post.get("text") or post.get("clean_text") or "",
        "clean_text": post.get("clean_text") or post.get("text") or "",
        "links": post.get("links", []),
        "translation_zh": post.get("translation_zh") or post.get("clean_text") or post.get("text") or "",
        "translation_status": post.get("translation_status", "unknown"),
        "summary_zh": post.get("summary_zh", ""),
        "metrics": post.get("metrics", {}),
        "media": media_items(post),
    }


def cluster_detail(cluster: dict[str, Any]) -> dict[str, Any]:
    return {
        **cluster_summary(cluster, include_posts=True),
        "evidence_chain": cluster["evidence_chain"],
        "score_explanation": cluster["score"]["explanation"],
    }


def source_status(posts: list[dict[str, Any]], provider_hint: str | None = None) -> dict[str, Any]:
    providers = sorted({post.get("source_provider", "unknown") for post in posts})
    if not providers and provider_hint:
        providers = [provider_hint]
    is_sample = providers == ["sample"]
    translation = translation_status(posts)
    joybuy_posts = [post for post in posts if post.get("brand") == "joybuy"]
    temu_posts = [post for post in posts if post.get("brand") == "temu"]
    return {
        "status": "sample" if is_sample else "normal",
        "raw_posts_collected": len(posts),
        "effective_posts": sum(1 for post in posts if post.get("is_relevant")),
        "brand_breakdown": {
            "primary_candidates": len(joybuy_posts),
            "primary_effective": sum(1 for post in joybuy_posts if post.get("is_relevant")),
            "competitor_candidates": len(temu_posts),
            "competitor_effective": sum(1 for post in temu_posts if post.get("is_relevant")),
        },
        "translation": translation,
        "notes": source_notes(is_sample, translation),
    }


def translation_status(posts: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for post in posts:
        status = str(post.get("translation_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {
        "counts": counts,
        "missing_count": counts.get("missing", 0) + counts.get("error", 0),
        "fallback_original_count": counts.get("missing", 0) + counts.get("error", 0),
    }


def source_notes(is_sample: bool, translation: dict[str, Any]) -> list[str]:
    base = [
        "Bookmarks are collected only when the data source provides them.",
        "Quote counts are treated as public propagation signals.",
    ]
    if is_sample:
        return [
            "Sample data mode is active for structure and interaction preview.",
            *base,
            "Sample translations are generated from the local sample dictionary.",
        ]
    translation_note = (
        f"Chinese translation unavailable for {translation['missing_count']} posts; original text is shown as fallback."
        if translation.get("missing_count")
        else "Chinese translation coverage is complete."
    )
    return [
        "Public social data collection is active. Review duplicate rate and relevance regularly.",
        *base,
        translation_note,
    ]


def public_collection_status_payload(collection_status: dict[str, Any]) -> dict[str, Any]:
    translation = collection_status.get("translation") or {}
    public_payload = {
        "status": collection_status.get("status", "unknown"),
        "warnings": public_warnings(collection_status.get("warnings", [])),
    }
    if translation:
        public_payload["translation"] = {
            "configured": bool(translation.get("configured", False)),
            "counts": translation.get("counts", {}),
            "missing_count": translation.get("missing_count", 0),
            "fallback_original_count": translation.get("fallback_original_count", translation.get("missing_count", 0)),
        }
    return public_payload


def public_warnings(warnings: list[Any]) -> list[str]:
    results = []
    for warning in warnings:
        text = str(warning)
        if "translation" in text.lower():
            results.append("Chinese translation is unavailable for some posts; original text is shown as fallback.")
        elif "budget" in text.lower() or "request" in text.lower() or "provider" in text.lower():
            results.append("Collection stopped early after reaching a protective runtime threshold.")
        else:
            results.append("Collection completed with a non-critical warning.")
    return results[:3]
