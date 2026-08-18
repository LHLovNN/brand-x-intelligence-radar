#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "dashboard-data"
CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
URL_RE = re.compile(r"https?://\S+|t\.co/\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"@[A-Za-z0-9_]{1,20}")
TEXT_SIGNAL_RE = re.compile(r"[A-Za-z0-9\u3400-\u9fff]")
LOW_QUALITY_CONTEXT_RE = re.compile(
    r"应该没人比我玩[的得]开了吧|我[福肤]不黑不信你看|比(?:我|你|他|她|ta)好看的没(?:我|你|他|她|ta)骚.{0,20}比(?:我|你|他|她|ta)骚的没(?:我|你|他|她|ta)好看|只入身体.{0,20}不入生活",
    re.IGNORECASE,
)
LOW_QUALITY_CONTEXT_PROFILE_RE = re.compile(
    r"找炮友|约炮|曰炮|入驻.{0,12}炮平台|真人认证.{0,30}隐私|附近的可加v|小号已禁言",
    re.IGNORECASE,
)
PLATFORM_ALLOWED_TAGS = {
    "账号冷启动",
    "爆文与内容结构",
    "流量机制",
    "变现",
    "私域引流",
    "案例复盘",
    "小红书方法论",
}


def load(path: Path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def walk_objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_objects(child)


def needs_context_translation(text: str) -> bool:
    if not text or CHINESE_RE.search(text):
        return False
    compact = URL_RE.sub("", text)
    compact = MENTION_RE.sub("", compact)
    return bool(TEXT_SIGNAL_RE.search(compact))


def verify_conversation_contexts(payload, label: str) -> None:
    for obj in walk_objects(payload):
        context = obj.get("conversation_context")
        if not isinstance(context, dict):
            continue
        posts = context.get("posts") or []
        if not posts:
            continue
        anchor = context.get("anchor_post_id") or obj.get("post_id") or "unknown"
        assert_true(len(posts) > 1, f"{label}:{anchor} conversation context should include neighboring posts")
        summary = str(context.get("summary_zh") or "")
        assert_true(len(summary) <= 200, f"{label}:{anchor} conversation context summary exceeds 200 chars")
        for post in posts:
            text = str(post.get("text") or post.get("original_text") or "")
            translation = str(post.get("translation_zh") or "")
            post_id = post.get("post_id") or "unknown"
            compact = re.sub(r"\s+", "", f"{text} {translation}")
            profile = " ".join(str(post.get(key) or "") for key in ("author_name", "author_handle", "author_bio"))
            compact_profile = re.sub(r"\s+", "", profile)
            assert_true(not LOW_QUALITY_CONTEXT_RE.search(compact), f"{label}:{anchor}:{post_id} context contains low-quality vulgar noise")
            assert_true(
                not LOW_QUALITY_CONTEXT_PROFILE_RE.search(compact_profile),
                f"{label}:{anchor}:{post_id} context contains low-quality adult spam profile",
            )
            assert_true(translation.strip(), f"{label}:{anchor}:{post_id} missing context translation")
            if needs_context_translation(text):
                assert_true(
                    bool(CHINESE_RE.search(translation)),
                    f"{label}:{anchor}:{post_id} context translation should be Chinese",
                )


def contextual_ids(item):
    ids = set()
    conversation_id = str(item.get("conversation_id") or "").strip()
    if conversation_id:
        ids.add(f"conversation:{conversation_id}")
    post_id = str(item.get("post_id") or item.get("id") or "").strip()
    if post_id:
        ids.add(f"post:{post_id}")
    context = item.get("conversation_context")
    if isinstance(context, dict):
        for post in context.get("posts") or []:
            if isinstance(post, dict) and post.get("post_id"):
                ids.add(f"post:{post['post_id']}")
    return ids


def verify_no_contextual_duplicate_items(items, label: str) -> None:
    groups = []
    for item in items or []:
        ids = contextual_ids(item)
        if not ids:
            continue
        for group in groups:
            if ids & group["ids"]:
                fail(f"{label}: duplicate collected items share the same context window")
        groups.append({"ids": ids})


def verify_platform_trends() -> None:
    latest_path = DATA / "platform-trends" / "xiaohongshu" / "latest.json"
    index_path = DATA / "platform-trends" / "xiaohongshu" / "index.json"
    if not latest_path.exists() and not index_path.exists():
        return
    assert_true(latest_path.exists(), "platform trends latest should exist when index exists")
    assert_true(index_path.exists(), "platform trends index should exist when latest exists")
    latest = load(latest_path)
    index = load(index_path)
    items = latest.get("items") or []
    collection_status = latest.get("collection_status", {})
    max_items = collection_status.get("max_items", 20)
    min_views = int(collection_status.get("min_views", 500) or 0)
    min_likes = int(collection_status.get("min_likes", 10) or 0)
    assert_true(len(items) <= max_items, "platform trends should not exceed daily max items")
    times = [str(item.get("created_at") or "") for item in items]
    assert_true(times == sorted(times, reverse=True), "platform trends should be sorted by publish time desc")
    assert_true(index.get("latest_date") == latest.get("date"), "platform trends latest date mismatch")
    if items:
        verify_no_contextual_duplicate_items(items, "platform-trends/xiaohongshu/latest")
        for item in items:
            assert_true(item.get("translation_zh"), "platform trend item should include Chinese display text")
            assert_true(
                str(item.get("topic") or "") in PLATFORM_ALLOWED_TAGS,
                f"platform trend topic should use controlled taxonomy: {item.get('topic')}",
            )
            tags = [str(tag or "") for tag in item.get("tags") or []]
            unexpected_tags = [tag for tag in tags if tag not in PLATFORM_ALLOWED_TAGS]
            assert_true(not unexpected_tags, f"platform trend tags should use controlled taxonomy: {unexpected_tags}")
            metrics = item.get("post_metrics") or item.get("metrics") or {}
            assert_true(int(metrics.get("views") or 0) >= min_views, "platform trend item should meet min views")
            assert_true(int(metrics.get("likes") or 0) >= min_likes, "platform trend item should meet min likes")
        verify_conversation_contexts(latest, "platform-trends/xiaohongshu/latest")


def main() -> None:
    latest = load(DATA / "latest.json")
    daily = load(DATA / "daily" / "latest.json")
    daily_index = load(DATA / "daily" / "index.json")
    fermentation = load(DATA / "fermentation.json")
    competitor = load(DATA / "competitor.json")
    source = load(DATA / "source-status.json")
    is_sample = source.get("status") == "sample"
    is_real_provider = not is_sample
    bundle_path = ROOT / "public" / "dashboard-data-bundle.js"
    assert_true(bundle_path.exists(), "dashboard-data-bundle.js should exist for file:// preview")

    clusters = daily.get("clusters", [])
    if is_sample:
        assert_true(clusters, "sample daily clusters should not be empty")
    assert_true(daily.get("date"), "daily latest should include report date")
    assert_true(daily_index.get("items"), "daily history index should not be empty")
    assert_true(daily_index["items"][0]["date"] == daily["date"], "daily history latest date mismatch")
    for item in daily_index["items"]:
        archive_path = DATA / "daily" / f"{item['date']}.json"
        assert_true(archive_path.exists(), f"missing daily archive file for {item['date']}")
    assert_true(latest["metrics"]["effective_intelligence"] == len(clusters), "effective intelligence metric mismatch")
    expected_source_status = "sample" if is_sample else "normal"
    assert_true(source["status"] == expected_source_status, f"source status should be {expected_source_status}")
    assert_true(source["raw_posts_collected"] >= source["effective_posts"], "raw posts should be >= effective posts")
    verify_conversation_contexts(latest, "latest")
    verify_conversation_contexts(daily, "daily/latest")
    verify_conversation_contexts(competitor, "competitor")
    verify_no_contextual_duplicate_items(latest.get("featured_items") or [], "latest featured_items")
    verify_no_contextual_duplicate_items(daily.get("featured_items") or [], "daily latest featured_items")
    for item in daily_index["items"]:
        archive_path = DATA / "daily" / f"{item['date']}.json"
        if archive_path.exists():
            verify_conversation_contexts(load(archive_path), f"daily/{item['date']}")
    verify_platform_trends()

    tracked = [cluster for cluster in clusters if cluster.get("tracking_eligible")]
    assert_true(len(fermentation["items"]) == len(tracked), "fermentation tracked count mismatch")
    if is_sample:
        assert_true(any(cluster["score"]["sentiment"] == "positive" for cluster in clusters), "expected at least one positive opportunity cluster")
        assert_true(any(cluster["score"]["level"] in {"urgent", "high"} for cluster in clusters), "expected high risk clusters")

    for cluster in clusters:
        cluster_id = cluster["cluster_id"]
        if daily.get("summary_only") or str(cluster_id).startswith("archive-"):
            continue
        detail_path = DATA / "clusters" / f"{cluster_id}.json"
        if not detail_path.exists():
            continue
        detail = load(detail_path)
        assert_true(detail["score"]["ips"] == cluster["score"]["ips"], f"detail score mismatch for {cluster_id}")
        assert_true("evidence_chain" in detail, f"missing evidence chain for {cluster_id}")
        for key, count in detail["evidence_counts"].items():
            assert_true(len(detail["evidence_chain"].get(key, [])) == count, f"evidence count mismatch for {cluster_id}:{key}")
        assert_true("total_quotes" in detail["metrics"], f"missing quote metric for {cluster_id}")
        assert_true("total_bookmarks" in detail["metrics"], f"missing bookmark metric for {cluster_id}")

    competitor_total = sum(competitor["sentiment"].values())
    assert_true(competitor_total == competitor["volume"], "competitor sentiment total mismatch")
    if is_sample:
        assert_true(competitor["top_posts"], "sample competitor top posts should not be empty")
    if is_real_provider and source["raw_posts_collected"] == 0:
        assert_true(competitor["volume"] == 0, "empty real source should not create competitor volume")

    print("Dashboard data verification passed.")
    print(f"Data mode: {source.get('status', 'unknown')}")
    print(f"Primary signals: {len(clusters)}")
    print(f"Tracked: {len(tracked)}")
    print(f"Competitor posts: {competitor['volume']}")


if __name__ == "__main__":
    main()
