from __future__ import annotations

import html
import json
import os
import re
import socket
import urllib.error
import urllib.request
from typing import Any

from src.pipeline.translation import CHINESE_RE, TranslationService, apply_translations, needs_translation, response_output_text


CONTEXT_BEFORE_LIMIT = 20
CONTEXT_AFTER_LIMIT = 20
CONTEXT_SCORE_THRESHOLD = 60
CONTEXT_FOLLOWER_THRESHOLD = 1000
COMPETITOR_CONTEXT_MIN_VIEWS = 500
CONTEXT_FETCH_LIMIT = 50
CONTEXT_TRANSLATION_TIMEOUT_SECONDS = 30
CONTEXT_SUMMARY_TIMEOUT_SECONDS = 20
CONTEXT_SUMMARY_CHAR_LIMIT = 200
LOW_QUALITY_CONTEXT_PATTERNS = [
    re.compile(r"应该没人比我玩[的得]开了吧", re.IGNORECASE),
    re.compile(r"我[福肤]不黑不信你看", re.IGNORECASE),
    re.compile(r"比(?:我|你|他|她|ta).{0,4}好看的没(?:我|你|他|她|ta).{0,4}骚.{0,20}比(?:我|你|他|她|ta).{0,4}骚的没(?:我|你|他|她|ta).{0,4}好看", re.IGNORECASE),
    re.compile(r"比(?:我|你|他|她|ta).{0,4}好看的没.{0,10}骚.{0,24}比(?:我|你|他|她|ta).{0,4}骚的没.{0,10}好看", re.IGNORECASE),
    re.compile(r"只入身体.{0,20}不入生活", re.IGNORECASE),
    re.compile(r"我果然太[涩色瑟]了.{0,16}有人想锐评一下我的[福肤]嘛", re.IGNORECASE),
    re.compile(r"sao.{0,8}货.{0,16}没人比(?:她|他|ta)sao", re.IGNORECASE),
    re.compile(r"(?:\d+\+)?(?:果然)?太[涩色瑟]了.{0,16}我真顶不住", re.IGNORECASE),
    re.compile(r"她太[涩色瑟]了.{0,16}我真顶不住", re.IGNORECASE),
    re.compile(r"主页.{0,16}能打(?:✈|飞机)", re.IGNORECASE),
    re.compile(r"玩归玩闹归闹.{0,24}给(?:你|妳)?看[福肤].{0,24}不开玩笑", re.IGNORECASE),
]
LOW_QUALITY_CONTEXT_PROFILE_PATTERNS = [
    re.compile(
        r"找炮友|约炮|约p|曰炮|固炮|入驻.{0,12}(?:炮|约p)平台|真人认证.{0,30}隐私|附近的可加v|小号已禁言|涩播|涩涩|寻欢必备|远程指挥直播控制玩具|同城.{0,8}线下|绿泡泡",
        re.IGNORECASE,
    ),
]


def attach_conversation_contexts(
    posts: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    x_source: Any | None,
    translation_service: TranslationService | None,
    window_start: str,
    window_end: str,
    allow_anchor_threads: bool = False,
) -> dict[str, Any]:
    if not x_source or not can_fetch_context(x_source):
        return {"attempted": 0, "attached": 0, "warnings": []}

    score_by_post = cluster_score_by_post(clusters)
    targets = context_targets(posts, score_by_post, allow_anchor_threads=allow_anchor_threads)
    target_ids = configured_target_post_ids()
    if target_ids:
        targets = [post for post in targets if str(post.get("post_id") or "") in target_ids]
    eligible = len(targets)
    max_targets = optional_positive_int_env("CONVERSATION_CONTEXT_MAX_TARGETS")
    if max_targets:
        targets = targets[:max_targets]
    if not targets:
        return {"eligible": eligible, "attempted": 0, "attached": 0, "warnings": []}

    fetch_limit = context_fetch_limit()
    fetched_by_conversation: dict[str, list[dict[str, Any]]] = {}
    warnings: list[str] = []
    attached = 0
    unresolved = 0
    filtered_noise = 0
    capped_contexts = 0
    summary_counts: dict[str, int] = {}
    for post in targets:
        conversation_id = str(post.get("conversation_id") or "")
        if not conversation_id:
            continue
        if conversation_id not in fetched_by_conversation:
            try:
                rows = fetch_context_rows(x_source, post, conversation_id, window_start, window_end, fetch_limit)
            except Exception as error:
                warnings.append(f"conversation {conversation_id} context fetch failed: {str(error)[:180]}")
                fetched_by_conversation[conversation_id] = []
            else:
                if len(rows) >= fetch_limit:
                    capped_contexts += 1
                context_rows, removed = filter_context_noise(rows)
                filtered_noise += removed
                fetched_by_conversation[conversation_id] = prepare_context_rows(context_rows, translation_service)
        rows = fetched_by_conversation[conversation_id]
        if not has_context_row_neighbor(post, rows):
            post.pop("conversation_context", None)
            unresolved += 1
            continue

        context = build_context_for_post(post, rows, translation_service)
        if context and has_context_neighbor(context):
            post["conversation_context"] = context
            attached += 1
            summary_status = str(context.get("summary_status") or "fallback")
            summary_counts[summary_status] = summary_counts.get(summary_status, 0) + 1
        else:
            post.pop("conversation_context", None)
            unresolved += 1

    if summary_counts.get("fallback") and can_generate_context_summary(translation_service):
        warnings.append("conversation context summaries fell back to local rules for some posts.")
    if capped_contexts:
        warnings.append(f"conversation context capped at {fetch_limit} posts for {capped_contexts} item(s).")

    return {
        "attempted": len(targets),
        "eligible": eligible,
        "attached": attached,
        "unresolved": unresolved,
        "filtered_noise": filtered_noise,
        "fetch_limit": fetch_limit,
        "summary": summary_counts,
        "warnings": warnings[:5],
    }


def can_fetch_context(x_source: Any) -> bool:
    return hasattr(x_source, "conversation_posts")


def fetch_context_rows(
    x_source: Any,
    post: dict[str, Any],
    conversation_id: str,
    window_start: str,
    window_end: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    fetch_limit = max(1, int(limit or context_fetch_limit()))
    post_id = str(post.get("post_id") or "")
    if post_id and hasattr(x_source, "thread_context_posts"):
        rows = filter_thread_context_rows(
            post,
            x_source.thread_context_posts(post_id, window_start, window_end, limit=fetch_limit),
        )
        if has_context_row_neighbor(post, rows):
            return rows
    return x_source.conversation_posts(conversation_id, window_start, window_end, limit=fetch_limit)


def has_context_neighbor(context: dict[str, Any]) -> bool:
    return len(context.get("posts") or []) > 1


def has_context_row_neighbor(anchor: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    anchor_id = str(anchor.get("post_id") or "")
    if not anchor_id:
        return False
    for row in rows:
        row_id = str(row.get("post_id") or row.get("url") or "")
        if row_id and row_id != anchor_id:
            return True
    return False


def filter_thread_context_rows(anchor: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if is_thread_context_row(anchor, row)]


def is_thread_context_row(anchor: dict[str, Any], row: dict[str, Any]) -> bool:
    anchor_id = str(anchor.get("post_id") or "").strip()
    row_id = str(row.get("post_id") or row.get("url") or "").strip()
    if not anchor_id or not row_id:
        return False
    if row_id == anchor_id:
        return True

    anchor_conversation_id = str(anchor.get("conversation_id") or "").strip()
    row_conversation_id = str(row.get("conversation_id") or "").strip()
    if anchor_conversation_id and (row_conversation_id == anchor_conversation_id or row_id == anchor_conversation_id):
        return True

    anchor_reply_to = str(anchor.get("reply_to_post_id") or anchor.get("in_reply_to_status_id") or "").strip()
    row_reply_to = str(row.get("reply_to_post_id") or row.get("in_reply_to_status_id") or "").strip()
    if row_reply_to == anchor_id or (anchor_reply_to and row_id == anchor_reply_to):
        return True

    anchor_handle = str(anchor.get("author_handle") or anchor.get("author", {}).get("handle") or "").strip().lstrip("@").lower()
    row_reply_handle = str(row.get("reply_to_handle") or row.get("in_reply_to_screen_name") or "").strip().lstrip("@").lower()
    if anchor_handle and row_reply_handle == anchor_handle:
        return True

    mentioned_handle = leading_mention(row).lower()
    if anchor_handle and mentioned_handle == anchor_handle:
        return True

    anchor_mentioned_handle = leading_mention(anchor).lower()
    row_handle = str(row.get("author_handle") or row.get("author", {}).get("handle") or "").strip().lstrip("@").lower()
    return bool(anchor_mentioned_handle and row_handle == anchor_mentioned_handle)


def cluster_score_by_post(clusters: list[dict[str, Any]]) -> dict[str, int]:
    scores: dict[str, int] = {}
    for cluster in clusters:
        score = int(cluster.get("score", {}).get("ips") or 0)
        for post_id in cluster.get("post_ids", []):
            scores[str(post_id)] = score
    return scores


def context_targets(posts: list[dict[str, Any]], score_by_post: dict[str, int], allow_anchor_threads: bool = False) -> list[dict[str, Any]]:
    targets = []
    seen: set[str] = set()
    for post in posts:
        if not post.get("is_relevant"):
            continue
        score = score_by_post.get(str(post.get("post_id")), competitor_context_score(post))
        if not should_fetch_context(post, score, allow_anchor_threads=allow_anchor_threads):
            continue
        key = str(post.get("post_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        targets.append((score, context_followers(post), str(post.get("created_at") or ""), post))
    return [post for _, _, _, post in sorted(targets, key=lambda item: (item[0], item[1], item[2]), reverse=True)]


def dedupe_conversation_items_keep_earliest(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep one collected entry per X conversation, preferring the earliest post."""
    selected: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    removed = 0
    for item in items:
        key = conversation_dedupe_key(item)
        if not key:
            selected.append(item)
            continue
        existing_index = index_by_key.get(key)
        if existing_index is None:
            index_by_key[key] = len(selected)
            selected.append(item)
            continue
        removed += 1
        if is_earlier_conversation_item(item, selected[existing_index]):
            selected[existing_index] = item
    return selected, removed


def dedupe_contextual_items_keep_earliest(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep one collected entry when items belong to overlapping context windows."""
    groups: list[dict[str, Any]] = []
    for item in items:
        ids = contextual_dedupe_ids(item)
        if not ids:
            groups.append({"ids": set(), "items": [item]})
            continue
        matching_indexes = [index for index, group in enumerate(groups) if group["ids"] and ids & group["ids"]]
        if not matching_indexes:
            groups.append({"ids": ids, "items": [item]})
            continue
        first_index = matching_indexes[0]
        groups[first_index]["ids"].update(ids)
        groups[first_index]["items"].append(item)
        for index in reversed(matching_indexes[1:]):
            groups[first_index]["ids"].update(groups[index]["ids"])
            groups[first_index]["items"].extend(groups[index]["items"])
            groups.pop(index)

    kept = [earliest_contextual_item(group["items"]) for group in groups]
    return kept, max(0, len(items) - len(kept))


def contextual_dedupe_ids(item: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    conversation_id = str(item.get("conversation_id") or "").strip()
    if conversation_id:
        ids.add(f"conversation:{conversation_id}")
    post_id = str(item.get("post_id") or "").strip()
    if post_id:
        ids.add(f"post:{post_id}")
    context = item.get("conversation_context") or {}
    if isinstance(context, dict):
        for post in context.get("posts") or []:
            if not isinstance(post, dict):
                continue
            context_post_id = str(post.get("post_id") or "").strip()
            if context_post_id:
                ids.add(f"post:{context_post_id}")
    return ids


def earliest_contextual_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    return sorted(items, key=lambda item: (str(item.get("created_at") or item.get("time") or ""), -int(item.get("quality_score") or item.get("score_value") or 0)))[0]


def conversation_dedupe_key(item: dict[str, Any]) -> str:
    conversation_id = str(item.get("conversation_id") or "").strip()
    post_id = str(item.get("post_id") or "").strip()
    return conversation_id if conversation_id and conversation_id != post_id else ""


def is_earlier_conversation_item(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_time = str(candidate.get("created_at") or candidate.get("time") or "")
    current_time = str(current.get("created_at") or current.get("time") or "")
    if candidate_time and current_time and candidate_time != current_time:
        return candidate_time < current_time
    return int(candidate.get("quality_score") or candidate.get("score_value") or 0) > int(
        current.get("quality_score") or current.get("score_value") or 0
    )


def should_fetch_context(post: dict[str, Any], score: int, allow_anchor_threads: bool = False) -> bool:
    conversation_id = str(post.get("conversation_id") or "")
    post_id = str(post.get("post_id") or "")
    if not conversation_id:
        return False
    if is_competitor_post(post) and context_views(post) < COMPETITOR_CONTEXT_MIN_VIEWS:
        return False
    has_reply_shape = allow_anchor_threads or conversation_id != post_id or bool(leading_mention(post))
    if not has_reply_shape:
        return False
    followers = context_followers(post)
    return score >= CONTEXT_SCORE_THRESHOLD or followers >= CONTEXT_FOLLOWER_THRESHOLD


def is_competitor_post(post: dict[str, Any]) -> bool:
    return str(post.get("brand") or "").strip().lower() in {"temu", "competitor"}


def context_views(post: dict[str, Any]) -> int:
    metrics = post.get("metrics") or {}
    value = metrics.get("views", metrics.get("total_views", post.get("view_count", post.get("views", 0))))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def context_followers(post: dict[str, Any]) -> int:
    return int(post.get("author_followers") or post.get("author", {}).get("followers") or 0)


def competitor_context_score(post: dict[str, Any]) -> int:
    if post.get("brand") != "temu":
        return 0
    metrics = post.get("metrics", {})
    interactions = int(metrics.get("likes") or 0) + int(metrics.get("reposts") or 0) + int(metrics.get("replies") or 0) + int(metrics.get("quotes") or 0)
    return min(100, 55 + round(interactions / 8))


def leading_mention(post: dict[str, Any]) -> str:
    text = str(post.get("text") or post.get("clean_text") or post.get("translation_zh") or "").strip()
    if not text.startswith("@"):
        return ""
    handle = text.split(maxsplit=1)[0].lstrip("@")
    return handle if handle and len(handle) <= 20 else ""


def prepare_context_rows(rows: list[dict[str, Any]], translation_service: TranslationService | None = None) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        post_id = str(row.get("post_id") or row.get("url") or "")
        if not post_id or post_id in seen:
            continue
        seen.add(post_id)
        clean_text = decoded_text(row.get("clean_text") or row.get("text") or "")
        item = {
            **row,
            "text": decoded_text(row.get("text") or ""),
            "clean_text": clean_text,
            "translation_zh": row.get("translation_zh") or "",
            "translation_status": row.get("translation_status", "pending"),
        }
        prepared.append(item)
    return sorted(prepared, key=lambda item: str(item.get("created_at") or ""))


def filter_context_noise(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    filtered = []
    removed = 0
    for row in rows:
        if is_low_quality_context_row(row):
            removed += 1
            continue
        filtered.append(row)
    return filtered, removed


def is_low_quality_context_row(row: dict[str, Any]) -> bool:
    text = " ".join(
        decoded_text(value)
        for value in (row.get("translation_zh"), row.get("clean_text"), row.get("text"))
        if value
    )
    compact = re.sub(r"\s+", "", text)
    if any(pattern.search(compact) for pattern in LOW_QUALITY_CONTEXT_PATTERNS):
        return True
    profile = " ".join(
        decoded_text(value)
        for value in (row.get("author_name"), row.get("author_handle"), row.get("author_bio"))
        if value
    )
    compact_profile = re.sub(r"\s+", "", profile)
    return any(pattern.search(compact_profile) for pattern in LOW_QUALITY_CONTEXT_PROFILE_PATTERNS)


def build_context_for_post(
    anchor: dict[str, Any],
    rows: list[dict[str, Any]],
    summary_service: TranslationService | None = None,
) -> dict[str, Any] | None:
    anchor_id = str(anchor.get("post_id") or "")
    if not anchor_id:
        return None
    sorted_rows = sorted(rows, key=lambda item: str(item.get("created_at") or ""))
    anchor_index = next((index for index, row in enumerate(sorted_rows) if str(row.get("post_id")) == anchor_id), None)
    if anchor_index is None:
        sorted_rows = sorted([*sorted_rows, anchor], key=lambda item: str(item.get("created_at") or ""))
        anchor_index = next((index for index, row in enumerate(sorted_rows) if str(row.get("post_id")) == anchor_id), None)
    if anchor_index is None:
        return None

    before = sorted_rows[max(0, anchor_index - CONTEXT_BEFORE_LIMIT) : anchor_index]
    after = sorted_rows[anchor_index + 1 : anchor_index + 1 + CONTEXT_AFTER_LIMIT]
    window = [*before, sorted_rows[anchor_index], *after]
    apply_context_translations(window, summary_service)
    summary = summarize_context(anchor, before, after, summary_service)
    return {
        "conversation_id": anchor.get("conversation_id", ""),
        "anchor_post_id": anchor_id,
        "summary_zh": summary["summary_zh"],
        "summary_status": summary["status"],
        "posts": [context_item(row) for row in window],
    }


def summarize_context(
    anchor: dict[str, Any],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    summary_service: TranslationService | None = None,
) -> dict[str, str]:
    fallback = heuristic_context_summary(anchor, before, after)
    if not can_generate_context_summary(summary_service):
        return {"summary_zh": fallback, "status": "fallback"}
    try:
        generated = model_context_summary(anchor, before, after, summary_service)
    except Exception:
        return {"summary_zh": fallback, "status": "fallback"}
    if not generated:
        return {"summary_zh": fallback, "status": "fallback"}
    return {"summary_zh": trim_summary(generated), "status": "model"}


def heuristic_context_summary(anchor: dict[str, Any], before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    author = anchor.get("author", {}).get("handle") or anchor.get("author_handle") or "该用户"
    text = f"{anchor.get('translation_zh') or ''} {anchor.get('clean_text') or anchor.get('text') or ''}"
    lower = text.lower()
    if any(term in lower for term in ("价格", "price", "voordeliger", "half")) and any(term in lower for term in ("配送", "delivery", "levering")):
        angle = "价格和配送优势"
    elif "joybuy" in lower or "主品牌" in text:
        angle = "主品牌相关信息"
    else:
        angle = "相关信息"
    before_hint = short_context_hint(before[-2:])
    after_hint = short_context_hint(after[:2])
    lead = f"前文主要在讨论{before_hint}" if before_hint else ("这段对话原本围绕其他话题展开" if before else "这段对话中")
    follow = f"；后续回应继续围绕{after_hint}" if after_hint else ("，后续有人回应并继续讨论" if after else "")
    summary = f"{lead}，@{author}把话题转到{angle}，收录帖可帮助判断该提及是在回复链中自然出现，而非孤立广告式发布{follow}。"
    return trim_summary(summary)


def can_generate_context_summary(summary_service: TranslationService | None) -> bool:
    if not model_context_summary_enabled():
        return False
    return bool(
        summary_service
        and getattr(summary_service, "configured", False)
        and getattr(summary_service, "api_key", None)
        and getattr(summary_service, "endpoint", None)
        and getattr(summary_service, "model", None)
    )


def model_context_summary_enabled() -> bool:
    raw = str(os.getenv("CONVERSATION_CONTEXT_MODEL_SUMMARY") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "local"}


def apply_context_translations(window: list[dict[str, Any]], summary_service: TranslationService | None) -> None:
    if not summary_service or not getattr(summary_service, "configured", False):
        return
    if str(os.getenv("CONVERSATION_CONTEXT_TRANSLATE_POSTS") or "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    original_timeout = getattr(summary_service, "timeout_seconds", None)
    if original_timeout:
        summary_service.timeout_seconds = min(
            int(original_timeout),
            positive_int_env("CONVERSATION_CONTEXT_TRANSLATION_TIMEOUT_SECONDS", CONTEXT_TRANSLATION_TIMEOUT_SECONDS),
        )
    try:
        apply_translations(window, summary_service)
    except Exception:
        return
    finally:
        if original_timeout:
            summary_service.timeout_seconds = original_timeout


def model_context_summary(
    anchor: dict[str, Any],
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    summary_service: TranslationService,
) -> str:
    request_body = {
        "model": getattr(summary_service, "model"),
        "stream": False,
        "input": context_summary_prompt(anchor, before, after),
    }
    request = urllib.request.Request(
        str(getattr(summary_service, "endpoint")),
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {getattr(summary_service, 'api_key')}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = min(
        positive_int_env("CONVERSATION_CONTEXT_SUMMARY_TIMEOUT_SECONDS", CONTEXT_SUMMARY_TIMEOUT_SECONDS),
        int(getattr(summary_service, "timeout_seconds", CONTEXT_SUMMARY_TIMEOUT_SECONDS) or CONTEXT_SUMMARY_TIMEOUT_SECONDS),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, socket.timeout, TimeoutError, json.JSONDecodeError) as error:
        raise RuntimeError("conversation context summary failed") from error
    return parse_summary_response(response_output_text(payload))


def context_summary_prompt(anchor: dict[str, Any], before: list[dict[str, Any]], after: list[dict[str, Any]]) -> str:
    posts = []
    window = [*before[-8:], anchor, *after[:8]]
    anchor_id = str(anchor.get("post_id") or "")
    before_ids = {str(post.get("post_id") or "") for post in before}
    for post in window:
        post_id = str(post.get("post_id") or "")
        posts.append(
            {
                "role": "anchor" if post_id == anchor_id else ("before" if post_id in before_ids else "after"),
                "author": post.get("author", {}).get("handle") or post.get("author_handle") or post.get("author_name") or "",
                "time": post.get("created_at") or "",
                "text": post.get("translation_zh") or post.get("clean_text") or post.get("text") or "",
            }
        )
    input_payload = json.dumps(posts, ensure_ascii=False)
    return (
        "你是品牌海外舆情分析助手。请根据同一 X 对话中收录帖前后的公开发言，"
        "用简体中文生成一段不超过200字的上下文摘要。摘要要更具体：说明前文主要话题、"
        "收录帖如何把话题转向品牌/商品/价格/配送/体验，后续是否有人回应或继续补充，"
        "以及这段上下文对判断该舆情真实性、情绪或传播价值有什么帮助。"
        "不要输出标题、标签、风险等级、JSON 或项目符号；不要臆测未出现的信息；不要超过200字。\n\n"
        f"收录帖 ID：{anchor_id}\n对话片段 JSON：\n{input_payload}"
    )


def parse_summary_response(text: str) -> str:
    stripped = re.sub(r"^```(?:json|text)?|```$", "", str(text or "").strip(), flags=re.IGNORECASE).strip()
    if not stripped:
        return ""
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return trim_summary(stripped)
    if isinstance(payload, dict):
        for key in ("summary_zh", "summary", "text"):
            value = str(payload.get(key) or "").strip()
            if value:
                return trim_summary(value)
    if isinstance(payload, str):
        return trim_summary(payload)
    return ""


def trim_summary(value: str) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    compact = compact.strip("「」\"'` ")
    return compact[:CONTEXT_SUMMARY_CHAR_LIMIT]


def short_context_hint(posts: list[dict[str, Any]]) -> str:
    snippets = []
    for post in posts:
        text = str(post.get("translation_zh") or post.get("clean_text") or post.get("text") or "").strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            snippets.append(text[:34])
    return " / ".join(snippets)[:80]


def positive_int_env(name: str, fallback: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    return max(1, value)


def context_fetch_limit() -> int:
    return positive_int_env("CONVERSATION_CONTEXT_FETCH_LIMIT", CONTEXT_FETCH_LIMIT)


def optional_positive_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def configured_target_post_ids() -> set[str]:
    raw = os.getenv("CONVERSATION_CONTEXT_TARGET_POST_IDS") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def context_item(post: dict[str, Any]) -> dict[str, Any]:
    author = post.get("author") or {}
    metrics = post.get("metrics") or {
        "likes": post.get("like_count", 0),
        "reposts": post.get("repost_count", 0),
        "replies": post.get("reply_count", 0),
        "quotes": post.get("quote_count", 0),
        "bookmarks": post.get("bookmark_count"),
        "views": post.get("view_count"),
    }
    translation_zh, translation_status = context_translation_fields(post)
    return {
        "post_id": post.get("post_id"),
        "url": post.get("url", ""),
        "created_at": post.get("created_at"),
        "text": decoded_text(post.get("clean_text") or post.get("text") or ""),
        "original_text": decoded_text(post.get("text") or ""),
        "translation_zh": translation_zh,
        "translation_status": translation_status,
        "author_name": author.get("name") or post.get("author_name") or post.get("author_handle"),
        "author_handle": author.get("handle") or post.get("author_handle"),
        "author_avatar_url": author.get("avatar_url") or post.get("author_avatar_url"),
        "author_followers": author.get("followers", post.get("author_followers", 0)),
        "author_following": author.get("following", post.get("author_following", 0)),
        "author_bio": author.get("bio", post.get("author_bio", "")),
        "author_location": author.get("location", post.get("author_location", "")),
        "author_joined_at": author.get("joined_at", post.get("author_joined_at", "")),
        "author_verified": author.get("verified", post.get("author_verified", False)),
        "links": post.get("links", []),
        "media": context_media_items(post),
        "metrics": metrics,
    }


def context_translation_fields(post: dict[str, Any]) -> tuple[str, str]:
    text = decoded_text(post.get("clean_text") or post.get("text") or "")
    original_text = decoded_text(post.get("text") or "")
    supplied = decoded_text(post.get("translation_zh") or "")
    probe = {
        "language": post.get("language") or "",
        "clean_text": text or original_text,
        "text": original_text,
    }
    if supplied and (not needs_translation(probe) or CHINESE_RE.search(supplied)):
        return supplied, str(post.get("translation_status") or "unknown")
    if not needs_translation(probe):
        return text or original_text, "source_chinese"
    return fallback_context_translation(text or original_text), "fallback_summary"


def fallback_context_translation(text: str) -> str:
    compact = re.sub(r"\s+", " ", decoded_text(text)).strip()
    if not compact:
        return "该上下文帖没有可翻译文本。"
    if len(compact) <= 80:
        return f"该上下文帖为非中文简短内容：{compact}"
    return f"该上下文帖为非中文长内容，自动翻译暂不可用；请切换原文查看完整内容。原文开头：{compact[:120]}"


def decoded_text(value: Any) -> str:
    return html.unescape(str(value or ""))


def context_media_items(post: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for item in post.get("media", []) or []:
        if isinstance(item, str):
            items.append({"url": item, "type": "image"})
        elif isinstance(item, dict):
            url = (
                item.get("media_url_https")
                or item.get("media_url")
                or item.get("mediaUrlHttps")
                or item.get("mediaUrl")
                or item.get("preview_image_url")
                or item.get("previewImageUrl")
                or item.get("thumbnail_url")
                or item.get("thumbnailUrl")
                or item.get("image_url")
                or item.get("imageUrl")
                or item.get("url")
                or item.get("src")
            )
            if not url:
                continue
            media_type = str(item.get("type") or item.get("media_type") or item.get("mediaType") or "image")
            payload: dict[str, Any] = {"url": url, "type": media_type}
            preview_url = (
                item.get("media_url_https")
                or item.get("media_url")
                or item.get("mediaUrlHttps")
                or item.get("mediaUrl")
                or item.get("preview_image_url")
                or item.get("previewImageUrl")
                or item.get("thumbnail_url")
                or item.get("thumbnailUrl")
            )
            if preview_url:
                payload["preview_image_url"] = preview_url
                payload["media_url_https"] = preview_url
            video_info = item.get("video_info") or item.get("videoInfo")
            if video_info:
                payload["video_info"] = video_info
            expanded_url = item.get("expanded_url") or item.get("expandedUrl")
            if expanded_url:
                payload["expanded_url"] = expanded_url
            items.append(payload)
    return items[:4]
