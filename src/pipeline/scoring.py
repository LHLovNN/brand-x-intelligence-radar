from typing import Any


def _clamp(value: float) -> int:
    return max(0, min(100, round(value)))


def _impact_score(cluster: dict[str, Any]) -> int:
    metrics = cluster["metrics"]
    interactions = metrics["public_interactions"]
    followers = metrics["max_author_followers"]
    views = metrics["total_views"] or 0
    score = 25 + min(30, interactions / 12) + min(25, followers / 3000) + min(20, views / 6000)
    return _clamp(score)


def _future_score(cluster: dict[str, Any]) -> int:
    topic = cluster["topic"]
    metrics = cluster["metrics"]
    quote_weight = min(24, metrics["total_quotes"] * 1.8)
    follow_weight = min(24, metrics["max_author_followers"] / 2500)
    topic_weight = {
        "fulfillment_risk": 18,
        "trust_safety": 16,
        "regulatory": 20,
        "positive_experience": 12,
        "product_deal": 8,
        "competitor_comparison": 13,
        "channel_activity": 10,
        "company_market": 9,
        "price_opportunity": 8,
        "general": 7,
        "general_observation": 6,
    }.get(topic, 6)
    density_weight = min(18, cluster["post_count"] * 4)
    return _clamp(28 + quote_weight + follow_weight + topic_weight + density_weight)


def _credibility_score(cluster: dict[str, Any]) -> int:
    posts = cluster["posts"]
    evidence = 0
    if cluster["post_count"] >= 2:
        evidence += 18
    if any(post["author"]["followers"] > 10000 for post in posts):
        evidence += 10
    if any("screenshot" in post["clean_text"].lower() or "tracking" in post["clean_text"].lower() for post in posts):
        evidence += 12
    if any(post.get("brand_context_evidence") for post in posts):
        evidence += 16
    if cluster["topic"] in {"refund", "delivery", "customer_service", "fulfillment_risk", "trust_safety", "regulatory"}:
        evidence += 8
    return _clamp(42 + evidence)


def _brand_relevance(cluster: dict[str, Any]) -> int:
    posts = cluster["posts"]
    direct = sum(1 for post in posts if any(term in ["joybuy", "jd.com", "京东"] for term in post["matched_brand_terms"]))
    contextual = sum(1 for post in posts if post.get("brand_context_evidence"))
    ambiguous = sum(1 for post in posts if post.get("brand_ambiguity"))
    return _clamp(50 + direct * 12 + contextual * 8 - ambiguous * 25)


def _intensity(cluster: dict[str, Any]) -> int:
    base = {
        "fulfillment_risk": 78,
        "trust_safety": 74,
        "regulatory": 82,
        "positive_experience": 62,
        "product_deal": 52,
        "competitor_comparison": 60,
        "channel_activity": 54,
        "company_market": 48,
        "price_opportunity": 58,
        "general": 45,
        "general_observation": 40,
    }.get(cluster["topic"], 45)
    if cluster["metrics"]["max_author_followers"] > 50000:
        base += 8
    return _clamp(base)


def _business_impact(cluster: dict[str, Any]) -> int:
    return _clamp(
        {
            "fulfillment_risk": 86,
            "trust_safety": 82,
            "regulatory": 90,
            "positive_experience": 60,
            "product_deal": 50,
            "competitor_comparison": 64,
            "channel_activity": 58,
            "company_market": 56,
            "price_opportunity": 52,
            "general": 48,
            "general_observation": 42,
        }.get(cluster["topic"], 48)
    )


def _urgency(cluster: dict[str, Any], current_impact: int, future_potential: int) -> int:
    topic_base = {
        "fulfillment_risk": 72,
        "trust_safety": 68,
        "regulatory": 78,
        "positive_experience": 42,
        "product_deal": 35,
        "competitor_comparison": 44,
        "channel_activity": 38,
        "company_market": 34,
        "price_opportunity": 38,
        "general": 34,
        "general_observation": 30,
    }.get(cluster["topic"], 34)
    return _clamp(topic_base + max(current_impact, future_potential) * 0.18)


def score_clusters(clusters: list[dict[str, Any]], scoring_config: dict[str, Any]) -> list[dict[str, Any]]:
    weights = scoring_config["ips_weights"]
    thresholds = scoring_config["risk_thresholds"]
    for cluster in clusters:
        brand_relevance = _brand_relevance(cluster)
        intensity = _intensity(cluster)
        current_impact = _impact_score(cluster)
        future_potential = _future_score(cluster)
        credibility = _credibility_score(cluster)
        business_impact = _business_impact(cluster)
        urgency = _urgency(cluster, current_impact, future_potential)

        ips = (
            brand_relevance * weights["brand_relevance"]
            + intensity * weights["risk_or_opportunity_intensity"]
            + current_impact * weights["current_impact"]
            + future_potential * weights["future_potential"]
            + credibility * weights["credibility"]
            + business_impact * weights["business_impact"]
            + urgency * weights["urgency"]
        )
        if cluster["topic"] in {"refund", "delivery", "fulfillment_risk"} and future_potential >= 80:
            ips += 3
        ips = _clamp(ips)

        level = "low"
        if ips >= thresholds["urgent"]:
            level = "urgent"
        elif ips >= thresholds["high"]:
            level = "high"
        elif ips >= thresholds["medium"]:
            level = "medium"

        sentiment = sentiment_for_topic(cluster["topic"])
        recommended_action = action_for(level, cluster["topic"], credibility, current_impact, future_potential)
        special_flags = []
        if credibility < 65 and max(current_impact, future_potential) > 75:
            special_flags.append("rumor_or_unverified_spread_risk")
        if future_potential >= 80:
            special_flags.append("potential_viral")
        if cluster["metrics"]["max_author_followers"] >= 50000:
            special_flags.append("high_influence_account")

        cluster["score"] = {
            "ips": ips,
            "level": level,
            "brand_relevance": brand_relevance,
            "risk_or_opportunity_intensity": intensity,
            "current_impact": current_impact,
            "future_potential": future_potential,
            "credibility": credibility,
            "business_impact": business_impact,
            "urgency": urgency,
            "sentiment": sentiment,
            "confidence": 0.81,
            "recommended_action": recommended_action,
            "risk_labels": cluster["risk_types"],
            "opportunity_labels": cluster["opportunity_types"],
            "special_flags": special_flags,
            "explanation": explain_score(cluster, ips, credibility, current_impact, future_potential),
        }
    return sorted(clusters, key=lambda item: item["score"]["ips"], reverse=True)


def action_for(level: str, topic: str, credibility: int, current_impact: int, future_potential: int) -> str:
    if topic == "regulatory":
        return "管理层同步" if level in {"urgent", "high", "medium"} else "人工核查"
    if topic in {"positive_experience", "price_opportunity", "product_deal"}:
        return "传播机会"
    if topic == "competitor_comparison":
        return "竞品对照观察"
    if topic == "channel_activity":
        return "渠道观察"
    if topic == "company_market":
        return "背景观察"
    if topic == "general_observation":
        return "观察"
    if level == "urgent":
        return "高层同步"
    if level == "high":
        return "人工核查" if credibility < 70 else "PR 准备回应"
    if future_potential > 78:
        return "观察"
    if topic == "price_opportunity":
        return "传播机会"
    return "观察"


def sentiment_for_topic(topic: str) -> str:
    if topic in {"positive_experience", "price_opportunity", "product_deal"}:
        return "positive"
    if topic in {"fulfillment_risk", "trust_safety", "regulatory", "refund", "delivery", "customer_service", "quality"}:
        return "negative"
    if topic in {"competitor_comparison", "channel_activity", "company_market", "general_observation", "general"}:
        return "neutral"
    return "neutral"


def explain_score(cluster: dict[str, Any], ips: int, credibility: int, current_impact: int, future_potential: int) -> str:
    topic = cluster["topic"]
    if topic in {"refund", "fulfillment_risk"}:
        return f"退款议题直接影响信任与支付体验，当前影响力 {current_impact}，未来发酵潜力 {future_potential}，可信度 {credibility}。"
    if topic == "delivery":
        return f"物流与追踪议题容易形成集中投诉，当前影响力 {current_impact}，未来发酵潜力 {future_potential}。"
    if topic == "customer_service":
        return f"客服与退货响应涉及售后体验，建议观察是否出现更多相似投诉。综合优先级 {ips}。"
    if topic == "regulatory":
        return f"监管与并购审查影响海外市场准入和品牌信任，当前影响力 {current_impact}，可信度 {credibility}，建议纳入管理层视野。"
    if topic in {"price_opportunity", "positive_experience"}:
        return f"该情报偏正向机会，体现价格、配送或促销优势，可用于观察传播借势。综合优先级 {ips}。"
    if topic == "product_deal":
        return f"商品、优惠或库存信息可反映自然需求与转化入口，综合优先级 {ips}。"
    if topic == "competitor_comparison":
        return f"用户将主品牌与其他平台对照，适合观察价格、配送或品类竞争位置。综合优先级 {ips}。"
    if topic == "channel_activity":
        return f"渠道、合作或活动信息体现市场扩展动向，建议作为背景信号观察。综合优先级 {ips}。"
    if topic == "company_market":
        return f"公司、资本市场或战略背景信息对品牌心智有间接影响，当前综合优先级为 {ips}。"
    if topic == "trust_safety":
        return f"信任、安全或真实性讨论可能影响品牌可信度，当前影响力 {current_impact}，未来发酵潜力 {future_potential}。"
    return f"该情报与 Joybuy/JD 海外购物相关，当前综合优先级为 {ips}。"
