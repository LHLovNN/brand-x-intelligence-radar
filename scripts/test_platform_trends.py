#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.platform_trends import (
    canonical_platform_tag,
    collection_status,
    public_platform_collection_status,
    score_platform_post,
)


def main() -> None:
    assert canonical_platform_tag("变现路径") == "变现"
    assert canonical_platform_tag("商单") == "变现"
    assert canonical_platform_tag("带货") == "变现"
    assert canonical_platform_tag("笔记") == "爆文与内容结构"
    assert canonical_platform_tag("涨粉") == "账号冷启动"

    platform = {
        "aliases": ["小红书"],
        "intent_terms": ["变现", "商单", "带货", "流量", "引流", "涨粉"],
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

    adult_noise = {
        "clean_text": "冷知识：中国约炮平台流量最高：Boss直聘 > 小红书 > 58同城",
        "links": [],
        "metrics": {"likes": 17, "views": 1478},
        "author_followers": 1000,
    }
    adult_noise_decision = score_platform_post(adult_noise, platform)
    assert not adult_noise_decision["accepted"], "low-value adult jokes should not enter platform trend collection"

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

    status = collection_status(
        [item],
        candidates_seen=80,
        max_items=20,
        max_candidates=200,
        warnings=["TwitterAPI.io request budget exhausted: 12/12 requests used."],
    )
    assert status["status"] == "partial"
    public_status = public_platform_collection_status(status)
    assert public_status["warnings"] == ["平台流变采集达到本次保护阈值，已保留已取得内容。"]
    assert "TwitterAPI.io" not in public_status["warnings"][0]
    print("Platform trend tag tests passed.")


if __name__ == "__main__":
    main()
