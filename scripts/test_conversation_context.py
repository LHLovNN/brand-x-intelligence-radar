#!/usr/bin/env python3
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.conversation_context import (
    attach_conversation_contexts,
    build_context_for_post,
    context_item,
    dedupe_contextual_items_keep_earliest,
    dedupe_conversation_items_keep_earliest,
    filter_context_noise,
    prepare_context_rows,
    should_fetch_context,
)
from src.pipeline.dashboard_builder import public_conversation_context


def post(index: int, **overrides):
    item = {
        "post_id": str(index),
        "conversation_id": "conversation-1",
        "text": f"@source context post {index}",
        "clean_text": f"@source context post {index}",
        "translation_zh": f"上下文帖子 {index}",
        "created_at": f"2026-07-29T00:{index:02d}:00Z",
        "author_handle": f"user{index}",
        "author_followers": 10,
    }
    item.update(overrides)
    return item


def main() -> None:
    anchor = post(25, post_id="anchor", author_followers=1000)
    assert should_fetch_context(anchor, 0), "followers >= 1000 should trigger context when reply-shaped"
    assert should_fetch_context(post(1, conversation_id="other", post_id="1", text="plain text"), 60), "conversation_id != post_id with score >= 60 should trigger"
    assert not should_fetch_context(post(2, conversation_id="2", text="plain text", author_followers=999), 59), "low-value root-shaped post should not trigger"
    assert not should_fetch_context(
        post(3, brand="temu", metrics={"views": 499}, author_followers=1000),
        80,
    ), "competitor context should require at least 500 views"
    assert should_fetch_context(
        post(4, brand="temu", metrics={"views": 500}),
        80,
    ), "competitor context should be allowed once the 500-view threshold is met"
    assert should_fetch_context(
        post(5, brand="joybuy", metrics={"views": 100}, author_followers=1000),
        0,
    ), "primary context should not be gated by the competitor view threshold"

    deduped, removed = dedupe_conversation_items_keep_earliest(
        [
            post(8, post_id="later", conversation_id="thread-1", created_at="2026-07-29T00:08:00Z"),
            post(7, post_id="earlier", conversation_id="thread-1", created_at="2026-07-29T00:07:00Z"),
            post(9, post_id="standalone", conversation_id="standalone", created_at="2026-07-29T00:09:00Z"),
        ]
    )
    assert removed == 1, "duplicate conversation entries should be counted"
    assert [item["post_id"] for item in deduped] == ["earlier", "standalone"], "same conversation should keep the earliest collected post"

    contextual_deduped, contextual_removed = dedupe_contextual_items_keep_earliest(
        [
            {
                **post(8, post_id="later-root", conversation_id="later-root", created_at="2026-07-29T00:08:00Z"),
                "conversation_context": {"posts": [{"post_id": "earlier-root"}, {"post_id": "later-root"}]},
            },
            {
                **post(7, post_id="earlier-root", conversation_id="earlier-root", created_at="2026-07-29T00:07:00Z"),
                "conversation_context": {"posts": [{"post_id": "earlier-root"}]},
            },
        ]
    )
    assert contextual_removed == 1, "overlapping context windows should be deduped"
    assert [item["post_id"] for item in contextual_deduped] == ["earlier-root"], "overlapping context should keep the earliest post"

    clean_rows, filtered_noise = filter_context_noise(
        [
            post(6, text="@source 这个拆解角度挺有意思"),
            post(7, text="@source 应该没人比我玩的开了吧😃😖我福不黑不信你看"),
            post(8, text="@source 比她好看的没她骚比她骚的没她好看@spam"),
            post(9, text="@source 比我好看的没我骚🦑🌊比我骚的没我好看"),
            post(10, text="@source Cringe 只入身体🍬👑不入生活。", author_name="张可欣找炮友点主页", author_bio="真人认证隐私保护，附近的可加V"),
        ]
    )
    assert filtered_noise == 4, "obvious low-quality vulgar context replies should be filtered"
    assert [item["post_id"] for item in clean_rows] == ["6"], "normal context replies should stay visible"

    rows = [post(index) for index in range(50)]
    rows.insert(25, anchor)
    context = build_context_for_post(anchor, rows)
    assert context, "context should be built around anchor"
    assert len(context["posts"]) == 41, "context window should include 20 before + anchor + 20 after"
    assert context["posts"][20]["post_id"] == "anchor", "anchor should stay in the middle of the context window"
    assert len(context["summary_zh"]) <= 200, "context summary should stay under 200 chars"
    assert context["summary_status"] == "fallback", "local summary fallback should be explicit when no model service is available"

    prepared = prepare_context_rows(
        [
            post(
                99,
                text="Ici &gt;&gt; https://t.co/example",
                clean_text="",
                media=[{"mediaUrlHttps": "https://pbs.twimg.com/media/example.jpg", "type": "photo"}],
            )
        ],
        None,
    )
    media_context = build_context_for_post(prepared[0], prepared)
    assert media_context["posts"][0]["text"] == "Ici >> https://t.co/example", "context text should decode HTML entities"
    assert media_context["posts"][0]["media"][0]["media_url_https"] == "https://pbs.twimg.com/media/example.jpg", "context media should be normalized for the dashboard renderer"

    class ConfiguredSummaryService:
        configured = True
        api_key = "test-key"
        endpoint = "http://127.0.0.1:9/unreachable"
        model = "test-model"

    os.environ["CONVERSATION_CONTEXT_MODEL_SUMMARY"] = "0"
    try:
        local_summary_context = build_context_for_post(anchor, rows, ConfiguredSummaryService())
    finally:
        os.environ.pop("CONVERSATION_CONTEXT_MODEL_SUMMARY", None)
    assert local_summary_context["summary_status"] == "fallback", "model summary should be skippable for bounded backfills"
    assert len(local_summary_context["summary_zh"]) <= 200, "local context summary should stay under 200 chars"

    fallback_item = context_item(
        post(
            88,
            language="en",
            clean_text="This English context reply was not translated by the provider.",
            translation_zh="This English context reply was not translated by the provider.",
            translation_status="error",
        )
    )
    assert "该上下文帖" in fallback_item["translation_zh"], "context fallback should be Chinese"
    assert fallback_item["translation_status"] == "fallback_summary"

    public_context = public_conversation_context(
        {
            "conversation_context": {
                "posts": [
                    {
                        "post_id": "name-only",
                        "language": "en",
                        "text": "@aneefahaliyu38 Aneefa 😀",
                        "translation_zh": "@aneefahaliyu38 Aneefa 😀",
                        "translation_status": "translated",
                    }
                ]
            }
        }
    )
    assert "该上下文帖" in public_context["posts"][0]["translation_zh"], "public context output should sanitize cached non-Chinese translations"

    class ConversationContextSource:
        def __init__(self, rows):
            self.rows = rows
            self.conversation_calls = []

        def conversation_posts(self, conversation_id, start_time, end_time, limit=120):
            self.conversation_calls.append(conversation_id)
            return self.rows

    target = post(10, post_id="target", author_followers=1000, is_relevant=True)
    source = ConversationContextSource([post(9), target, post(11)])
    status = attach_conversation_contexts(
        [target],
        [{"score": {"ips": 0}, "post_ids": ["target"]}],
        source,
        None,
        "2026-07-29T00:00:00Z",
        "2026-07-30T00:00:00Z",
    )
    assert source.conversation_calls == ["conversation-1"], "context should be fetched by conversation_id"
    assert status["attached"] == 1, "multi-post conversation context should be attached"
    assert len(target["conversation_context"]["posts"]) == 3

    class ThreadContextSource(ConversationContextSource):
        def __init__(self, thread_rows, fallback_rows):
            super().__init__(fallback_rows)
            self.thread_rows = thread_rows
            self.thread_calls = []

        def thread_context_posts(self, post_id, start_time, end_time, limit=120):
            self.thread_calls.append(post_id)
            return self.thread_rows

    thread_target = post(20, post_id="thread-anchor", author_followers=1000, is_relevant=True)
    thread_source = ThreadContextSource(
        [
            post(18, post_id="thread-parent", created_at="2026-07-28T23:59:00Z", text="parent before report window"),
            thread_target,
            post(21, post_id="thread-after"),
        ],
        [thread_target],
    )
    thread_status = attach_conversation_contexts(
        [thread_target],
        [{"score": {"ips": 0}, "post_ids": ["thread-anchor"]}],
        thread_source,
        None,
        "2026-07-29T00:00:00Z",
        "2026-07-30T00:00:00Z",
    )
    assert thread_source.thread_calls == ["thread-anchor"], "thread context should be fetched by collected post id"
    assert thread_source.conversation_calls == [], "conversation search should not be used when thread context has neighbors"
    assert thread_status["attached"] == 1
    assert [item["post_id"] for item in thread_target["conversation_context"]["posts"]] == [
        "thread-parent",
        "thread-anchor",
        "thread-after",
    ]

    fallback_target = post(30, post_id="fallback-anchor", author_followers=1000, is_relevant=True)
    fallback_source = ThreadContextSource([fallback_target], [post(29, post_id="fallback-parent"), fallback_target])
    fallback_status = attach_conversation_contexts(
        [fallback_target],
        [{"score": {"ips": 0}, "post_ids": ["fallback-anchor"]}],
        fallback_source,
        None,
        "2026-07-29T00:00:00Z",
        "2026-07-30T00:00:00Z",
    )
    assert fallback_source.thread_calls == ["fallback-anchor"]
    assert fallback_source.conversation_calls == ["conversation-1"], "conversation search should backstop sparse thread context"
    assert fallback_status["attached"] == 1

    solo = post(12, post_id="solo", author_followers=1000, is_relevant=True)
    solo["conversation_context"] = {"posts": [{"post_id": "solo"}]}
    solo_source = ConversationContextSource([solo])
    solo_status = attach_conversation_contexts(
        [solo],
        [{"score": {"ips": 0}, "post_ids": ["solo"]}],
        solo_source,
        None,
        "2026-07-29T00:00:00Z",
        "2026-07-30T00:00:00Z",
    )
    assert solo_status["attached"] == 0, "anchor-only context should not be exposed as successful context"
    assert solo_status["unresolved"] == 1
    assert "conversation_context" not in solo
    print("Conversation context tests passed.")


if __name__ == "__main__":
    main()
