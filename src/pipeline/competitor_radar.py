from collections import Counter
from typing import Any


NEGATIVE_TERMS = {"refund", "delivery", "scam", "fake", "damaged", "slow", "missing", "customer service"}
HARD_NEGATIVE_TERMS = {"refund", "scam", "fake", "damaged", "slow", "missing"}
POSITIVE_TERMS = {"quick", "solved", "good", "fast", "arrived", "surprisingly"}


def build_competitor_radar(posts: list[dict[str, Any]]) -> dict[str, Any]:
    temu_posts = [post for post in posts if post.get("brand") == "temu" and post.get("is_relevant")]
    sentiments = Counter(sentiment_for(post) for post in temu_posts)
    top_terms = extract_terms(temu_posts)
    top_posts = sorted(
        temu_posts,
        key=lambda item: item["metrics"]["likes"] + item["metrics"]["reposts"] + item["metrics"]["replies"] + item["metrics"]["quotes"],
        reverse=True,
    )[:10]
    return {
        "brand": "temu",
        "volume": len(temu_posts),
        "sentiment": {
            "negative": sentiments.get("negative", 0),
            "neutral": sentiments.get("neutral", 0),
            "positive": sentiments.get("positive", 0),
        },
        "top_terms": top_terms,
        "top_posts": [post_card(post) for post in top_posts],
        "anomalies": [
            "Temu fake discount discussion has higher interaction than other competitor topics."
        ]
        if any("fake" in post["clean_text"].lower() for post in temu_posts)
        else [],
    }


def sentiment_for(post: dict[str, Any]) -> str:
    text = post["clean_text"].lower()
    has_positive = any(term in text for term in POSITIVE_TERMS)
    has_hard_negative = any(term in text for term in HARD_NEGATIVE_TERMS)
    if has_positive and not has_hard_negative:
        return "positive"
    if has_hard_negative or "customer service" in text:
        return "negative"
    return "neutral"


def extract_terms(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for post in posts:
        for term in list(NEGATIVE_TERMS) + list(POSITIVE_TERMS):
            if term in post["clean_text"].lower():
                counter[term] += 1
    return [{"term": term, "count": count} for term, count in counter.most_common(8)]


def post_card(post: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_id": post["post_id"],
        "url": post["url"],
        "text": post["clean_text"],
        "original_text": post.get("text", ""),
        "links": post.get("links", []),
        "translation_zh": post.get("translation_zh") or post.get("clean_text") or post.get("text") or "",
        "translation_status": post.get("translation_status", "unknown"),
        "translation_provider": post.get("translation_provider", "none"),
        "summary_zh": post["summary_zh"],
        "author_name": post["author"].get("name") or post["author"].get("handle"),
        "author_handle": post["author"]["handle"],
        "author_avatar_url": post["author"].get("avatar_url"),
        "author_followers": post["author"].get("followers", 0),
        "author_following": post["author"].get("following", 0),
        "author_bio": post["author"].get("bio", ""),
        "author_location": post["author"].get("location", ""),
        "author_joined_at": post["author"].get("joined_at", ""),
        "author_verified": post["author"].get("verified", False),
        "created_at": post["created_at"],
        "reply_to_post_id": post.get("reply_to_post_id", ""),
        "reply_to_handle": post.get("reply_to_handle", ""),
        "quoted_post_id": post.get("quoted_post_id", ""),
        "conversation_id": post.get("conversation_id", ""),
        "conversation_context": post.get("conversation_context", {}),
        "language": post.get("language", "und"),
        "media": post.get("media", []),
        "metrics": post["metrics"],
        "sentiment": sentiment_for(post),
        "matched_terms": post.get("risk_terms", []) + post.get("opportunity_terms", []),
    }
