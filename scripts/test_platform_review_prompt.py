#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.translation import (  # noqa: E402
    PLATFORM_REVIEW_CONTENT_TYPES,
    PLATFORM_REVIEW_DOMAINS,
    JoyBuilderTranslationService,
    build_platform_review_prompt,
)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")


def test_platform_review_prompt_has_typed_acceptance_paths() -> None:
    prompt = build_platform_review_prompt()

    assert prompt == build_platform_review_prompt()
    for content_type in PLATFORM_REVIEW_CONTENT_TYPES:
        assert content_type in prompt
    assert "platform_relation" in prompt
    assert "specific_signal" in prompt
    assert "source_status=rumor" in prompt
    assert "案例不必写成系统教程" in prompt
    assert "多平台方法不要求提供小红书独有的机制或技术适配" in prompt
    assert "即使这些方法也适用于公众号、抖音或 X" in prompt
    assert "低俗色情和其他黑灰产内容，拒绝" in prompt
    assert "不能脱离 content_type 和 specific_signal 单独否决" in prompt
    for domain in PLATFORM_REVIEW_DOMAINS:
        assert domain in prompt


def test_platform_review_prompt_contains_regression_examples() -> None:
    prompt = build_platform_review_prompt()

    assert "选题、生产、发布、复盘工作流" in prompt
    assert "短视频提示词或分镜模板" in prompt
    assert "每天两更、具体内容形式" in prompt
    assert "涨粉互动和商单结果" in prompt
    assert "多平台方法不要求提供小红书独有的机制或技术适配" in prompt
    assert "小红书适合图文起步" in prompt
    assert "先用轻量图文验证内容与洞察" in prompt
    assert "对标账号和选择简单形式" in prompt
    assert "正常、合规的数字产品已经在小红书产生收入或订单" in prompt
    assert "生产该产品所需的提示词仓库" in prompt
    assert "通用生产工具不必具备小红书独有功能" in prompt
    assert "手写笔记持续成为爆款" in prompt
    assert "属于可验证的平台现象假设" in prompt
    assert "隔离海外身份账号与内地账号" in prompt
    assert "小红书数字产品" in prompt
    assert "case_lead" in prompt
    assert "收藏来源" in prompt


def test_platform_review_prompt_keeps_risk_vetoes() -> None:
    prompt = build_platform_review_prompt()

    for rejected_pattern in (
        "盗版或绝版资料售卖",
        "网盘拉新",
        "AI 代充",
        "付费打粉或评论",
        "规避平台规则的引流",
        "低俗色情",
    ):
        assert rejected_pattern in prompt
    assert "hard_risk=true 必须拒绝" in prompt


def test_platform_review_parser_keeps_actionable_field() -> None:
    service = JoyBuilderTranslationService(api_key="test-key", retry_attempts=0)
    model_output = json.dumps(
        [
            {
                "id": "multi-platform-workflow",
                "platform_relation": "directly_applicable",
                "content_type": "tool_resource",
                "specific_signal": True,
                "hard_risk": False,
                "source_status": "verified",
                "central_subject": False,
                "actionable_for_platform": True,
                "relevant_domain": True,
                "substantive": True,
                "low_value": False,
                "domain": "爆文与内容结构",
                "confidence": 0.94,
                "reason": "完整工作流明确支持小红书并说明平台限制。",
            }
        ],
        ensure_ascii=False,
    )
    captured_request: dict = {}

    def fake_urlopen(request, timeout):
        captured_request.update(json.loads(request.data.decode("utf-8")))
        return FakeResponse({"output_text": model_output})

    with patch("src.pipeline.translation.urllib.request.urlopen", fake_urlopen):
        decisions = service._classify_platform_chunk(
            [
                {
                    "id": "multi-platform-workflow",
                    "language": "zh",
                    "text": "完整运营工作流支持小红书，并说明发布前检查和自动化风控。",
                    "acceptance_path_hint": "tool_resource",
                    "evidence": {"media_count": 1},
                }
            ]
        )

    decision = decisions["multi-platform-workflow"]
    assert decision["central_subject"] is False
    assert decision["actionable_for_platform"] is True
    assert decision["content_type"] == "tool_resource"
    assert decision["platform_relation"] == "directly_applicable"
    assert decision["specific_signal"] is True
    assert decision["hard_risk"] is False
    assert decision["source_status"] == "verified"
    assert decision["substantive"] is True
    assert decision["low_value"] is False
    assert '"actionable_for_platform"' in captured_request["input"]
    assert '"acceptance_path_hint": "tool_resource"' in captured_request["input"]
    assert '"media_count": 1' in captured_request["input"]


if __name__ == "__main__":
    test_platform_review_prompt_has_typed_acceptance_paths()
    test_platform_review_prompt_contains_regression_examples()
    test_platform_review_prompt_keeps_risk_vetoes()
    test_platform_review_parser_keeps_actionable_field()
    print("Platform review prompt tests passed.")
