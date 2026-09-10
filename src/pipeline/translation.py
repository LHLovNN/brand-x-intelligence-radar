from __future__ import annotations

import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from typing import Any


CHINESE_RE = re.compile(r"[\u3400-\u9fff]")
JAPANESE_KANA_RE = re.compile(r"[\u3040-\u30ff]")
HANGUL_RE = re.compile(r"[\uac00-\ud7af]")
TEXT_SIGNAL_RE = re.compile(r"[\w\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]", re.UNICODE)
ZH_LANGUAGES = {"zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant", "cn"}
SEGMENT_ID_SEPARATOR = "::segment::"
PLATFORM_REVIEW_DOMAINS = (
    "账号冷启动",
    "爆文与内容结构",
    "流量机制",
    "风控对抗",
    "平台规则",
    "矩阵",
    "变现",
    "私域引流",
    "案例复盘",
    "逆向与改机",
)
PLATFORM_REVIEW_CONTENT_TYPES = (
    "platform_update",
    "method_case",
    "tool_resource",
    "monetization_opportunity",
    "case_lead",
    "platform_observation",
    "off_topic",
)
PLATFORM_REVIEW_RELATIONS = ("central", "directly_applicable", "incidental", "none")
PLATFORM_REVIEW_SOURCE_STATUSES = ("verified", "claimed", "rumor", "unknown")


def build_platform_review_prompt() -> str:
    """Build the deterministic policy prompt used by the platform semantic reviewer."""
    allowed_domains = json.dumps(PLATFORM_REVIEW_DOMAINS, ensure_ascii=False)
    allowed_content_types = json.dumps(PLATFORM_REVIEW_CONTENT_TYPES, ensure_ascii=False)
    return (
        "你是小红书运营情报的严格内容审核员。情报库同时收录平台动向、方法案例、工具资源、"
        "变现机会、案例线索和平台现象，不要只用‘是否为完整教程’这一把尺子判断。"
        "输入可能附带 acceptance_path_hint、互动数据、媒体数量和公开评论上下文；这些都属于审核证据。\n"
        "逐条独立判断以下字段：\n"
        "1. platform_relation：central 表示小红书是主要对象；directly_applicable 表示内容可直接用于"
        "小红书创作、运营、分析或发布；incidental 表示只是渠道罗列或顺带提及；none 表示无关。\n"
        "2. content_type：按内容主要价值选择一个类型。platform_update 是平台产品、账号体系、规则、"
        "算法、商业化或生态变化；method_case 是方法或完整案例；tool_resource 是 Skill、GitHub 项目、"
        "模板或工具；monetization_opportunity 是明确的变现模式；case_lead 是可继续追踪的人物、账号、"
        "项目或案例线索；platform_observation 是有具体对象、差异或讨论证据的平台现象；off_topic 是无关内容。\n"
        "3. specific_signal：正文或附加证据是否包含足以支持该类型的具体对象、变化、能力、模式、数据或对比。\n"
        "4. hard_risk：是否属于盗版或绝版资料售卖、网盘拉新、AI 代充、付费打粉或评论、"
        "规避平台规则的引流、低俗色情或其他黑灰产。hard_risk=true 必须拒绝。\n"
        "5. source_status：verified 表示有可核验的一手来源或数据；claimed 表示作者明确声称但尚未独立核实；"
        "rumor 表示爆料、传闻、预计或未经证实的平台消息；unknown 表示无法判断。传闻本身不是拒绝理由。\n"
        "兼容字段也必须返回：central_subject、actionable_for_platform、relevant_domain、substantive、low_value。\n"
        "以下任一情形可构成有效价值：\n"
        "- 工具或完整工作流明确支持小红书，且正文说明了实际能力、操作环节、平台适配、限制或风控；\n"
        "- 提示词、脚本、模板、选题、分镜或内容生产方法明确用于小红书，或明确说明该内容形态在小红书的表现；\n"
        "- 真实小红书运营案例同时给出具体动作和结果，例如发布频率、内容形式、账号操作，"
        "以及涨粉、互动、流量、获客、商单或变现结果。案例不必写成系统教程；\n"
        "- 针对小红书客户端、接口、签名、设备指纹、设备环境或账号风控的技术研究；\n"
        "- 明确描述小红书未来产品、账号体系、规则、流量机制、商业化或生态变化。即使是爆料或预计，"
        "也应判为 platform_update、specific_signal=true，并用 source_status=rumor 标记；\n"
        "- 明确列出可在小红书执行的变现模式，例如数字产品、模板素材或单品带货。"
        "它可以只是机会线索，不要求给出完整 SOP；\n"
        "- 明确指出某个人、账号、项目或团队在小红书拿到结果，可作为 case_lead 收录，"
        "但不要把其他平台的数据误写成小红书的已验证结果；\n"
        "- 对同一个小红书账号或同类内容给出具体形式对比、流量差异或可追溯现象。"
        "即使正文以提问结尾，只要媒体、评论或互动数据增强了证据，也可作为 platform_observation 收录。\n"
        "多平台方法不要求提供小红书独有的机制或技术适配。只要正文明确把小红书列为实际使用或推荐场景，"
        "并给出能在小红书执行的具体方法、动作链、模板、工具链或案例结果，"
        "即使这些方法也适用于公众号、抖音或 X，actionable_for_platform 仍应为 true。\n"
        "如果只是把小红书和其他平台并列为分发渠道、收藏来源或顺带提及，platform_relation 必须为 incidental。"
        "通用品牌营销案例不能因为最后写了‘借助小红书、抖音传播’就进入小红书情报库；"
        "用于收纳小红书收藏的通用工具，也不等于用于小红书创作或运营。\n"
        "收录条件：hard_risk=false，platform_relation 为 central 或 directly_applicable，"
        "content_type 不是 off_topic，specific_signal=true，且 relevant_domain=true。"
        "method_case 通常还应 substantive=true；platform_update、monetization_opportunity、case_lead、"
        "tool_resource 和 platform_observation 可以是有价值线索，不要求完整教程。"
        "low_value 只用于描述最终确实缺乏价值的内容，不能脱离 content_type 和 specific_signal 单独否决。\n"
        "正例校准：\n"
        "- 一个多平台运营 Agent 详细说明选题、生产、发布、复盘工作流，明确支持小红书并说明自动化风控，"
        "应判 actionable_for_platform=true、substantive=true、low_value=false。\n"
        "- 一份可直接复用的短视频提示词或分镜模板，明确说明该内容形态用于小红书且有流量表现，"
        "应判 actionable_for_platform=true、substantive=true。\n"
        "- 小红书账号案例给出每天两更、具体内容形式，并报告涨粉互动和商单结果，"
        "即使带有个人感慨、没有完整教程，也应判 substantive=true、low_value=false。\n"
        "- 多平台起号建议明确说明小红书适合图文起步，并给出‘先用轻量图文验证内容与洞察→"
        "以流量为目标做选题→对标账号和选择简单形式→根据真实数据迭代’的动作链，"
        "应判 actionable_for_platform=true；不能因这些动作也适用于其他平台而拒绝。\n"
        "- 正常、合规的数字产品已经在小红书产生收入或订单，正文继续提供生产该产品所需的提示词仓库、"
        "模板或工作流及具体用法，应判 actionable_for_platform=true、substantive=true；"
        "通用生产工具不必具备小红书独有功能，但工具链必须和前述小红书使用或变现场景存在明确联系。\n"
        "- 对同一个小红书账号或同类内容给出明确的内容形式对比，例如手写笔记持续成为爆款、"
        "改成电脑排版或露脸后流量明显下降，属于可验证的平台现象假设；即使以提问结尾，"
        "也应判 central_subject=true、relevant_domain=true、substantive=true、low_value=false。\n"
        "- ‘小红书预计将隔离海外身份账号与内地账号’属于平台未来动向，即使来源是业内爆料，"
        "也应收录并标记 source_status=rumor。\n"
        "- ‘小红书数字产品：手账、模板、素材包；小红书单品带货’已经给出具体变现模式，"
        "应判 monetization_opportunity，不应因缺少 SOP 拒绝。\n"
        "- 推荐一位明确声称曾在小红书拿到结果的操盘者或账号，属于 case_lead；"
        "可以收录为追踪线索，但应把未经核实的结果标为 claimed。\n"
        "反例校准：\n"
        "- 只写‘支持小红书、抖音、视频号等平台’，没有能力说明、模板、适配细节或案例，拒绝。\n"
        "- 只说‘小红书流量很好，大家快去做’，没有动作、方法或结果细节，拒绝。\n"
        "- 以购买、加群、私信或跳转为主要目的且没有实质方法的广告导流，以及盗版资料、网盘拉新、"
        "AI 代充、付费打粉或评论、规避平台规则的引流、低俗色情和其他黑灰产内容，拒绝。\n"
        "逆向与改机仅指围绕小红书客户端、接口、签名、设备指纹、设备环境、账号风控的技术研究，"
        "不包括普通手机维修或与小红书无关的逆向。\n"
        "只返回 JSON 数组。每项格式为："
        '{"id":"...","platform_relation":"central","content_type":"platform_update",'
        '"specific_signal":true,"hard_risk":false,"source_status":"rumor",'
        '"central_subject":true,"actionable_for_platform":false,"relevant_domain":true,'
        '"substantive":true,"low_value":false,"domain":"平台规则",'
        '"confidence":0.95,"reason":"一句话说明判断依据"}。'
        f"content_type 只能是：{allowed_content_types}；domain 只能是：{allowed_domains}。"
    )


class TranslationNotConfigured(RuntimeError):
    pass


class TranslationRequestError(RuntimeError):
    def __init__(self, message: str, *, retriable: bool = True, timeout: bool = False) -> None:
        super().__init__(message)
        self.retriable = retriable
        self.timeout = timeout


class TranslationService:
    provider_name = "none"
    configured = False

    def translate_batch(self, items: list[dict[str, str]]) -> dict[str, str]:
        return {}

    def classify_platform_batch(self, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {}


class NoopTranslationService(TranslationService):
    provider_name = "none"


class SampleDictionaryTranslationService(TranslationService):
    provider_name = "sample_dictionary"
    configured = True

    def translate_batch(self, items: list[dict[str, str]]) -> dict[str, str]:
        translated: dict[str, str] = {}
        for item in items:
            text = item["text"]
            match = sample_translation(text)
            if match:
                translated[item["id"]] = match
        return translated


class JoyBuilderTranslationService(TranslationService):
    provider_name = "joybuilder"
    configured = True

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        endpoint: str | None = None,
        timeout_seconds: int = 90,
        batch_size: int = 6,
        retry_attempts: int = 1,
        max_chars_per_batch: int = 3500,
    ) -> None:
        self.api_key = api_key
        self.model = model or os.getenv("JDBUILDER_TRANSLATION_MODEL") or "GPT-5.5"
        self.endpoint = endpoint or os.getenv("JDBUILDER_RESPONSES_URL") or "http://ai-api.jdcloud.com/v1/responses"
        self.timeout_seconds = positive_int_env("JDBUILDER_TRANSLATION_TIMEOUT_SECONDS", timeout_seconds)
        self.batch_size = positive_int_env("JDBUILDER_TRANSLATION_BATCH_SIZE", batch_size)
        self.retry_attempts = positive_int_env("JDBUILDER_TRANSLATION_RETRIES", retry_attempts, minimum=0)
        self.max_chars_per_batch = positive_int_env("JDBUILDER_TRANSLATION_MAX_CHARS", max_chars_per_batch)
        self.errors: list[str] = []
        self.last_error = ""
        self.classification_errors: list[str] = []
        self.classification_last_error = ""
        self._strict_translation_attempt = False

    def translate_batch(self, items: list[dict[str, str]]) -> dict[str, str]:
        self.errors = []
        self.last_error = ""
        expanded_items, segments_by_item = self._expand_long_items(items)
        expanded_result: dict[str, str] = {}
        for chunk in self._split_items(expanded_items):
            try:
                expanded_result.update(self._translate_chunk_with_recovery(chunk))
            except Exception as error:
                self._record_error(error)
        return self._merge_segmented_translations(items, expanded_result, segments_by_item)

    def classify_platform_batch(self, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        self.classification_errors = []
        self.classification_last_error = ""
        decisions: dict[str, dict[str, Any]] = {}
        for chunk in self._split_items(items):
            last_error: Exception | None = None
            for attempt in range(self.retry_attempts + 1):
                try:
                    decisions.update(self._classify_platform_chunk(chunk))
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    if attempt < self.retry_attempts:
                        time.sleep(min(2**attempt, 4))
            if last_error:
                message = str(last_error).strip() or last_error.__class__.__name__
                if message not in self.classification_errors and len(self.classification_errors) < 3:
                    self.classification_errors.append(message)
        self.classification_last_error = "; ".join(self.classification_errors)
        return decisions

    def _classify_platform_chunk(self, items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        system_prompt = build_platform_review_prompt()
        input_payload = json.dumps(
            [
                {
                    "id": item["id"],
                    "language": item.get("language", "und"),
                    "text": item.get("text", ""),
                    "acceptance_path_hint": item.get("acceptance_path_hint", ""),
                    "evidence": item.get("evidence") or {},
                }
                for item in items
            ],
            ensure_ascii=False,
        )
        request_body = {
            "model": self.model,
            "stream": False,
            "input": f"{system_prompt}\n\n待审核帖子 JSON 数组：\n{input_payload}",
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise TranslationRequestError(
                f"JoyBuilder platform review failed with HTTP {error.code}: {body[:300]}",
                retriable=error.code == 429 or 500 <= error.code < 600,
            ) from error
        except urllib.error.URLError as error:
            raise TranslationRequestError(f"JoyBuilder platform review failed: {error}") from error
        except (socket.timeout, TimeoutError) as error:
            raise TranslationRequestError(
                f"JoyBuilder platform review timed out after {self.timeout_seconds}s",
                timeout=True,
            ) from error

        text = response_output_text(payload)
        try:
            records = json.loads(extract_json_array(text))
        except json.JSONDecodeError as error:
            raise TranslationRequestError(f"JoyBuilder platform review returned non-JSON output: {text[:300]}") from error
        decisions: dict[str, dict[str, Any]] = {}
        allowed = set(PLATFORM_REVIEW_DOMAINS)
        allowed_content_types = set(PLATFORM_REVIEW_CONTENT_TYPES)
        allowed_relations = set(PLATFORM_REVIEW_RELATIONS)
        allowed_source_statuses = set(PLATFORM_REVIEW_SOURCE_STATUSES)
        for record in records if isinstance(records, list) else []:
            if not isinstance(record, dict):
                continue
            item_id = str(record.get("id") or "")
            domain = str(record.get("domain") or "")
            if not item_id or domain not in allowed:
                continue
            try:
                confidence = max(0.0, min(1.0, float(record.get("confidence") or 0)))
            except (TypeError, ValueError):
                confidence = 0.0
            decisions[item_id] = {
                "platform_relation": (
                    str(record.get("platform_relation") or "")
                    if str(record.get("platform_relation") or "") in allowed_relations
                    else ""
                ),
                "content_type": (
                    str(record.get("content_type") or "")
                    if str(record.get("content_type") or "") in allowed_content_types
                    else ""
                ),
                "specific_signal": record.get("specific_signal") is True,
                "hard_risk": record.get("hard_risk") is True,
                "source_status": (
                    str(record.get("source_status") or "")
                    if str(record.get("source_status") or "") in allowed_source_statuses
                    else "unknown"
                ),
                "central_subject": record.get("central_subject") is True,
                "actionable_for_platform": record.get("actionable_for_platform") is True,
                "relevant_domain": record.get("relevant_domain") is True,
                "substantive": record.get("substantive") is True,
                "low_value": record.get("low_value") is True,
                "domain": domain,
                "confidence": confidence,
                "reason": str(record.get("reason") or "")[:300],
            }
        return decisions

    def _expand_long_items(self, items: list[dict[str, str]]) -> tuple[list[dict[str, str]], dict[str, list[str]]]:
        expanded: list[dict[str, str]] = []
        segments_by_item: dict[str, list[str]] = {}
        for item in items:
            item_id = item["id"]
            segments = split_translation_text(item.get("text", ""), self.max_chars_per_batch)
            if len(segments) <= 1:
                expanded.append(item)
                continue
            segment_ids: list[str] = []
            for index, segment in enumerate(segments):
                segment_id = f"{item_id}{SEGMENT_ID_SEPARATOR}{index}"
                expanded.append({**item, "id": segment_id, "text": segment})
                segment_ids.append(segment_id)
            segments_by_item[item_id] = segment_ids
        return expanded, segments_by_item

    def _merge_segmented_translations(
        self,
        original_items: list[dict[str, str]],
        expanded_result: dict[str, str],
        segments_by_item: dict[str, list[str]],
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for item in original_items:
            item_id = item["id"]
            segment_ids = segments_by_item.get(item_id)
            if not segment_ids:
                if item_id in expanded_result:
                    result[item_id] = expanded_result[item_id]
                continue
            translated_segments = [expanded_result.get(segment_id, "").strip() for segment_id in segment_ids]
            if all(translated_segments):
                result[item_id] = "\n\n".join(translated_segments)
            else:
                missing = [segment_id for segment_id, value in zip(segment_ids, translated_segments) if not value]
                self._record_error(TranslationRequestError(f"Long translation missing segments for {item_id}: {', '.join(missing[:3])}"))
        return result

    def _split_items(self, items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        chunks: list[list[dict[str, Any]]] = []
        chunk: list[dict[str, Any]] = []
        char_count = 0
        for item in items:
            evidence_length = len(json.dumps(item.get("evidence") or {}, ensure_ascii=False))
            text_length = len(item.get("text", "")) + evidence_length + len(item.get("acceptance_path_hint", ""))
            if chunk and (len(chunk) >= self.batch_size or char_count + text_length > self.max_chars_per_batch):
                chunks.append(chunk)
                chunk = []
                char_count = 0
            chunk.append(item)
            char_count += text_length
        if chunk:
            chunks.append(chunk)
        return chunks

    def _translate_chunk_with_recovery(self, items: list[dict[str, str]]) -> dict[str, str]:
        try:
            return self._translate_chunk_with_retries(items)
        except TranslationRequestError as error:
            if len(items) <= 1:
                recovered = self._recover_single_item_by_splitting(items[0], error)
                if recovered:
                    return recovered
                raise
            midpoint = max(1, len(items) // 2)
            translations: dict[str, str] = {}
            for sub_chunk in (items[:midpoint], items[midpoint:]):
                try:
                    translations.update(self._translate_chunk_with_recovery(sub_chunk))
                except Exception as sub_error:
                    self._record_error(sub_error)
            if translations:
                self._record_error(error)
                return translations
            raise error

    def _recover_single_item_by_splitting(self, item: dict[str, str], error: TranslationRequestError) -> dict[str, str]:
        if not error.retriable:
            return {}
        text = item.get("text", "")
        if len(text) <= 400:
            return {}
        retry_limit = max(400, len(text) // 2)
        segments = split_translation_text(text, retry_limit)
        if len(segments) <= 1:
            return {}
        segment_ids = []
        expanded = []
        for index, segment in enumerate(segments):
            segment_id = f"{item['id']}{SEGMENT_ID_SEPARATOR}retry{index}"
            expanded.append({**item, "id": segment_id, "text": segment})
            segment_ids.append(segment_id)
        translations = self._translate_chunk_with_recovery(expanded)
        translated_segments = [translations.get(segment_id, "").strip() for segment_id in segment_ids]
        if all(translated_segments):
            self._record_error(error)
            return {item["id"]: "\n\n".join(translated_segments)}
        return {}

    def _translate_chunk_with_retries(self, items: list[dict[str, str]]) -> dict[str, str]:
        last_error: TranslationRequestError | None = None
        for attempt in range(self.retry_attempts + 1):
            self._strict_translation_attempt = attempt > 0
            try:
                return self._translate_chunk(items)
            except TranslationRequestError as error:
                last_error = error
                if error.timeout and len(items) > 1:
                    break
                if attempt >= self.retry_attempts or not error.retriable:
                    break
                time.sleep(min(2**attempt, 4))
            finally:
                self._strict_translation_attempt = False
        if last_error:
            raise last_error
        return {}

    def _record_error(self, error: Exception) -> None:
        message = str(error).strip() or error.__class__.__name__
        if message and message not in self.errors and len(self.errors) < 3:
            self.errors.append(message)
        self.last_error = "; ".join(self.errors)

    def _build_request_body(self, items: list[dict[str, str]]) -> dict[str, Any]:
        system_prompt = (
            "你是专业的多语言社交媒体译员。请把输入的公开社媒帖子忠实翻译成自然、准确的简体中文。"
            "不要总结，不要省略事实，不要添加分析。保留品牌名、@账号、话题标签、URL、数字、emoji 和专有名词。"
            "只返回 JSON 数组，每一项必须是 {\"id\":\"...\",\"translation_zh\":\"...\"}。"
        )
        if self._strict_translation_attempt:
            system_prompt += (
                " 重要：translation_zh 必须包含简体中文字符，绝不能原样返回英文或其他非中文原文。"
                "如果某些品牌名、人名、股票代码或专有名词不需要翻译，也要用中文句子说明原文含义。"
                "如果文本很长，请完整逐段翻译，不要摘要。"
            )
        input_payload = json.dumps(
            [
                {
                    "id": item["id"],
                    "language": item.get("language", "und"),
                    "text": item["text"],
                }
                for item in items
            ],
            ensure_ascii=False,
        )
        return {
            "model": self.model,
            "stream": False,
            "input": f"{system_prompt}\n\n待翻译帖子 JSON 数组：\n{input_payload}",
        }

    def _translate_chunk(self, items: list[dict[str, str]]) -> dict[str, str]:
        request_body = self._build_request_body(items)
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            retriable = error.code == 429 or 500 <= error.code < 600
            raise TranslationRequestError(
                f"JoyBuilder translation request failed with HTTP {error.code}: {body[:300]}",
                retriable=retriable,
            ) from error
        except urllib.error.URLError as error:
            raise TranslationRequestError(f"JoyBuilder translation request failed: {error}") from error
        except (socket.timeout, TimeoutError) as error:
            raise TranslationRequestError(
                f"JoyBuilder translation request timed out after {self.timeout_seconds}s",
                timeout=True,
            ) from error

        text = response_output_text(payload)
        try:
            records = json.loads(extract_json_array(text))
        except json.JSONDecodeError as error:
            raise TranslationRequestError(f"JoyBuilder translation returned non-JSON output: {text[:300]}") from error
        translations: dict[str, str] = {}
        for record in records:
            item_id = str(record.get("id", ""))
            translation = str(record.get("translation_zh", "")).strip()
            if item_id and translation:
                translations[item_id] = translation
        self._validate_chunk_translations(items, translations)
        return translations

    def _validate_chunk_translations(self, items: list[dict[str, str]], translations: dict[str, str]) -> None:
        invalid_ids = []
        for item in items:
            item_id = item["id"]
            translation = translations.get(item_id, "").strip()
            if not translation:
                invalid_ids.append(item_id)
                continue
            probe = {"language": item.get("language", "und"), "clean_text": item.get("text", "")}
            if needs_translation(probe) and not CHINESE_RE.search(translation):
                invalid_ids.append(item_id)
        if invalid_ids:
            raise TranslationRequestError(
                f"JoyBuilder translation missing or non-Chinese output for ids: {', '.join(invalid_ids[:5])}",
                retriable=True,
            )


def build_translation_service(source_provider: str) -> TranslationService:
    selected = (os.getenv("TRANSLATION_PROVIDER") or "").strip().lower()
    if not selected:
        selected = "sample_dictionary" if source_provider == "sample" else "joybuilder"
    if selected in {"none", "off", "disabled"}:
        return NoopTranslationService()
    if selected in {"sample", "sample_dictionary"}:
        return SampleDictionaryTranslationService()
    if selected in {"joybuilder", "jdcloud", "company", "company_gpt"}:
        api_key = os.getenv("JDCLOUD_GPT_API_KEY")
        if not api_key:
            return NoopTranslationService()
        return JoyBuilderTranslationService(api_key=api_key)
    raise TranslationNotConfigured(f"Unknown TRANSLATION_PROVIDER: {selected}")


def apply_translations(posts: list[dict[str, Any]], service: TranslationService) -> dict[str, Any]:
    pending: list[dict[str, str]] = []
    for index, post in enumerate(posts):
        text = post.get("clean_text") or post.get("text") or ""
        post["translation_provider"] = service.provider_name
        if not needs_translation(post):
            post["translation_zh"] = text
            post["translation_status"] = "source_chinese"
            continue
        supplied = str(post.get("translation_zh") or "").strip()
        if supplied and CHINESE_RE.search(supplied):
            post["translation_status"] = "provider_supplied"
            continue
        post["translation_zh"] = ""
        post["translation_status"] = "pending"
        pending.append(
            {
                "id": str(index),
                "language": str(post.get("language") or "und"),
                "text": text,
            }
        )

    translations: dict[str, str] = {}
    error_message = ""
    if pending and service.configured:
        try:
            translations = service.translate_batch(pending)
        except Exception as error:
            error_message = f"{error.__class__.__name__}: {error}"
        if not error_message:
            error_message = str(getattr(service, "last_error", "") or "")

    for item in pending:
        post = posts[int(item["id"])]
        translated = translations.get(item["id"], "").strip()
        if translated and CHINESE_RE.search(translated):
            post["translation_zh"] = translated
            post["translation_status"] = "sample_dictionary" if service.provider_name == "sample_dictionary" else "translated"
        elif translated:
            post["translation_zh"] = item["text"]
            post["translation_status"] = "error"
            post["translation_error"] = "Translation provider returned non-Chinese output."
        else:
            post["translation_zh"] = item["text"]
            post["translation_status"] = "error" if error_message else "missing"
            if error_message:
                post["translation_error"] = error_message[:300]

    return translation_report(posts, service.provider_name, error_message)


def positive_int_env(name: str, fallback: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if not raw:
        return max(minimum, fallback)
    try:
        value = int(raw)
    except ValueError:
        return max(minimum, fallback)
    return max(minimum, value)


def split_translation_text(text: str, max_chars: int) -> list[str]:
    value = str(text or "").strip()
    if not value:
        return [""]
    limit = max(1, max_chars)
    if len(value) <= limit:
        return [value]

    segments: list[str] = []
    start = 0
    while start < len(value):
        end = min(len(value), start + limit)
        if end < len(value):
            end = best_translation_split(value, start, end, limit)
        segment = value[start:end].strip()
        if segment:
            segments.append(segment)
        start = end
    return segments or [value[:limit]]


def best_translation_split(text: str, start: int, hard_end: int, limit: int) -> int:
    min_end = start + max(1, limit // 2)
    for boundary in ("\n\n", "\n", ". ", "。", "！", "？", "; ", "；", ", ", "，", " "):
        index = text.rfind(boundary, min_end, hard_end)
        if index > start:
            return index + len(boundary)
    return hard_end


def needs_translation(post: dict[str, Any]) -> bool:
    language = str(post.get("language") or "").strip().lower()
    text = post.get("clean_text") or post.get("text") or ""
    if language in ZH_LANGUAGES:
        return False
    if language and language != "und":
        return True
    return not is_probably_chinese_text(text)


def is_probably_chinese_text(text: str) -> bool:
    if not text or not CHINESE_RE.search(text):
        return False
    if JAPANESE_KANA_RE.search(text) or HANGUL_RE.search(text):
        return False
    signal_chars = TEXT_SIGNAL_RE.findall(text)
    if not signal_chars:
        return False
    chinese_chars = CHINESE_RE.findall(text)
    return len(chinese_chars) / len(signal_chars) >= 0.3


def translation_report(posts: list[dict[str, Any]], provider: str, error_message: str = "") -> dict[str, Any]:
    counts: dict[str, int] = {}
    missing_examples = []
    for post in posts:
        status = str(post.get("translation_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
        if status in {"missing", "error"} and len(missing_examples) < 3:
            missing_examples.append(
                {
                    "post_id": post.get("post_id"),
                    "language": post.get("language", "und"),
                    "author_handle": post.get("author", {}).get("handle") or post.get("author_handle"),
                }
            )
    return {
        "provider": provider,
        "configured": provider != "none",
        "counts": counts,
        "missing_count": counts.get("missing", 0) + counts.get("error", 0),
        "fallback_original_count": counts.get("missing", 0) + counts.get("error", 0),
        "missing_examples": missing_examples,
        "error": error_message,
    }


def sample_translation(text: str) -> str:
    if CHINESE_RE.search(text):
        return text
    lower = text.lower()
    translations = [
        (
            ["still waiting", "joybuy refund", "12 days"],
            "我还在等 Joybuy 退款，已经 12 天了。客服一直说这个 case 还在审核中。",
        ),
        (
            ["same refund issue", "joybuy uk", "payment is still pending"],
            "我也遇到了 Joybuy UK 的退款问题。订单已经取消，但付款状态仍然挂起。",
        ),
        (
            ["joybuy germany delivered", "two days earlier"],
            "JD.com / Joybuy Germany 比预计时间提前两天把手机送到了，价格也不错。",
        ),
        (
            ["joybuy netherlands legit", "never got the parcel"],
            "Joybuy Netherlands 靠谱吗？物流显示已送达，但我从来没有收到包裹。",
        ),
        (
            ["joybuy france promo code", "returns are easy"],
            "Joybuy France 的优惠码可以用，预计送达时间看起来也合理。我好奇退货是否方便。",
        ),
        (
            ["joybuy belgium", "slow customer service"],
            "有个关于 Joybuy Belgium 的讨论串：价格低，但有人反馈退货时客服响应较慢。",
        ),
        (
            ["joybuy luxembourg", "damaged packaging"],
            "Joybuy Luxembourg 的订单到了，但包装破损。商品看起来没问题，不过客服应该回应。",
        ),
        (
            ["jd overseas shopping", "same checkout flow"],
            "JD 海外购物流程有点让人困惑。Joybuy 对欧盟客户是不是同一个结账流程？",
        ),
        (
            ["switch from temu to joybuy", "germany shipping"],
            "如果 Joybuy Germany 的配送能一直这么快，我可能会从 Temu 转到 Joybuy。",
        ),
        (
            ["joybuy return page", "timing out"],
            "Joybuy 的退货页面一直超时，还有其他人遇到这个问题吗？",
        ),
        (
            ["joybuy refund screenshot", "not sure if it is real"],
            "这张 Joybuy 退款截图正在我的群聊里传播。我不确定它是不是真的。",
        ),
        (
            ["temu refund", "support chat finally solved"],
            "Temu 的退款比预期更久，但在线客服最后解决了问题。",
        ),
        (
            ["temu delivery", "joybuy germany"],
            "Temu 配送变慢后，有人开始拿 Joybuy Germany 做对比。",
        ),
        (
            ["temu delivery", "germany", "slower"],
            "Temu 在德国本周配送变慢了。还有其他人在等包裹吗？",
        ),
        (
            ["temu fake discount", "same price"],
            "又一个关于 Temu 虚假折扣的讨论串。同样的价格每周都会出现。",
        ),
        (
            ["joybuy logistics", "temu"],
            "如果 Joybuy 的物流保持稳定，可能会吸走一部分 Temu 用户。",
        ),
        (
            ["temu package", "damaged", "refund request"],
            "Temu 包裹送达时已经损坏，用户已经发起退款申请。",
        ),
        (
            ["temu customer service", "surprisingly quick"],
            "Temu 今天的客服响应出乎意料地快。",
        ),
    ]
    for needles, translation in translations:
        if all(needle in lower for needle in needles):
            return translation
    return ""


def response_output_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    if isinstance(payload.get("text"), str):
        return payload["text"]
    chunks: list[str] = []
    for output in payload.get("output", []) or []:
        for content in output.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    for candidate in payload.get("candidates", []) or []:
        content = candidate.get("content", {})
        for part in content.get("parts", []) or []:
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
    for choice in payload.get("choices", []) or []:
        message = choice.get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            chunks.append(content)
    return "\n".join(chunks)


def extract_json_array(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("["):
        return stripped
    start = stripped.find("[")
    end = stripped.rfind("]")
    if start >= 0 and end >= start:
        return stripped[start : end + 1]
    return stripped
