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
    prepare_context_rows,
    should_fetch_context,
)


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
