#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.sync_dt_digests import (
    clean_tg_markdown_links,
    details_to_sync,
    merge_targeted_digest_entries,
    merge_structured_tg_media,
    parse_date_filters,
    multiline_text,
    strip_repeated_tg_title,
    strip_tg_channel_recommendations,
    structured_tg_item,
    tg_item_filter_reason,
)


def main() -> None:
    assert parse_date_filters(["2026-08-30,2026-08-29", "2026-08-30"]) == ["2026-08-30", "2026-08-29"]

    digest_entries = [
        {"kind": "tg", "date": "2026-08-31", "item_count": 38},
        {"kind": "ai", "date": "2026-08-31", "item_count": 7},
        {"kind": "tg", "date": "2026-08-30", "item_count": 55},
        {"kind": "tg", "date": "2026-08-29", "item_count": 68},
    ]
    selected = details_to_sync(digest_entries, 60, ["tg"], ["2026-08-30", "2026-08-29"])
    assert [entry["date"] for entry in selected] == ["2026-08-30", "2026-08-29"]

    merged_entries = merge_targeted_digest_entries(
        {
            "items": [
                {"kind": "ai", "date": "2026-08-30", "item_count": 6},
                {"kind": "tg", "date": "2026-08-28", "item_count": 32, "filtered_count": 1},
            ]
        },
        selected,
    )
    assert [entry["date"] for entry in merged_entries if entry["kind"] == "tg"] == [
        "2026-08-30",
        "2026-08-29",
        "2026-08-28",
    ]
    assert not any(entry["date"] == "2026-08-31" for entry in merged_entries)
    assert next(entry for entry in merged_entries if entry["date"] == "2026-08-28")["filtered_count"] == 1

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
    assert strip_tg_channel_recommendations("正文\n@aigc1024") == "正文"
    assert strip_tg_channel_recommendations("正文\n\n互联网从业者专属\n@https1024") == "正文"

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

    structured_tg_bare_handle = structured_tg_item({
        "id": "aigc1024-23609",
        "message_id": "23609",
        "channel": "aigc1024",
        "url": "https://t.me/aigc1024/23609",
        "title": "豆包工作",
        "summary": "豆包工作\n\n这里领会员 doubao.com/work\n@aigc1024",
    }, "https://codew1028.github.io/dt")
    assert "@aigc1024" not in structured_tg_bare_handle["summary"]
    assert "这里领会员" in structured_tg_bare_handle["summary"]

    structured_tg_promo_handle = structured_tg_item({
        "id": "inside1024-83758",
        "message_id": "83758",
        "channel": "inside1024",
        "url": "https://t.me/inside1024/83758",
        "title": "年轻人变专家",
        "summary": "年轻人变专家\n\n互联网从业者专属\n@https1024",
    }, "https://codew1028.github.io/dt")
    assert not structured_tg_promo_handle.get("summary")

    zero_byte_reply = structured_tg_item({
        "id": "zaihuapd-43376",
        "message_id": "43376",
        "channel": "zaihuapd",
        "url": "https://t.me/zaihuapd/43376",
        "title": "评论媒体测试",
        "summary": "评论媒体测试\n\n正文",
        "reply_count": 1,
        "replies_fetched": 1,
        "replies": [
            {
                "id": "411144",
                "time": "09:50",
                "sender_name": "匿名",
                "media": [
                    {
                        "type": "video",
                        "publish_status": "published",
                        "url": "assets/tg-media/2026-08-26/comments/c-411144-1.mp4",
                        "size_bytes": 0,
                    }
                ],
            }
        ],
    }, "https://codew1028.github.io/dt")
    assert zero_byte_reply.get("replies_visible") == 0
    assert not zero_byte_reply.get("replies")

    assert tg_item_filter_reason({
        "title": "最新AI爆剧",
        "summary": "谁还没冲！景甜被操到失禁喷水装死，骚穴却夹得更紧流水不停……",
    }) == "low_value_adult"
    assert tg_item_filter_reason({"title": "Claude 挂了？", "summary": "Claude 挂了？"}) == "short_status_chatter"
    assert tg_item_filter_reason({"title": "Claude 挂了？", "summary": "Claude 恢复计划和替代方案整理如下"}) is None
    print("Diting sync tests passed.")


if __name__ == "__main__":
    main()
