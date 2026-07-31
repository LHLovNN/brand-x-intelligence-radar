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

    def _split_items(self, items: list[dict[str, str]]) -> list[list[dict[str, str]]]:
        chunks: list[list[dict[str, str]]] = []
        chunk: list[dict[str, str]] = []
        char_count = 0
        for item in items:
            text_length = len(item.get("text", ""))
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
