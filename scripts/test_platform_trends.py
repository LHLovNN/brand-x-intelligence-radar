#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.platform_trends import (
    build_platform_queries,
    canonical_platform_tag,
    clean_post_text,
    collection_status,
    platform_query_candidate_limit,
    public_platform_collection_status,
    score_platform_post,
)


def main() -> None:
    assert canonical_platform_tag("变现路径") == "变现"
    assert canonical_platform_tag("商单") == "变现"
    assert canonical_platform_tag("带货") == "变现"
    assert canonical_platform_tag("笔记") == "爆文与内容结构"
    assert canonical_platform_tag("涨粉") == "账号冷启动"
    assert canonical_platform_tag("限流") == "风控对抗"
    assert canonical_platform_tag("平台规则") == "平台规则"
    assert canonical_platform_tag("账号矩阵") == "矩阵"

    media_text = clean_post_text(
        {
            "text": "图片用 Image2 等模型生成， https://t.co/yqRoyVQuOY",
            "media": [{"url": "https://t.co/yqRoyVQuOY", "type": "photo"}],
        }
    )
    assert media_text == "图片用 Image2 等模型生成，", "media placeholder URLs should not appear in XHS card text"

    platform = {
        "aliases": ["小红书"],
        "intent_terms": ["变现", "商单", "带货", "流量", "引流", "涨粉", "风控", "平台规则", "账号获取", "矩阵"],
        "exclude_terms": [],
    }
    item = {
        "clean_text": "小红书起号后怎么做流量和变现？1. 先用笔记测选题；2. 再用商单和带货验证收入；3. 最后引流到私域复购。",
        "links": [],
        "metrics": {"likes": 80, "views": 8000},
        "author_followers": 2000,
    }
    decision = score_platform_post(item, platform)
    assert decision["accepted"], "strong platform trend methods should be accepted"
    tags = decision["item"]["tags"]
    assert "变现" in tags
    assert "变现路径" not in tags
    assert "商单" not in tags
    assert "带货" not in tags
    assert "涨粉" not in tags
    assert len(tags) == len(set(tags)), "canonical tags should be deduped"

    risk_control_item = {
        "clean_text": "小红书账号矩阵起号时，先准备老号和白号池，按平台规则控制发布节奏，避免审核限流。这里是完整风控对抗流程：1. 分层养号；2. 批量测试笔记；3. 复盘违规原因。",
        "links": [],
        "metrics": {"likes": 24, "views": 1200},
        "author_followers": 1800,
    }
    risk_control_decision = score_platform_post(risk_control_item, platform)
    assert risk_control_decision["accepted"], "risk-control and matrix playbooks should enter platform trend collection"
    risk_tags = risk_control_decision["item"]["tags"]
    assert "风控对抗" in risk_tags
    assert "平台规则" in risk_tags
    assert "矩阵" in risk_tags

    adult_noise = {
        "clean_text": "冷知识：中国约炮平台流量最高：Boss直聘 > 小红书 > 58同城",
        "links": [],
        "metrics": {"likes": 17, "views": 1478},
        "author_followers": 1000,
    }
    adult_noise_decision = score_platform_post(adult_noise, platform)
    assert not adult_noise_decision["accepted"], "low-value adult jokes should not enter platform trend collection"

    adult_rule_evasion = {
        "clean_text": "玩的就是反差，身体已经软成一滩水。小红书两次违规真发不出，只能推特发了，开脱上供 Luo照 锐评一下不许说我黑。",
        "links": [],
        "metrics": {"likes": 28, "views": 1800},
        "author_followers": 1000,
    }
    adult_rule_evasion_decision = score_platform_post(adult_rule_evasion, platform)
    assert not adult_rule_evasion_decision["accepted"], "adult rule-evasion spam should not enter platform trend collection"

    adult_platform_joke = {
        "clean_text": "小红书是不是拖延审核员工资了，我还以为打开了小黄书。",
        "links": [],
        "metrics": {"likes": 32, "views": 2200},
        "author_followers": 1000,
    }
    adult_platform_joke_decision = score_platform_post(adult_platform_joke, platform)
    assert not adult_platform_joke_decision["accepted"], "adult platform jokes should not enter platform trend collection"

    short_reaction_link = {
        "clean_text": "卧槽，小红书变现能力这么强的嘛！！ https://t.co/example",
        "links": ["https://example.com"],
        "metrics": {"likes": 61, "views": 43322, "replies": 116},
        "author_followers": 1000,
    }
    short_reaction_decision = score_platform_post(short_reaction_link, platform)
    assert not short_reaction_decision["accepted"], "short reaction links should not enter platform trend collection"

    platform_news = {
        "clean_text": "杜撰“小红书上市失败”贴文，被警方行拘。涉企网络谣言案件通报。",
        "links": [],
        "metrics": {"likes": 74, "views": 21787, "replies": 16},
        "author_followers": 1000,
    }
    assert not score_platform_post(platform_news, platform)["accepted"], "platform news should not enter method collection"

    off_topic_namedrop = {
        "clean_text": "我简单讲讲这个人和特斯拉中国的恩怨：他借着小红书上一个账号的所谓人去楼空来黑特斯拉，最后把FSD相关谣言热点引爆。",
        "links": [],
        "metrics": {"likes": 52, "views": 21323, "replies": 22},
        "author_followers": 1000,
    }
    assert not score_platform_post(off_topic_namedrop, platform)["accepted"], "keyword-only namedrops should not enter method collection"

    off_topic_comparison = {
        "clean_text": "Tutti 商单收益比做闲鱼和小红书投入产出自由，赶紧来注册加入。",
        "links": [],
        "metrics": {"likes": 57, "views": 5543, "replies": 2},
        "author_followers": 1000,
    }
    assert not score_platform_post(off_topic_comparison, platform)["accepted"], "off-topic platform comparisons should not enter collection"

    animal_cruelty_report = {
        "clean_text": "如果你在网络上发现虐待动物的视频，请不要沉默。保存证据后向微博、小红书、QQ、抖音等平台按平台规则举报，再通报执法部门和动物保护组织。STOP ANIMAL CRUELTY.",
        "links": [],
        "metrics": {"likes": 116, "views": 1962, "replies": 0},
        "author_followers": 1000,
    }
    assert not score_platform_post(animal_cruelty_report, platform)["accepted"], "animal-cruelty reporting advocacy is not XHS growth methodology"

    status = collection_status(
        [item],
        candidates_seen=80,
        max_items=None,
        max_candidates=400,
        min_views=300,
        warnings=[],
        source_request_limit_reached=True,
    )
    assert status["status"] == "complete"
    assert status["completion_reason"] == "source_request_limit_reached"
    public_status = public_platform_collection_status(status)
    assert public_status["warnings"] == []

    budget_status = collection_status(
        [item],
        candidates_seen=80,
        max_items=None,
        max_candidates=400,
        min_views=300,
        warnings=["TwitterAPI.io request budget exhausted: 12/12 requests used."],
        source_request_limit_reached=True,
    )
    assert budget_status["status"] == "partial"
    budget_public_status = public_platform_collection_status(budget_status)
    assert budget_public_status["warnings"] == [], "planned source request limit should not create a public warning"

    split_platform = {
        "aliases": ["小红书", "rednote"],
        "query_groups": [
            {"intent_terms": ["养号", "起号", "涨粉"]},
            {"intent_terms": ["变现", "商单", "带货"]},
        ],
        "exclude_terms": ["coupon code"],
    }
    queries = build_platform_queries(split_platform)
    assert len(queries) == 2, "platform trend queries should split into configured topic groups"
    assert all(len(query) < 180 for query in queries), "split platform trend queries should stay short enough for stable Top search"
    assert platform_query_candidate_limit(400, len(queries)) == 200
    assert platform_query_candidate_limit(400, 5) == 80

    zero_status = collection_status([], candidates_seen=0, max_items=None, max_candidates=400, warnings=["Platform trend source returned no candidates for all configured queries."])
    zero_public_status = public_platform_collection_status(zero_status)
    assert zero_status["status"] == "partial"
    assert zero_public_status["warnings"] == ["平台流变未从数据源取到候选内容，请检查查询配置或稍后补跑。"]
    print("Platform trend tag tests passed.")


if __name__ == "__main__":
    main()
