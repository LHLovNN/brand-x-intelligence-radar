#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sync_dt_digests import (
    clean_tg_markdown_links,
    merge_structured_tg_media,
    multiline_text,
    strip_repeated_tg_title,
    strip_tg_channel_recommendations,
    structured_tg_item,
    tg_item_filter_reason,
)


def main() -> None:
    raw_summary = "第一段  \n\n第二段\n  第三段"
    assert multiline_text(raw_summary) == "第一段\n\n第二段\n第三段"
    assert strip_repeated_tg_title("第一段", "第一段\n\n第二段") == "第二段"
    assert strip_repeated_tg_title("标题", "第一段\n\n第二段") == "第一段\n\n第二段"
    zaihua_tail = (
        "正文\n\n"
        "[Theregister](https://www.theregister.com/off-prem/2026/08/25/example)\n\n"
        "🌸 [在花频道](http://t.me/ZaiHuaPd) · [茶馆水群](https://t.me/zaihuachat) · [投稿通道](http://t.me/ZaiHuabot)"
    )
    stripped_tail = strip_tg_channel_recommendations(zaihua_tail)
    assert "在花频道" not in stripped_tail
    assert "茶馆水群" not in stripped_tail
    assert "投稿通道" not in stripped_tail
    assert clean_tg_markdown_links(stripped_tail).endswith("Theregister")

    structured = {
        "kind": "tg",
        "sections": [
            {
                "items": [
                    {
                        "id": "aigc1024-100",
                        "message_id": "100",
                        "channel": "aigc1024",
                        "url": "https://t.me/aigc1024/100",
                        "title": "第一段",
                        "summary": raw_summary,
                    }
                ]
            }
        ],
    }
    html_sections = [
        {
            "title": "TG 频道精选",
            "items": [
                {
                    "id": "aigc1024-100",
                    "title": "第一段",
                    "summary": "第一段 第二段 第三段",
                    "url": "https://t.me/aigc1024/100",
                }
            ],
        }
    ]
    merged = merge_structured_tg_media(html_sections, structured, "https://codew1028.github.io/dt")
    assert merged[0]["items"][0]["summary"] == "第二段\n第三段"

    normalized = structured_tg_item(structured["sections"][0]["items"][0], "https://codew1028.github.io/dt")
    assert normalized["summary"] == "第二段\n第三段"

    structured_tg_link = structured_tg_item({
        "id": "zaihuapd-43388",
        "message_id": "43388",
        "channel": "zaihuapd",
        "url": "https://t.me/zaihuapd/43388",
        "title": "SpaceX 计划明年将英伟达 Vera Rubin NVL72 送入太空",
        "summary": zaihua_tail,
    }, "https://codew1028.github.io/dt")
    assert "https://www.theregister.com" not in structured_tg_link["summary"]
    assert "Theregister" in structured_tg_link["summary"]
    assert "在花频道" not in structured_tg_link["summary"]

    assert tg_item_filter_reason({"title": "Claude 挂了？", "summary": "Claude 挂了？"}) == "short_status_chatter"
    assert tg_item_filter_reason({"title": "Claude 挂了？", "summary": "Claude 恢复计划和替代方案整理如下"}) is None
    print("Diting sync tests passed.")


if __name__ == "__main__":
    main()
