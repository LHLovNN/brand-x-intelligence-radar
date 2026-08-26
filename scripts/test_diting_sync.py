#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sync_dt_digests import (
    merge_structured_tg_media,
    multiline_text,
    strip_repeated_tg_title,
    structured_tg_item,
    tg_item_filter_reason,
)


def main() -> None:
    raw_summary = "第一段  \n\n第二段\n  第三段"
    assert multiline_text(raw_summary) == "第一段\n\n第二段\n第三段"
    assert strip_repeated_tg_title("第一段", "第一段\n\n第二段") == "第二段"
    assert strip_repeated_tg_title("标题", "第一段\n\n第二段") == "第一段\n\n第二段"

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

    assert tg_item_filter_reason({"title": "Claude 挂了？", "summary": "Claude 挂了？"}) == "short_status_chatter"
    assert tg_item_filter_reason({"title": "Claude 挂了？", "summary": "Claude 恢复计划和替代方案整理如下"}) is None
    print("Diting sync tests passed.")


if __name__ == "__main__":
    main()
