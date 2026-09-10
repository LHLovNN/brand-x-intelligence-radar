#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.translation import (  # noqa: E402
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


def test_platform_review_prompt_has_two_acceptance_paths() -> None:
    prompt = build_platform_review_prompt()

    assert prompt == build_platform_review_prompt()
    assert "A. central_subject=true；B. actionable_for_platform=true" in prompt
    assert "多平台内容可以为 false，不要为了收录而虚报 true" in prompt
    assert "案例不必写成系统教程" in prompt
    assert "具体动作加结果数据本身就可以为 true" in prompt
    assert "多平台方法不要求提供小红书独有的机制或技术适配" in prompt
    assert "即使这些方法也适用于公众号、抖音或 X" in prompt
    assert "只宣称‘支持小红书等平台’" in prompt
    assert "低俗色情和其他黑灰产内容，拒绝" in prompt
    assert "low_value 是独立否决项" in prompt
    for domain in PLATFORM_REVIEW_DOMAINS:
        assert domain in prompt


def test_platform_review_prompt_contains_regression_examples() -> None:
    prompt = build_platform_review_prompt()

    assert "选题、生产、发布、复盘工作流" in prompt
    assert "短视频提示词或分镜模板" in prompt
    assert "每天两更、具体内容形式" in prompt
    assert "涨粉互动和商单结果" in prompt
    assert "不得仅因是多平台内容而拒绝" in prompt
    assert "小红书适合图文起步" in prompt
    assert "先用轻量图文验证内容与洞察" in prompt
    assert "对标账号和选择简单形式" in prompt
    assert "正常、合规的数字产品已经在小红书产生收入或订单" in prompt
    assert "生产该产品所需的提示词仓库" in prompt
    assert "通用生产工具不必具备小红书独有功能" in prompt
    assert "手写笔记持续成为爆款" in prompt
    assert "属于可验证的平台现象假设" in prompt


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
    assert "即使步骤具体也必须判 low_value=true" in prompt


def test_platform_review_parser_keeps_actionable_field() -> None:
    service = JoyBuilderTranslationService(api_key="test-key", retry_attempts=0)
    model_output = json.dumps(
        [
            {
                "id": "multi-platform-workflow",
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
                }
            ]
        )

    decision = decisions["multi-platform-workflow"]
    assert decision["central_subject"] is False
    assert decision["actionable_for_platform"] is True
    assert decision["substantive"] is True
    assert decision["low_value"] is False
    assert '"actionable_for_platform":true' in captured_request["input"]


if __name__ == "__main__":
    test_platform_review_prompt_has_two_acceptance_paths()
    test_platform_review_prompt_contains_regression_examples()
    test_platform_review_prompt_keeps_risk_vetoes()
    test_platform_review_parser_keeps_actionable_field()
    print("Platform review prompt tests passed.")
