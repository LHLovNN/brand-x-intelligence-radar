#!/usr/bin/env python3
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.translation import (
    JoyBuilderTranslationService,
    NoopTranslationService,
    SampleDictionaryTranslationService,
    TranslationRequestError,
    TranslationService,
    apply_translations,
    build_translation_service,
    needs_translation,
    response_output_text,
)


class FailingTranslationService(TranslationService):
    provider_name = "failing_test_provider"
    configured = True

    def translate_batch(self, items: list[dict[str, str]]) -> dict[str, str]:
        raise RuntimeError("simulated translation outage")


class TimeoutTranslationService(TranslationService):
    provider_name = "timeout_test_provider"
    configured = True

    def translate_batch(self, items: list[dict[str, str]]) -> dict[str, str]:
        raise socket.timeout("simulated timeout")


class SplittingJoyBuilderTranslationService(JoyBuilderTranslationService):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", batch_size=4, retry_attempts=0, timeout_seconds=1)
        self.calls: list[list[str]] = []

    def _translate_chunk(self, items: list[dict[str, str]]) -> dict[str, str]:
        ids = [item["id"] for item in items]
        self.calls.append(ids)
        if len(items) > 1:
            raise TranslationRequestError("simulated batch timeout", timeout=True)
        return {items[0]["id"]: f"中文译文 {items[0]['id']}"}


class AlwaysFailingJoyBuilderTranslationService(JoyBuilderTranslationService):
    def __init__(self) -> None:
        super().__init__(api_key="test-key", batch_size=1, retry_attempts=0, timeout_seconds=1)

    def _translate_chunk(self, items: list[dict[str, str]]) -> dict[str, str]:
        raise TranslationRequestError("simulated single-item timeout", timeout=True)


class NonChineseTranslationService(TranslationService):
    provider_name = "non_chinese_test_provider"
    configured = True

    def translate_batch(self, items: list[dict[str, str]]) -> dict[str, str]:
        return {item["id"]: item["text"] for item in items}


def test_sample_dictionary_translation() -> None:
    posts = [
        {
            "post_id": "1",
            "language": "en",
            "clean_text": "Still waiting for my Joybuy refund after 12 days. Support keeps saying the case is under review.",
        },
        {
            "post_id": "2",
            "language": "zh",
            "clean_text": "京东海外 Joybuy 的客服回复很慢。",
        },
    ]
    report = apply_translations(posts, SampleDictionaryTranslationService())
    assert report["missing_count"] == 0
    assert posts[0]["translation_status"] == "sample_dictionary"
    assert "退款" in posts[0]["translation_zh"]
    assert posts[1]["translation_status"] == "source_chinese"
    assert posts[1]["translation_zh"] == posts[1]["clean_text"]


def test_translation_need_detection() -> None:
    assert needs_translation({"language": "fr", "clean_text": "Le remboursement Joybuy est lent."})
    assert not needs_translation({"language": "zh", "clean_text": "Joybuy 退款很慢。"})
    assert not needs_translation({"language": "und", "clean_text": "Joybuy 退款很慢。"})
    assert needs_translation(
        {
            "language": "ja",
            "clean_text": "Joybuyって今日配達済みになってるけど、アパート周り色々見たけど無し！",
        }
    )
    assert needs_translation({"language": "und", "clean_text": "I tried 京东 Joybuy refund and support is slow."})
    assert not needs_translation({"language": "und", "clean_text": "京东海外 Joybuy 的客服回复很慢，退款也还没到账。"})


def test_joybuilder_response_text_parsing() -> None:
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '[{"id":"0","translation_zh":"Joybuy 退款很慢。"}]',
                        }
                    ]
                }
            }
        ]
    }
    assert "translation_zh" in response_output_text(payload)


def test_joybuilder_request_body_uses_responses_input() -> None:
    service = JoyBuilderTranslationService(api_key="test-key", batch_size=1)
    body = service._build_request_body(
        [
            {
                "id": "0",
                "language": "fr",
                "text": "Le remboursement Joybuy est lent.",
            }
        ]
    )
    assert body["model"] == "GPT-5.5"
    assert "input" in body
    assert "contents" not in body
    assert "Joybuy" in body["input"]
    assert "translation_zh" in body["input"]


def test_translation_failure_falls_back_to_original() -> None:
    posts = [
        {
            "post_id": "fallback-1",
            "language": "fr",
            "clean_text": "Le remboursement Joybuy est toujours en attente.",
        }
    ]
    report = apply_translations(posts, FailingTranslationService())
    assert report["missing_count"] == 1
    assert report["fallback_original_count"] == 1
    assert posts[0]["translation_status"] == "error"
    assert posts[0]["translation_zh"] == posts[0]["clean_text"]
    assert "simulated translation outage" in posts[0]["translation_error"]


def test_translation_timeout_falls_back_to_original() -> None:
    posts = [
        {
            "post_id": "timeout-1",
            "language": "en",
            "clean_text": "Joybuy refund is still pending.",
        }
    ]
    report = apply_translations(posts, TimeoutTranslationService())
    assert report["missing_count"] == 1
    assert report["fallback_original_count"] == 1
    assert posts[0]["translation_status"] == "error"
    assert posts[0]["translation_zh"] == posts[0]["clean_text"]
    assert "simulated timeout" in posts[0]["translation_error"]


def test_joybuilder_timeout_splits_batch_and_keeps_successful_translations() -> None:
    posts = [
        {
            "post_id": f"split-{index}",
            "language": "en",
            "clean_text": f"Joybuy refund post {index}.",
        }
        for index in range(4)
    ]
    service = SplittingJoyBuilderTranslationService()
    report = apply_translations(posts, service)

    assert report["missing_count"] == 0
    assert report["counts"]["translated"] == 4
    assert service.calls[0] == ["0", "1", "2", "3"]
    assert ["0"] in service.calls
    assert ["3"] in service.calls
    assert all(post["translation_status"] == "translated" for post in posts)
    assert posts[2]["translation_zh"] == "中文译文 2"


def test_joybuilder_single_item_failure_falls_back_to_original() -> None:
    posts = [
        {
            "post_id": "single-timeout-1",
            "language": "en",
            "clean_text": "Joybuy refund is still pending.",
        }
    ]
    report = apply_translations(posts, AlwaysFailingJoyBuilderTranslationService())

    assert report["missing_count"] == 1
    assert report["fallback_original_count"] == 1
    assert posts[0]["translation_status"] == "error"
    assert posts[0]["translation_zh"] == posts[0]["clean_text"]
    assert "single-item timeout" in posts[0]["translation_error"]


def test_missing_translation_config_falls_back_to_original() -> None:
    posts = [
        {
            "post_id": "fallback-2",
            "language": "de",
            "clean_text": "Joybuy Lieferung ist noch nicht angekommen.",
        }
    ]
    report = apply_translations(posts, NoopTranslationService())
    assert report["missing_count"] == 1
    assert report["fallback_original_count"] == 1
    assert posts[0]["translation_status"] == "missing"
    assert posts[0]["translation_zh"] == posts[0]["clean_text"]


def test_non_chinese_provider_output_is_not_accepted() -> None:
    posts = [
        {
            "post_id": "bad-provider-output",
            "language": "en",
            "clean_text": "Joybuy refund is still pending.",
        }
    ]
    report = apply_translations(posts, NonChineseTranslationService())
    assert report["missing_count"] == 1
    assert posts[0]["translation_status"] == "error"
    assert posts[0]["translation_zh"] == posts[0]["clean_text"]
    assert "non-Chinese" in posts[0]["translation_error"]


def test_default_real_provider_without_company_key_uses_noop_translation() -> None:
    original_provider = os.environ.pop("TRANSLATION_PROVIDER", None)
    original_key = os.environ.pop("JDCLOUD_GPT_API_KEY", None)
    try:
        service = build_translation_service("twitterapi_io")
        assert service.provider_name == "none"
    finally:
        if original_provider is not None:
            os.environ["TRANSLATION_PROVIDER"] = original_provider
        if original_key is not None:
            os.environ["JDCLOUD_GPT_API_KEY"] = original_key


if __name__ == "__main__":
    test_sample_dictionary_translation()
    test_translation_need_detection()
    test_joybuilder_response_text_parsing()
    test_joybuilder_request_body_uses_responses_input()
    test_translation_failure_falls_back_to_original()
    test_translation_timeout_falls_back_to_original()
    test_joybuilder_timeout_splits_batch_and_keeps_successful_translations()
    test_joybuilder_single_item_failure_falls_back_to_original()
    test_missing_translation_config_falls_back_to_original()
    test_non_chinese_provider_output_is_not_accepted()
    test_default_real_provider_without_company_key_uses_noop_translation()
    print("Translation tests passed.")
