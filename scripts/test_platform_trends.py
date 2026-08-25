#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.platform_trends import canonical_platform_tag, score_platform_post


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
    print("Platform trend tag tests passed.")


if __name__ == "__main__":
    main()
