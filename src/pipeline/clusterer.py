from collections import defaultdict
from typing import Any


def _combined_text(post: dict[str, Any]) -> str:
    return f"{post.get('clean_text', '')} {post.get('translation_zh', '')}".lower()


def _has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _has_commerce_risk_context(text: str) -> bool:
    return _has_any(
        text,
        [
            "order",
            "orders",
            "refund",
            "return goods",
            "return item",
            "return package",
            "delivery",
            "shipping",
            "tracking",
            "parcel",
            "package",
            "customer service",
            "support",
            "seller",
            "warehouse",
            "退货",
            "退款",
            "订单",
            "配送",
            "物流",
            "包裹",
            "客服",
            "售后",
        ],
    )


def _has_financial_context(text: str) -> bool:
    return _has_any(
        text,
        [
            "total return",
            "shareholder return",
            "stock",
            "stocks",
            "share",
            "shares",
            "equity",
            "nasdaq",
            "hang seng",
            "market cap",
            "valuation",
            "portfolio",
            "invest",
            "股票",
            "股价",
            "投资",
            "指数",
            "估值",
        ],
    )


def _topic_for(post: dict[str, Any]) -> str:
    text = _combined_text(post)

    if _has_any(
        text,
        [
            "regulator",
            "regulatory",
            "investigation",
            "foreign subsidies",
            "subsidy",
            "charge sheet",
            "european commission",
            "ceconomy",
            "takeover",
            "antitrust",
            "监管",
            "欧盟",
            "反垄断",
            "市场准入",
        ],
    ):
        return "regulatory"

    if _has_financial_context(text) or _has_any(
        text,
        [
            "ceo",
            "fortune",
            "white paper",
            "report",
            "strategy",
            "ai pivot",
            "logistics network",
            "公司",
            "白皮书",
            "报告",
            "战略",
            "物流网络",
            "新品方法论",
            "女 CEO",
        ],
    ):
        return "company_market"

    has_refund_or_service = _has_any(
        text,
        [
            "refund",
            "chargeback",
            "customer service",
            "support",
            "missing order",
            "damaged",
            "broken",
            "退货",
            "退款",
            "售后",
            "客服",
            "损坏",
        ],
    )
    has_return_only = "return" in text and not _has_financial_context(text)
    if (has_refund_or_service or has_return_only) and _has_commerce_risk_context(text):
        return "fulfillment_risk"

    if _has_any(
        text,
        [
            "scam",
            "fake",
            "privacy",
            "security",
            "deceptive",
            "data",
            "fraud",
            "骗局",
            "虚假",
            "隐私",
            "安全",
        ],
    ):
        return "trust_safety"

    if _has_any(
        text,
        [
            "faster than",
            "fast delivery",
            "arrived early",
            "delivered my",
            "good deal",
            "great price",
            "recommend",
            "satisfied",
            "cheaper",
            "better value",
            "helft van de prijs",
            "idioot snel",
            "voordeliger",
            "delivery is",
            "配送快",
            "更划算",
            "价格通常只有一半",
            "快得离谱",
            "最多一天",
            "推荐",
            "正向",
        ],
    ):
        return "positive_experience"

    if _has_any(
        text,
        [
            "temu",
            "amazon",
            "alibaba",
            "tjin",
            "jumia",
            "compared",
            "versus",
            " vs ",
            "instead of",
            "switch from",
            "same products",
            "lower price",
            "品类更多",
            "同样的产品",
            "价格更低",
            "对比",
        ],
    ) and _has_any(text, ["joybuy", "jd.com", "京东"]):
        return "competitor_comparison"

    if _has_any(
        text,
        [
            "deal",
            "discount",
            "promo",
            "coupon",
            "in stock",
            "available",
            "€",
            "£",
            "$",
            "tidd.ly",
            "affiliate",
            "立即购买",
            "有货",
            "售价",
            "价格降到",
            "上架",
            "折扣",
            "优惠",
        ],
    ):
        return "product_deal"

    if _has_any(
        text,
        [
            "marketplace",
            "partner",
            "partnership",
            "subscription",
            "live",
            "launch",
            "site update",
            "shop update",
            "jd.com live",
            "合作伙伴",
            "直播",
            "订阅服务",
            "平台接入",
            "站点更新",
        ],
    ):
        return "channel_activity"

    return "general_observation"


def cluster_posts(posts: list[dict[str, Any]], brand: str) -> list[dict[str, Any]]:
    relevant = [post for post in posts if post.get("brand") == brand and post.get("is_relevant")]
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for post in relevant:
        buckets[_topic_for(post)].append(post)

    clusters = []
    for index, (topic, grouped) in enumerate(sorted(buckets.items()), start=1):
        first_seen = min(item["created_at"] for item in grouped)
        last_seen = max(item["created_at"] for item in grouped)
        total_likes = sum(item["metrics"]["likes"] for item in grouped)
        total_reposts = sum(item["metrics"]["reposts"] for item in grouped)
        total_replies = sum(item["metrics"]["replies"] for item in grouped)
        total_quotes = sum(item["metrics"]["quotes"] for item in grouped)
        total_views = sum(item["metrics"]["views"] or 0 for item in grouped)
        max_followers = max(item["author"]["followers"] for item in grouped)
        cluster_id = f"{brand}-cluster-{index:03d}"
        clusters.append(
            {
                "cluster_id": cluster_id,
                "brand": brand,
                "canonical_brand_entity": grouped[0].get("canonical_brand_entity", brand),
                "topic": topic,
                "title": title_for_topic(topic),
                "summary": summary_for_topic(topic, grouped),
                "summary_zh": summary_zh_for_topic(topic, grouped),
                "language_mix": sorted({item["language"] for item in grouped}),
                "risk_types": risk_types_for_topic(topic),
                "opportunity_types": opportunity_types_for_topic(topic),
                "post_ids": [item["post_id"] for item in grouped],
                "posts": grouped,
                "post_count": len(grouped),
                "history_status": "archived",
                "tracking_eligible": False,
                "tracking_reason": [],
                "tracking_until": None,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "metrics": {
                    "total_likes": total_likes,
                    "total_reposts": total_reposts,
                    "total_replies": total_replies,
                    "total_quotes": total_quotes,
                    "total_bookmarks": sum(item["metrics"]["bookmarks"] or 0 for item in grouped),
                    "total_views": total_views,
                    "max_author_followers": max_followers,
                    "public_interactions": total_likes + total_reposts + total_replies + total_quotes,
                },
                "evidence_chain": {},
                "score": {},
                "fermentation": {},
            }
        )
    return clusters


def title_for_topic(topic: str) -> str:
    titles = {
        "positive_experience": "Positive shopping experience around Joybuy",
        "product_deal": "Product, deal and availability discussion",
        "fulfillment_risk": "Fulfillment and after-sales risk discussion",
        "trust_safety": "Trust, safety and authenticity concerns",
        "competitor_comparison": "Competitor comparison and substitution signals",
        "channel_activity": "Channel, partner and campaign activity",
        "company_market": "Corporate, market and strategy discussion",
        "regulatory": "Regulatory and market-access scrutiny around JD.com",
        "general_observation": "General Joybuy/JD overseas shopping discussion",
    }
    return titles.get(topic, "General Joybuy discussion")


def summary_for_topic(topic: str, posts: list[dict[str, Any]]) -> str:
    count = len(posts)
    summaries = {
        "positive_experience": f"{count} related posts praise price, delivery speed or buying experience.",
        "product_deal": f"{count} related posts mention product availability, deals or affiliate promotion.",
        "fulfillment_risk": f"{count} related posts discuss refund, return, delivery or after-sales issues.",
        "trust_safety": f"{count} related posts mention trust, safety or authenticity concerns.",
        "competitor_comparison": f"{count} related posts compare Joybuy/JD with other shopping platforms.",
        "channel_activity": f"{count} related posts discuss channel, partner or campaign activity.",
        "company_market": f"{count} related posts discuss corporate, market or strategy context.",
        "regulatory": f"{count} related posts discuss regulatory review, acquisition scrutiny or market-access risk.",
        "general_observation": f"{count} related posts discuss Joybuy/JD overseas shopping context.",
    }
    return summaries.get(topic, summaries["general_observation"])


def summary_zh_for_topic(topic: str, posts: list[dict[str, Any]]) -> str:
    summaries = {
        "positive_experience": "相关讨论体现价格、配送或购物体验上的正向口碑。",
        "product_deal": "相关讨论集中在商品上架、优惠导购或库存信息。",
        "fulfillment_risk": "相关讨论涉及退款、退货、配送或售后体验风险。",
        "trust_safety": "相关讨论涉及信任、安全、真假或隐私相关担忧。",
        "competitor_comparison": "相关讨论把主品牌与其他购物平台进行价格、配送或品类对比。",
        "channel_activity": "相关讨论涉及渠道合作、站点更新、直播活动或市场推广。",
        "company_market": "相关讨论涉及公司、资本市场、战略或行业报告背景。",
        "regulatory": "相关讨论涉及 JD.com 在海外市场的监管审查、并购交易或市场准入风险。",
        "general_observation": "相关讨论涉及 Joybuy/JD 海外购物的一般体验和认知问题。",
    }
    return summaries.get(topic, summaries["general_observation"])


def risk_types_for_topic(topic: str) -> list[str]:
    mapping = {
        "fulfillment_risk": ["fulfillment", "after_sales", "delivery"],
        "trust_safety": ["brand_trust", "safety"],
        "regulatory": ["regulatory", "market_access", "acquisition"],
    }
    return mapping.get(topic, [])


def opportunity_types_for_topic(topic: str) -> list[str]:
    mapping = {
        "positive_experience": ["positive_value", "delivery_strength"],
        "product_deal": ["product_interest", "promotion"],
        "competitor_comparison": ["competitive_position"],
        "channel_activity": ["channel_expansion"],
        "company_market": ["corporate_context"],
    }
    if topic in mapping:
        return mapping[topic]
    return []
