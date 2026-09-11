from __future__ import annotations

import html
import json
import math
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from src.adapters.x_source_base import ProviderBudgetExceeded
from src.pipeline.content_policy import PLATFORM_HARD_NOISE_TERMS, platform_noise_reason
from src.pipeline.conversation_context import (
    attach_conversation_contexts,
    dedupe_contextual_items_keep_earliest,
    dedupe_conversation_items_keep_earliest,
    strip_media_placeholder_urls,
)
from src.pipeline.dashboard_builder import write_data_bundle
from src.pipeline.lazy_payloads import shard_json_file
from src.pipeline.translation import apply_translations, translation_report
from src.utils.config import load_project_json
from src.utils.io import read_json, write_json
from src.utils.time import beijing_label, now_utc, to_iso


PLATFORM_KEY = "xiaohongshu"
DEFAULT_MAX_ITEMS = None
DEFAULT_MAX_REQUESTS = 30
DEFAULT_QUERY_ROUNDS = 1
DEFAULT_MAX_PAGES_PER_QUERY_ROUND = 3
# The provider API requires an item limit, while this workflow is bounded by
# pages. This ceiling is intentionally unreachable within three source pages.
PLATFORM_QUERY_ITEM_LIMIT = 1_000_000
DEFAULT_MIN_VIEWS = 100
DEFAULT_MIN_LIKES = 1
PLATFORM_DATA_ROOT = Path("platform-trends")
PLATFORM_SEMANTIC_CONFIDENCE = 0.65
PLATFORM_SEMANTIC_NEGATIVE_CONFIDENCE = 0.80
PLATFORM_SEMANTIC_RULE_FALLBACK_SCORE = 75
PLATFORM_SEMANTIC_TEXT_LIMIT = 3000
PLATFORM_REJECTION_AUDIT_RETENTION_DAYS = 7

# These are scoring signals only. Keeping them out of the source queries avoids
# broadening collection with generic AI-tool posts, while allowing an already
# fetched post to reach semantic review when it explicitly applies the method
# to Xiaohongshu.
PLATFORM_REUSABLE_CONTENT_TERMS = [
    "提示词",
    "分镜",
    "脚本",
    "内容模板",
    "配图",
    "工作流",
    "内容生产",
    "内容形式",
    "prompt",
    "workflow",
]

PLATFORM_ACCEPTANCE_PATH_TOPICS = {
    "platform_update": "平台规则",
    "tool_resource": "爆文与内容结构",
    "monetization_opportunity": "变现",
    "case_lead": "案例复盘",
    "platform_observation": "爆文与内容结构",
}
PLATFORM_TYPED_CONTENT_TYPES = frozenset(
    {
        "platform_update",
        "method_case",
        "tool_resource",
        "monetization_opportunity",
        "case_lead",
        "platform_observation",
    }
)
PLATFORM_REVIEW_RELATIONS = frozenset({"central", "directly_applicable"})

PLATFORM_REJECTION_REASON_LABELS = {
    "missing_required_terms": "未同时命中小红书与目标主题",
    "article_content_unavailable": "数据源未返回长文正文，暂待解析",
    "platform_not_central": "小红书不是正文核心对象",
    "content_policy": "命中低俗、敏感或垃圾内容规则",
    "excluded_noise": "命中排除词且缺少明确方法信息",
    "short_reaction": "短句、感叹或仅附链接，缺少可复用信息",
    "insufficient_method_value": "方法论结构或信息密度不足",
    "conversation_duplicate": "同一上下文仅保留最早发布的一条",
    "context_duplicate": "完整上下文重叠，仅保留最早发布的一条",
    "low_value": "模型判定为低价值内容",
    "not_central_subject": "模型判定小红书不是正文核心对象",
    "outside_target_domain": "模型判定不属于目标情报方向",
    "not_substantive": "模型判定缺少实质方法或案例",
    "low_confidence": "模型判断置信度不足",
    "semantic_rejected": "未通过模型价值复审",
    "strict_fallback_rejected": "模型不可用时未通过严格兜底规则",
    "final_filter": "最终结果未保留该内容",
}


TOPIC_TERMS = {
    "账号冷启动": [
        "养号",
        "起号",
        "冷启动",
        "涨粉",
        "账号获取",
        "买号",
        "租号",
        "老号",
        "白号",
        "account growth",
        "grow account",
        "cold start",
        "account acquisition",
        "buy account",
        "aged account",
        "followers",
    ],
    "爆文与内容结构": [
        "爆文",
        "笔记",
        "选题",
        "标题",
        "封面",
        "内容定位",
        "viral",
        "content",
        "post structure",
        "hook",
        "提示词",
        "分镜",
        "脚本",
        "内容模板",
        "工作流",
        "社媒运营",
        "prompt",
        "workflow",
    ],
    "流量机制": [
        "流量",
        "算法",
        "推荐",
        "曝光",
        "traffic",
        "algorithm",
        "distribution",
        "reach",
    ],
    "风控对抗": [
        "风控",
        "风控对抗",
        "限流",
        "封号",
        "违规",
        "审核",
        "敏感词",
        "账号安全",
        "risk control",
        "anti-risk",
        "account safety",
    ],
    "平台规则": [
        "平台规则",
        "社区规范",
        "规则",
        "审核规则",
        "推荐规则",
        "内容规则",
        "违规规则",
        "platform rules",
        "platform policy",
        "community guideline",
        "policy",
    ],
    "矩阵": [
        "矩阵",
        "账号矩阵",
        "内容矩阵",
        "批量账号",
        "矩阵号",
        "matrix",
        "account matrix",
        "content matrix",
    ],
    "变现": [
        "变现",
        "变现路径",
        "商单",
        "带货",
        "店铺",
        "电商",
        "monetization",
        "make money",
        "affiliate",
        "commerce",
    ],
    "私域引流": [
        "引流",
        "私域",
        "社群",
        "微信",
        "leads",
        "funnel",
        "community",
        "private domain",
    ],
    "案例复盘": [
        "案例",
        "复盘",
        "拆解",
        "实操",
        "case study",
        "playbook",
        "breakdown",
        "experiment",
        "results",
    ],
    "逆向与改机": [
        "小红书逆向",
        "小红书改机",
        "逆向工程",
        "app逆向",
        "客户端逆向",
        "协议分析",
        "抓包",
        "参数签名",
        "接口签名",
        "设备指纹",
        "设备环境",
        "设备伪装",
        "机型伪装",
        "一机一号",
        "xiaohongshu reverse engineering",
        "rednote reverse engineering",
        "device fingerprint",
        "device spoofing",
    ],
}

PLATFORM_TAG_ALIASES = {
    "养号": "账号冷启动",
    "起号": "账号冷启动",
    "冷启动": "账号冷启动",
    "涨粉": "账号冷启动",
    "账号获取": "账号冷启动",
    "买号": "账号冷启动",
    "租号": "账号冷启动",
    "老号": "账号冷启动",
    "白号": "账号冷启动",
    "爆文": "爆文与内容结构",
    "笔记": "爆文与内容结构",
    "选题": "爆文与内容结构",
    "标题": "爆文与内容结构",
    "封面": "爆文与内容结构",
    "内容定位": "爆文与内容结构",
    "流量": "流量机制",
    "算法": "流量机制",
    "推荐": "流量机制",
    "曝光": "流量机制",
    "限流": "风控对抗",
    "风控": "风控对抗",
    "风控对抗": "风控对抗",
    "封号": "风控对抗",
    "违规": "风控对抗",
    "审核": "风控对抗",
    "敏感词": "风控对抗",
    "账号安全": "风控对抗",
    "平台规则": "平台规则",
    "社区规范": "平台规则",
    "规则": "平台规则",
    "审核规则": "平台规则",
    "推荐规则": "平台规则",
    "内容规则": "平台规则",
    "违规规则": "平台规则",
    "矩阵": "矩阵",
    "账号矩阵": "矩阵",
    "内容矩阵": "矩阵",
    "批量账号": "矩阵",
    "矩阵号": "矩阵",
    "变现路径": "变现",
    "商单": "变现",
    "带货": "变现",
    "店铺": "变现",
    "电商": "变现",
    "引流": "私域引流",
    "私域": "私域引流",
    "社群": "私域引流",
    "微信": "私域引流",
    "案例": "案例复盘",
    "复盘": "案例复盘",
    "拆解": "案例复盘",
    "实操": "案例复盘",
    "小红书逆向": "逆向与改机",
    "小红书改机": "逆向与改机",
    "逆向工程": "逆向与改机",
    "app逆向": "逆向与改机",
    "客户端逆向": "逆向与改机",
    "协议分析": "逆向与改机",
    "抓包": "逆向与改机",
    "参数签名": "逆向与改机",
    "接口签名": "逆向与改机",
    "设备指纹": "逆向与改机",
    "设备环境": "逆向与改机",
    "设备伪装": "逆向与改机",
    "机型伪装": "逆向与改机",
    "一机一号": "逆向与改机",
}

NOISE_TERMS = [
    "tiktok refugee",
    "refugees",
    "spy app",
    "privacy",
    "ccp",
    "ban",
    "download rednote",
    "coupon code",
    "promo code",
]

STRUCTURE_SIGNALS = [
    "how to",
    "step",
    "steps",
    "thread",
    "guide",
    "playbook",
    "framework",
    "checklist",
    "经验",
    "方法",
    "步骤",
    "复盘",
    "拆解",
    "总结",
    "实操",
    "提示词",
    "分镜",
    "脚本",
    "模板",
    "工作流",
    "账号画像",
    "prompt",
    "workflow",
]

PLATFORM_FOCUS_TERMS = [
    "养号",
    "起号",
    "冷启动",
    "涨粉",
    "爆文",
    "笔记",
    "选题",
    "标题",
    "封面",
    "内容定位",
    *PLATFORM_REUSABLE_CONTENT_TERMS,
    "流量",
    "账号运营",
    "运营",
    "矩阵",
    "账号矩阵",
    "内容矩阵",
    "风控",
    "风控对抗",
    "限流",
    "封号",
    "违规",
    "审核",
    "平台规则",
    "社区规范",
    "账号获取",
    "买号",
    "租号",
    "老号",
    "白号",
    "商单",
    "带货",
    "店铺",
    "小店",
    "电商",
    "变现",
    "引流",
    "私域",
    "投流",
    "推荐",
    "曝光",
    "算法",
    "完播",
    "收藏",
    "转化",
    "成交",
    "获客",
    "客单价",
    "营收",
    "收入",
    "收益",
    "售卖",
    "卖",
    "服务",
    "资料",
    "案例",
    "玩法",
    "方法",
    "教程",
    "拆解",
    "复盘",
    "经验",
    "策略",
    "路径",
    "growth",
    "grow",
    "monetization",
    "creator",
    "traffic",
    "algorithm",
    "risk control",
    "account safety",
    "platform policy",
    "account acquisition",
    "buy account",
    "account matrix",
    "commerce",
    "affiliate",
    "playbook",
    "case study",
    "strategy",
    "逆向工程",
    "app逆向",
    "客户端逆向",
    "协议分析",
    "抓包",
    "参数签名",
    "接口签名",
    "改机",
    "设备指纹",
    "设备环境",
    "设备伪装",
    "机型伪装",
    "一机一号",
    "reverse engineering",
    "device fingerprint",
    "device spoofing",
]


def platform_trends_enabled() -> bool:
    raw = str(os.getenv("BRAND_RADAR_PLATFORM_TRENDS") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def load_platform_config() -> dict[str, Any]:
    return load_project_json("platform_trends.local.json")


def apply_platform_runtime_limits(x_source: Any, config: dict[str, Any]) -> dict[str, Any]:
    platform = platform_config(config)
    configured = int(platform.get("max_source_requests_per_run") or DEFAULT_MAX_REQUESTS)
    max_requests = optional_int_env("BRAND_RADAR_PLATFORM_MAX_SOURCE_REQUESTS", configured)
    max_context_requests = optional_int_env("BRAND_RADAR_PLATFORM_MAX_CONTEXT_REQUESTS", None)
    if hasattr(x_source, "max_requests_per_run"):
        x_source.max_requests_per_run = max_requests
    if hasattr(x_source, "max_context_requests_per_run"):
        x_source.max_context_requests_per_run = max_context_requests
    return {
        "max_source_requests": max_requests,
        "max_context_requests": max_context_requests,
    }


def platform_query_request_allowance(x_source: Any, remaining_groups: int) -> int | None:
    """Reserve an even share of the remaining search budget for each query group."""
    max_requests = getattr(x_source, "max_requests_per_run", None)
    if max_requests is None:
        return None
    try:
        remaining = max(
            0,
            int(max_requests) - int(getattr(x_source, "requests_used", 0) or 0),
        )
    except (TypeError, ValueError):
        return None
    return remaining // max(1, int(remaining_groups))


def source_search_telemetry(x_source: Any) -> dict[str, Any]:
    stats = getattr(x_source, "last_search_stats", None)
    if not isinstance(stats, dict):
        return {"source_pages_used": None, "source_stop_reason": "unknown"}
    pages = stats.get("pages_used")
    try:
        pages_value = max(0, int(pages)) if pages is not None else None
    except (TypeError, ValueError):
        pages_value = None
    return {
        "source_pages_used": pages_value,
        "source_stop_reason": str(stats.get("stop_reason") or "unknown"),
    }


def search_platform_query_with_budget(
    x_source: Any,
    query: str,
    start_time: str,
    end_time: str,
    limit: int,
    request_allowance: int | None,
    page_cap: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run one query without allowing it to consume later groups' reserved requests."""
    original_max_requests = getattr(x_source, "max_requests_per_run", None)
    original_max_pages = getattr(x_source, "max_pages_per_query", None)
    has_page_cap = page_cap is not None and hasattr(x_source, "max_pages_per_query")
    requests_before = int(getattr(x_source, "requests_used", 0) or 0)
    can_apply_local_cap = original_max_requests is not None and hasattr(x_source, "requests_used")
    if has_page_cap:
        x_source.max_pages_per_query = max(1, int(page_cap))
    try:
        if not can_apply_local_cap or request_allowance is None:
            rows = x_source.search_posts(query, start_time, end_time, limit, query_type="Top")
            requests_after = int(getattr(x_source, "requests_used", requests_before) or requests_before)
            return rows, {
                "request_allowance": request_allowance,
                "requests_used": max(0, requests_after - requests_before),
                "request_budget_limited": False,
                **source_search_telemetry(x_source),
            }

        allowance = max(0, int(request_allowance))
        if allowance == 0:
            return [], {
                "request_allowance": 0,
                "requests_used": 0,
                "request_budget_limited": True,
                "source_pages_used": 0,
                "source_stop_reason": "request_budget",
            }

        global_max_requests = int(original_max_requests)
        local_max_requests = min(global_max_requests, requests_before + allowance)
        original_budget_exhausted = bool(getattr(x_source, "request_budget_exhausted", False))
        has_budget_flag = hasattr(x_source, "request_budget_exhausted")
        x_source.max_requests_per_run = local_max_requests
        if has_budget_flag and not original_budget_exhausted:
            x_source.request_budget_exhausted = False

        rows: list[dict[str, Any]] = []
        request_budget_limited = False
        try:
            try:
                rows = x_source.search_posts(query, start_time, end_time, limit, query_type="Top")
            except ProviderBudgetExceeded:
                request_budget_limited = True
            request_budget_limited = request_budget_limited or bool(
                getattr(x_source, "request_budget_exhausted", False)
            )
        finally:
            requests_after = int(getattr(x_source, "requests_used", requests_before) or requests_before)
            x_source.max_requests_per_run = original_max_requests
            if has_budget_flag:
                global_budget_exhausted = request_budget_limited and requests_after >= global_max_requests
                x_source.request_budget_exhausted = original_budget_exhausted or global_budget_exhausted

        return rows, {
            "request_allowance": allowance,
            "requests_used": max(0, requests_after - requests_before),
            "request_budget_limited": request_budget_limited,
            **source_search_telemetry(x_source),
        }
    finally:
        if has_page_cap:
            x_source.max_pages_per_query = original_max_pages


def platform_query_tasks(queries: list[str], rounds: int) -> list[tuple[int, int, str]]:
    return [
        (round_number, query_index, query)
        for round_number in range(1, max(1, int(rounds)) + 1)
        for query_index, query in enumerate(queries)
    ]


def collect_platform_trends(
    x_source: Any,
    translation_service: Any,
    provider: str,
    start: Any,
    end: Any,
    report_date: str,
    window_label: str,
    output_dir: str,
    audit_dir: str | None = None,
) -> dict[str, Any]:
    config = load_platform_config()
    platform = platform_config(config)
    runtime_limits = apply_platform_runtime_limits(x_source, config)
    configured_max_items = optional_config_int(platform.get("max_items_per_day"))
    max_items = optional_int_env("BRAND_RADAR_PLATFORM_MAX_ITEMS", configured_max_items)
    min_views = optional_int_env("BRAND_RADAR_PLATFORM_MIN_VIEWS", int(platform.get("min_views_per_item") or DEFAULT_MIN_VIEWS))
    min_likes = optional_int_env("BRAND_RADAR_PLATFORM_MIN_LIKES", int(platform.get("min_likes_per_item") or DEFAULT_MIN_LIKES))
    query_rounds = max(1, int(platform.get("query_rounds") or DEFAULT_QUERY_ROUNDS))
    max_pages_per_query_round = max(
        1,
        int(platform.get("max_pages_per_query_round") or DEFAULT_MAX_PAGES_PER_QUERY_ROUND),
    )
    max_items = max(1, max_items) if max_items else None
    min_views = max(0, min_views or 0)
    min_likes = max(0, min_likes or 0)

    selected: list[dict[str, Any]] = []
    metric_eligible_items: dict[str, dict[str, Any]] = {}
    rejection_details: dict[str, dict[str, Any]] = {}
    seen: set[str] = set()
    candidates_seen = 0
    metric_filtered = 0
    conversation_deduped = 0
    warnings: list[str] = []
    query_stats: list[dict[str, Any]] = []
    queries = build_platform_queries(platform)
    query_tasks = platform_query_tasks(queries, query_rounds)
    round_candidate_ids: dict[int, set[str]] = {round_number: set() for round_number in range(1, query_rounds + 1)}

    for task_index, (round_number, query_index, query) in enumerate(query_tasks):
        if source_request_limit_reached(x_source):
            break
        remaining_tasks = len(query_tasks) - task_index
        request_allowance = platform_query_request_allowance(x_source, remaining_tasks)
        if request_allowance is not None:
            request_allowance = min(max_pages_per_query_round, request_allowance)
        try:
            rows, query_request_stats = search_platform_query_with_budget(
                x_source,
                query,
                to_iso(start),
                to_iso(end),
                PLATFORM_QUERY_ITEM_LIMIT,
                request_allowance,
                page_cap=max_pages_per_query_round,
            )
        except ProviderBudgetExceeded as error:
            if not source_request_limit_reached(x_source) or not candidates_seen:
                warnings.append(str(error))
            break
        except RuntimeError as error:
            warnings.append(f"Platform trend collection stopped after error: {str(error)[:180]}")
            break

        accepted_for_query = 0
        inspected_for_query = 0
        metric_filtered_for_query = 0
        row_ids = {
            str(row.get("post_id") or row.get("url") or "").strip()
            for row in rows
            if str(row.get("post_id") or row.get("url") or "").strip()
        }
        prior_round_ids = set().union(
            *(round_candidate_ids[prior_round] for prior_round in range(1, round_number))
        ) if round_number > 1 else set()
        prior_round_duplicates = len(row_ids & prior_round_ids)
        round_candidate_ids[round_number].update(row_ids)
        unique_rows, query_uniqueness = unique_platform_query_rows(rows, seen)
        for post_id, row in unique_rows:
            candidates_seen += 1
            inspected_for_query += 1
            if not passes_platform_metric_gate(row, min_views, min_likes):
                metric_filtered += 1
                metric_filtered_for_query += 1
                continue
            item = normalize_platform_post(row, platform)
            item["_audit_query_group"] = platform_query_group_name(platform, query_index)
            item["_audit_query_round"] = round_number
            metric_eligible_items[post_id] = item
            decision = score_platform_post(item, platform)
            if decision["accepted"] and (max_items is None or len(selected) < max_items):
                item.update(decision["item"])
                selected.append(item)
                before_dedupe = {str(entry.get("post_id") or "") for entry in selected}
                selected, removed_duplicates = dedupe_conversation_items_keep_earliest(selected)
                conversation_deduped += removed_duplicates
                kept_after_dedupe = {str(entry.get("post_id") or "") for entry in selected}
                for removed_id in before_dedupe - kept_after_dedupe:
                    rejection_details[removed_id] = platform_rejection_detail(
                        "conversation_dedupe",
                        "conversation_duplicate",
                    )
                accepted_for_query += 1
            else:
                reason_code = str(decision.get("reason_code") or "final_filter")
                rejection_details[post_id] = platform_rejection_detail(
                    "pending_content" if reason_code == "article_content_unavailable" else "rule_filter",
                    reason_code,
                    details=decision.get("details") or {},
                )
        source_pages_used = query_request_stats.get("source_pages_used")
        query_stats.append(
            {
                "round": round_number,
                "query_group": platform_query_group_name(platform, query_index),
                "query_label": query_label(query),
                "page_target": max_pages_per_query_round,
                "fetched": len(rows),
                "group_unique_candidates": query_uniqueness["group_unique_candidates"],
                "new_unique_candidates": len(unique_rows),
                "within_query_duplicates": query_uniqueness["within_query_duplicates"],
                "inspected": inspected_for_query,
                "cross_query_duplicates": query_uniqueness["cross_query_duplicates"],
                "prior_round_duplicates": prior_round_duplicates,
                "missing_identifier": query_uniqueness["missing_identifier"],
                "metric_filtered": metric_filtered_for_query,
                "metric_eligible": inspected_for_query - metric_filtered_for_query,
                "accepted": accepted_for_query,
                "target_met": source_pages_used is not None and source_pages_used >= max_pages_per_query_round,
                "source_exhausted": (
                    not query_request_stats["request_budget_limited"]
                    and query_request_stats.get("source_stop_reason")
                    in {"empty_page", "missing_next_cursor", "unknown", None}
                ),
                **query_request_stats,
            }
        )

    if not candidates_seen and query_stats:
        append_unique_warning(warnings, "Platform trend source returned no candidates for all configured queries.")

    completed_tasks = {(int(entry["round"]), str(entry["query_group"])) for entry in query_stats}
    completed_groups = sum(
        1
        for query_index in range(len(queries))
        if any(
            (round_number, platform_query_group_name(platform, query_index)) in completed_tasks
            for round_number in range(1, query_rounds + 1)
        )
    )
    target_met_groups = sum(
        1
        for query_index in range(len(queries))
        if all(
            (round_number, platform_query_group_name(platform, query_index)) in completed_tasks
            for round_number in range(1, query_rounds + 1)
        )
    )
    round_stats = []
    prior_ids: set[str] = set()
    for round_number in range(1, query_rounds + 1):
        round_entries = [entry for entry in query_stats if int(entry["round"]) == round_number]
        round_ids = round_candidate_ids[round_number]
        round_stats.append(
            {
                "round": round_number,
                "queries_completed": len(round_entries),
                "requests_used": sum(int(entry.get("requests_used") or 0) for entry in round_entries),
                "pages_used": sum(int(entry.get("source_pages_used") or 0) for entry in round_entries),
                "raw_candidates_fetched": sum(int(entry.get("fetched") or 0) for entry in round_entries),
                "unique_candidates": len(round_ids),
                "overlap_with_prior_rounds": len(round_ids & prior_ids),
                "new_unique_candidates": len(round_ids - prior_ids),
            }
        )
        prior_ids.update(round_ids)

    selected.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    evidence_targets = [item for item in selected if platform_review_evidence_candidate(item)]
    review_evidence_status = attach_platform_context(
        evidence_targets,
        x_source,
        translation_service,
        start,
        end,
    )
    selected, semantic_review = apply_platform_semantic_review(
        selected,
        translation_service,
        rejection_details=rejection_details,
    )
    translation_status = apply_translations(selected, translation_service)
    remaining_context_items = [
        item
        for item in selected
        if not isinstance(item.get("conversation_context"), dict)
        or not item["conversation_context"].get("posts")
    ]
    final_context_status = attach_platform_context(
        remaining_context_items,
        x_source,
        translation_service,
        start,
        end,
    )
    context_status = merge_platform_context_statuses(
        review_evidence_status,
        final_context_status,
        selected,
    )
    before_context_dedupe = {str(entry.get("post_id") or "") for entry in selected}
    selected, context_deduped = dedupe_contextual_items_keep_earliest(selected)
    if context_deduped:
        conversation_deduped += context_deduped
        kept_after_context_dedupe = {str(entry.get("post_id") or "") for entry in selected}
        for removed_id in before_context_dedupe - kept_after_context_dedupe:
            rejection_details[removed_id] = platform_rejection_detail(
                "context_dedupe",
                "context_duplicate",
            )
        context_status["deduped_after_context"] = context_deduped
        refresh_context_status_for_items(context_status, selected)
        selected.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        translation_status = translation_report(selected, getattr(translation_service, "provider_name", "none"))
    audit_status: dict[str, Any] = {"enabled": False}
    if audit_dir:
        try:
            audit_payload = write_platform_rejection_audit(
                Path(audit_dir),
                report_date,
                window_label,
                metric_eligible_items,
                selected,
                rejection_details,
            )
            audit_status = {
                "enabled": True,
                "rejected_count": audit_payload["summary"]["rejected_count"],
                "pending_count": audit_payload["summary"].get("pending_count", 0),
                "retention_days": PLATFORM_REJECTION_AUDIT_RETENTION_DAYS,
            }
        except Exception as error:
            warnings.append(f"Platform rejection audit failed: {str(error)[:180]}")
            audit_status = {"enabled": True, "error": str(error)[:180]}
    status = collection_status(
        selected,
        candidates_seen,
        max_items,
        None,
        warnings,
        source_request_limit_reached=source_request_limit_reached(x_source),
        min_views=min_views,
        min_likes=min_likes,
        metric_filtered=metric_filtered,
        conversation_deduped=conversation_deduped,
        semantic_filtered=int(semantic_review.get("rejected_count") or 0),
        query_groups_completed=completed_groups,
        configured_query_groups=len(queries),
        query_targets_met=target_met_groups,
    )

    payload = {
        "platform": PLATFORM_KEY,
        "display_name": platform.get("display_name", "小红书"),
        "topic_label": platform.get("topic_label", "小红书增长方法"),
        "date": report_date,
        "generated_at": to_iso(now_utc()),
        "generated_at_label": beijing_label(now_utc()),
        "window_label": window_label,
        "items": public_platform_items(selected),
        "collection_status": {
            **public_platform_collection_status(status),
            "translation": public_translation_status(translation_status),
            "conversation_context": context_status,
            "semantic_review": public_semantic_review_status(semantic_review),
        },
        "summary": {
            "accepted": len(selected),
            "candidates_inspected": candidates_seen,
            "metric_filtered": metric_filtered,
            "conversation_deduped": conversation_deduped,
            "semantic_filtered": int(semantic_review.get("rejected_count") or 0),
            "max_items": max_items,
            "max_candidates": None,
            "max_candidates_per_query": None,
            "configured_query_groups": len(queries),
            "query_groups_completed": completed_groups,
            "query_targets_met": target_met_groups,
            "query_rounds": query_rounds,
            "max_pages_per_query_round": max_pages_per_query_round,
            "configured_query_tasks": len(query_tasks),
            "query_tasks_completed": len(query_stats),
            "page_targets_met": sum(1 for entry in query_stats if entry.get("target_met")),
            "round_stats": round_stats,
            "raw_candidates_fetched": sum(int(entry.get("fetched") or 0) for entry in query_stats),
            "group_unique_candidates_fetched": sum(
                int(entry.get("group_unique_candidates") or 0) for entry in query_stats
            ),
            "within_query_duplicates": sum(
                int(entry.get("within_query_duplicates") or 0) for entry in query_stats
            ),
            "cross_query_duplicates": sum(int(entry.get("cross_query_duplicates") or 0) for entry in query_stats),
            "max_source_requests": runtime_limits.get("max_source_requests"),
            "min_views": min_views,
            "min_likes": min_likes,
        },
    }
    write_platform_payload(Path(output_dir), payload)
    return {
        "status": status["status"],
        "accepted": len(selected),
        "candidates_inspected": candidates_seen,
        "metric_filtered": metric_filtered,
        "conversation_deduped": conversation_deduped,
        "warnings": warnings[:5],
        "provider": provider,
        "request_stats": platform_request_stats(x_source),
        "runtime_limits": runtime_limits,
        "query_stats": query_stats,
        "translation": translation_status,
        "conversation_context": context_status,
        "semantic_review": semantic_review,
        "review_evidence": review_evidence_status,
        "rejection_audit": audit_status,
    }


def platform_config(config: dict[str, Any]) -> dict[str, Any]:
    platforms = config.get("platforms") or {}
    platform = platforms.get(PLATFORM_KEY) or {}
    if not platform:
        raise RuntimeError(f"Missing platform trend config for {PLATFORM_KEY}")
    return platform


def build_platform_queries(platform: dict[str, Any]) -> list[str]:
    if platform.get("query_groups"):
        queries = []
        for group in platform["query_groups"]:
            aliases = group.get("query_aliases") or platform.get("query_aliases") or group.get("aliases") or platform.get("aliases") or []
            intents = group.get("intent_terms") or platform.get("intent_terms") or []
            excludes = group.get("exclude_terms") or platform.get("exclude_terms") or []
            queries.append(f"({_or_clause(aliases)}) ({_or_clause(intents)}) -filter:retweets {_negative_clause(excludes)}".strip())
        return [query for query in queries if query]
    aliases = platform.get("query_aliases") or platform.get("aliases") or []
    intents = platform.get("intent_terms") or []
    excludes = platform.get("exclude_terms") or []
    return [f"({_or_clause(aliases)}) ({_or_clause(intents)}) -filter:retweets {_negative_clause(excludes)}".strip()]


def effective_platform_intent_terms(platform: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    for term in platform.get("intent_terms") or []:
        value = str(term).strip().lower()
        if value and value not in terms:
            terms.append(value)
    for group in platform.get("query_groups") or []:
        for term in group.get("intent_terms") or []:
            value = str(term).strip().lower()
            if value and value not in terms:
                terms.append(value)
    return terms


def platform_query_group_name(platform: dict[str, Any], query_index: int) -> str:
    groups = platform.get("query_groups") or []
    if query_index < len(groups):
        name = str(groups[query_index].get("name") or "").strip()
        if name:
            return name
    return f"query_{query_index + 1}"


def unique_platform_query_rows(
    rows: list[dict[str, Any]],
    globally_seen: set[str],
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, int]]:
    """Separate within-query duplicates from candidates repeated across query groups."""
    query_seen: set[str] = set()
    unique_rows: list[tuple[str, dict[str, Any]]] = []
    within_query_duplicates = 0
    cross_query_duplicates = 0
    missing_identifier = 0
    for row in rows:
        post_id = str(row.get("post_id") or row.get("url") or "").strip()
        if not post_id:
            missing_identifier += 1
            continue
        if post_id in query_seen:
            within_query_duplicates += 1
            continue
        query_seen.add(post_id)
        if post_id in globally_seen:
            cross_query_duplicates += 1
            continue
        globally_seen.add(post_id)
        unique_rows.append((post_id, row))
    return unique_rows, {
        "group_unique_candidates": len(query_seen),
        "within_query_duplicates": within_query_duplicates,
        "cross_query_duplicates": cross_query_duplicates,
        "missing_identifier": missing_identifier,
    }


def normalize_platform_post(post: dict[str, Any], platform: dict[str, Any]) -> dict[str, Any]:
    clean_text = clean_post_text(post)
    metrics = {
        "likes": int(post.get("like_count") or 0),
        "reposts": int(post.get("repost_count") or 0),
        "replies": int(post.get("reply_count") or 0),
        "quotes": int(post.get("quote_count") or 0),
        "bookmarks": post.get("bookmark_count"),
        "views": post.get("view_count"),
    }
    return {
        "post_id": post.get("post_id"),
        "created_at": post.get("created_at"),
        "time": post.get("created_at"),
        "url": post.get("url"),
        "external_href": post.get("url"),
        "language": post.get("language") or "und",
        "text": post.get("text") or "",
        "clean_text": clean_text,
        "original_text": clean_text,
        "translation_zh": "",
        "translation_status": "pending",
        "summary_zh": "X 上关于小红书增长、运营或变现的方法论分享。",
        "platform": PLATFORM_KEY,
        "brand": "platform_xiaohongshu",
        "source_type": platform.get("topic_label", "平台流变"),
        "badge": "小红书",
        "author_id": post.get("author_id"),
        "author_name": post.get("author_name"),
        "author_handle": post.get("author_handle"),
        "author_avatar_url": post.get("author_avatar_url"),
        "author_followers": post.get("author_followers") or 0,
        "author_following": post.get("author_following") or 0,
        "author_bio": post.get("author_bio") or "",
        "author_location": post.get("author_location") or "",
        "author_joined_at": post.get("author_joined_at") or "",
        "author_verified": bool(post.get("author_verified")),
        "reply_to_post_id": post.get("reply_to_post_id"),
        "reply_to_handle": post.get("reply_to_handle"),
        "quoted_post_id": post.get("quoted_post_id"),
        "conversation_id": post.get("conversation_id"),
        "media": post.get("media") or [],
        "links": post.get("links") or [],
        "metrics": metrics,
        "post_metrics": metrics,
        "is_relevant": True,
    }


def passes_platform_metric_gate(post: dict[str, Any], min_views: int, min_likes: int) -> bool:
    views = raw_metric(post, "views", "view_count", "total_views")
    likes = raw_metric(post, "likes", "like_count")
    return views >= min_views and likes >= min_likes


def raw_metric(post: dict[str, Any], *keys: str) -> int:
    metrics = post.get("metrics") or post.get("post_metrics") or {}
    for key in keys:
        value = post.get(key)
        if value is None:
            value = metrics.get(key)
        if value is None:
            continue
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            continue
    return 0


def score_platform_post(item: dict[str, Any], platform: dict[str, Any]) -> dict[str, Any]:
    text = combined_text(item)
    lower = text.lower()
    if platform_article_content_unavailable(item):
        return rejected_platform_decision("article_content_unavailable")
    aliases = [str(term).lower() for term in platform.get("aliases") or []]
    intent_terms = effective_platform_intent_terms(platform)
    exclude_terms = [str(term).lower() for term in [*NOISE_TERMS, *(platform.get("exclude_terms") or [])]]
    alias_hits = matched_terms(lower, aliases)
    intent_hits = matched_terms(lower, intent_terms)
    reusable_content_hits = matched_terms(lower, PLATFORM_REUSABLE_CONTENT_TERMS)
    case_evidence = platform_case_evidence_signal(lower, aliases)
    risk_evidence = platform_risk_evidence_signal(lower, aliases)
    acceptance_path = platform_acceptance_path(item, lower, aliases)
    hard_noise_hits = matched_terms(lower, PLATFORM_HARD_NOISE_TERMS)
    policy_reason = platform_noise_reason(text) or platform_specific_hard_risk_reason(text)
    if hard_noise_hits or policy_reason:
        return rejected_platform_decision(
            "content_policy",
            {"policy_reason": policy_reason or "hard_noise_term", "matched_terms": hard_noise_hits},
        )
    if not intent_hits:
        intent_hits = reusable_content_hits
    if not intent_hits and case_evidence:
        intent_hits = ["platform_case_evidence"]
    if not intent_hits and risk_evidence:
        intent_hits = ["platform_risk_evidence"]
    if not intent_hits and acceptance_path:
        intent_hits = [acceptance_path]
    if not alias_hits or not intent_hits:
        return rejected_platform_decision(
            "missing_required_terms",
            {"platform_terms": alias_hits, "intent_terms": intent_hits},
        )
    if not platform_focus_signal(lower, aliases) and not case_evidence and not risk_evidence and not acceptance_path:
        return rejected_platform_decision("platform_not_central")
    excluded_hits = matched_terms(lower, exclude_terms)
    if excluded_hits and not strong_method_signal(lower):
        return rejected_platform_decision("excluded_noise", {"matched_terms": excluded_hits})

    topics = matched_topics(lower)
    acceptance_topic = PLATFORM_ACCEPTANCE_PATH_TOPICS.get(acceptance_path or "")
    if acceptance_topic and acceptance_topic not in topics:
        topics.insert(0, acceptance_topic)
    if case_evidence and "案例复盘" not in topics:
        topics.append("案例复盘")
    if risk_evidence and "风控对抗" not in topics:
        topics.append("风控对抗")
    structure_score = method_structure_score(lower)
    if case_evidence or risk_evidence or acceptance_path:
        structure_score = max(12, structure_score)
    if is_short_reaction_link(item, lower, topics, structure_score):
        return rejected_platform_decision("short_reaction", {"structure_score": structure_score})
    metric_score = propagation_score(item)
    topic_score = min(30, len(intent_hits) * 6 + len(topics) * 4)
    score = min(100, 35 + topic_score + structure_score + metric_score)
    if score < 62:
        return rejected_platform_decision(
            "insufficient_method_value",
            {"quality_score": score, "structure_score": structure_score, "metric_score": metric_score},
        )

    topic = topics[0] if topics else "小红书方法论"
    return {
        "accepted": True,
        "item": {
            "topic": topic,
            "quality_score": score,
            "score_value": score,
            "score_label": "GQS",
            "quality_label": "黄金内容",
            "selected_reason": selection_reason(topic, structure_score, metric_score, acceptance_path),
            "reusable_takeaway": reusable_takeaway(topic),
            "tags": platform_item_tags(topic, topics),
            "acceptance_path": acceptance_path or "method_case",
            "source_status": platform_source_status(text),
        },
    }


def rejected_platform_decision(reason_code: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "accepted": False,
        "item": {},
        "reason_code": reason_code,
        "details": details or {},
    }


def platform_article_content_unavailable(item: dict[str, Any]) -> bool:
    raw_text = str(item.get("clean_text") or item.get("text") or "")
    visible_text = re.sub(r"https?://\S+", "", raw_text).strip()
    if len(re.findall(r"[a-z0-9\u3400-\u9fff]", visible_text.lower())) > 8:
        return False
    media = item.get("media") or []
    has_article_card = any(
        isinstance(entry, dict) and str(entry.get("source") or "").lower() == "card"
        for entry in media
    )
    links = [str(link or "").lower() for link in item.get("links") or []]
    has_article_link = any("x.com/i/article/" in link or "twitter.com/i/article/" in link for link in links)
    return has_article_card or has_article_link


def apply_platform_semantic_review(
    items: list[dict[str, Any]],
    review_service: Any,
    rejection_details: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not items:
        return [], semantic_review_report("not_needed", 0, 0, 0)
    if not semantic_review_enabled():
        return items, semantic_review_report("disabled", 0, 0, len(items))

    reviewer = getattr(review_service, "classify_platform_batch", None)
    decisions: dict[str, dict[str, Any]] = {}
    if callable(reviewer) and bool(getattr(review_service, "configured", False)):
        review_input = [platform_semantic_review_input(item, index) for index, item in enumerate(items)]
        try:
            decisions = reviewer(review_input) or {}
        except Exception as error:
            setattr(review_service, "classification_last_error", str(error)[:300])

    kept: list[dict[str, Any]] = []
    reviewed_count = 0
    rejected_count = 0
    fallback_count = 0
    overridden_count = 0
    rejection_reasons: dict[str, int] = {}
    override_reasons: dict[str, int] = {}
    for index, item in enumerate(items):
        item_id = str(item.get("post_id") or index)
        decision = decisions.get(item_id)
        if decision:
            reviewed_count += 1
            override_reason = ""
            if not semantic_model_accepts(decision):
                override_reason = semantic_rule_override_reason(decision, item)
            accepted = semantic_decision_accepts(decision, item)
            if accepted:
                if not override_reason and not semantic_model_accepts(decision):
                    override_reason = "low_confidence_rule_fallback"
                if override_reason:
                    overridden_count += 1
                    override_reasons[override_reason] = override_reasons.get(override_reason, 0) + 1
                    item["_semantic_override_reason"] = override_reason
                domain = str(decision.get("domain") or "")
                if domain in TOPIC_TERMS:
                    item["topic"] = domain
                    item["tags"] = platform_item_tags(domain, [domain, *matched_topics(combined_text(item).lower())])
                content_type = str(decision.get("content_type") or "")
                if content_type in PLATFORM_TYPED_CONTENT_TYPES:
                    item["acceptance_path"] = content_type
                source_status = str(decision.get("source_status") or "")
                if source_status in {"verified", "claimed", "rumor", "unknown"}:
                    item["source_status"] = source_status
                item["semantic_confidence"] = float(decision.get("confidence") or 0)
                kept.append(item)
            else:
                rejected_count += 1
                reason_code = semantic_rejection_code(decision)
                rejection_reasons[reason_code] = rejection_reasons.get(reason_code, 0) + 1
                if rejection_details is not None:
                    rejection_details[item_id] = platform_rejection_detail(
                        "semantic_review",
                        reason_code,
                        model_decision=decision,
                    )
            continue

        fallback_count += 1
        if strict_platform_relevance(item):
            kept.append(item)
        else:
            rejected_count += 1
            rejection_reasons["strict_fallback_rejected"] = rejection_reasons.get("strict_fallback_rejected", 0) + 1
            if rejection_details is not None:
                rejection_details[item_id] = platform_rejection_detail(
                    "semantic_review",
                    "strict_fallback_rejected",
                )

    mode = "model" if reviewed_count else "strict_fallback"
    error = str(getattr(review_service, "classification_last_error", "") or "")[:300]
    return kept, semantic_review_report(
        mode,
        reviewed_count,
        rejected_count,
        fallback_count,
        rejection_reasons,
        error,
        overridden_count,
        override_reasons,
    )


def semantic_review_enabled() -> bool:
    raw = str(os.getenv("BRAND_RADAR_PLATFORM_SEMANTIC_REVIEW") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def semantic_review_text(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) <= PLATFORM_SEMANTIC_TEXT_LIMIT:
        return text
    head_size = PLATFORM_SEMANTIC_TEXT_LIMIT - 700
    return f"{text[:head_size]}\n...[内容过长，已截取中段]...\n{text[-650:]}"


def platform_semantic_review_input(item: dict[str, Any], index: int = 0) -> dict[str, Any]:
    context = item.get("conversation_context") or {}
    context_posts = context.get("posts") if isinstance(context, dict) else []
    comment_snippets: list[str] = []
    anchor_id = str(item.get("post_id") or "")
    for post in context_posts or []:
        if not isinstance(post, dict) or str(post.get("post_id") or "") == anchor_id:
            continue
        value = re.sub(
            r"\s+",
            " ",
            str(post.get("translation_zh") or post.get("clean_text") or post.get("text") or ""),
        ).strip()
        if value:
            comment_snippets.append(value[:180])
        if len(comment_snippets) >= 6:
            break
    media_evidence = []
    for entry in item.get("media") or []:
        if not isinstance(entry, dict):
            continue
        media_evidence.append(
            {
                "type": str(entry.get("type") or "unknown"),
                "url": str(
                    entry.get("media_url_https")
                    or entry.get("media_url")
                    or entry.get("preview_image_url")
                    or entry.get("expanded_url")
                    or entry.get("url")
                    or ""
                ),
                "description": str(
                    entry.get("alt_text")
                    or entry.get("description")
                    or entry.get("title")
                    or ""
                )[:300],
            }
        )
        if len(media_evidence) >= 4:
            break
    media_types = [entry["type"] for entry in media_evidence]
    metrics = item.get("metrics") or {}
    evidence = {
        "media_count": len(media_types),
        "media_types": media_types,
        "media": media_evidence,
        "reply_count": raw_metric(item, "replies", "reply_count"),
        "bookmark_count": raw_metric(item, "bookmarks", "bookmark_count"),
        "quote_count": raw_metric(item, "quotes", "quote_count"),
        "links": [str(link) for link in item.get("links") or []][:4],
        "context_summary": str(context.get("summary_zh") or "")[:500] if isinstance(context, dict) else "",
        "comment_snippets": comment_snippets,
    }
    return {
        "id": str(item.get("post_id") or index),
        "language": str(item.get("language") or "und"),
        "text": semantic_review_text(item.get("clean_text") or item.get("text") or ""),
        "acceptance_path_hint": str(item.get("acceptance_path") or ""),
        "evidence": evidence,
    }


def semantic_rejection_code(decision: dict[str, Any]) -> str:
    if decision.get("hard_risk") is True:
        return "content_policy"
    if decision.get("content_type") == "off_topic" or decision.get("platform_relation") in {"incidental", "none"}:
        return "not_central_subject"
    if decision.get("low_value") is True:
        return "low_value"
    if decision.get("central_subject") is not True and decision.get("actionable_for_platform") is not True:
        return "not_central_subject"
    if decision.get("relevant_domain") is not True:
        return "outside_target_domain"
    if decision.get("substantive") is not True:
        return "not_substantive"
    if float(decision.get("confidence") or 0) < PLATFORM_SEMANTIC_CONFIDENCE:
        return "low_confidence"
    return "semantic_rejected"


def semantic_decision_accepts(decision: dict[str, Any], item: dict[str, Any] | None = None) -> bool:
    platform_relevant = decision.get("central_subject") is True or decision.get("actionable_for_platform") is True
    confidence = float(decision.get("confidence") or 0)
    if semantic_model_accepts(decision):
        return True
    override_reason = semantic_rule_override_reason(decision, item)
    if override_reason:
        return True
    if confidence >= PLATFORM_SEMANTIC_NEGATIVE_CONFIDENCE:
        return False
    quality_score = int((item or {}).get("quality_score") or 0)
    return (
        platform_relevant
        and decision.get("relevant_domain") is True
        and quality_score >= PLATFORM_SEMANTIC_RULE_FALLBACK_SCORE
    )


def semantic_model_accepts(decision: dict[str, Any]) -> bool:
    if decision.get("hard_risk") is True:
        return False
    content_type = str(decision.get("content_type") or "")
    relation = str(decision.get("platform_relation") or "")
    if content_type in PLATFORM_TYPED_CONTENT_TYPES and relation in PLATFORM_REVIEW_RELATIONS:
        if decision.get("specific_signal") is not True or decision.get("relevant_domain") is not True:
            return False
        if content_type == "method_case" and decision.get("substantive") is not True:
            return False
        return float(decision.get("confidence") or 0) >= PLATFORM_SEMANTIC_CONFIDENCE
    platform_relevant = decision.get("central_subject") is True or decision.get("actionable_for_platform") is True
    return (
        platform_relevant
        and decision.get("relevant_domain") is True
        and decision.get("substantive") is True
        and decision.get("low_value") is not True
        and float(decision.get("confidence") or 0) >= PLATFORM_SEMANTIC_CONFIDENCE
    )


def semantic_rule_override_reason(
    decision: dict[str, Any],
    item: dict[str, Any] | None,
) -> str:
    """Return the bounded deterministic reason that overrules a model false negative."""
    if not item:
        return ""
    if decision.get("hard_risk") is True:
        return ""
    text = combined_text(item)
    if platform_noise_reason(text) or platform_specific_hard_risk_reason(text):
        return ""
    quality_score = int(item.get("quality_score") or 0)
    acceptance_path = str(item.get("acceptance_path") or platform_acceptance_path(item))
    if acceptance_path in PLATFORM_ACCEPTANCE_PATH_TOPICS and quality_score >= 62:
        return acceptance_path
    if decision.get("relevant_domain") is not True:
        return ""
    if quality_score < PLATFORM_SEMANTIC_RULE_FALLBACK_SCORE:
        return ""
    lower = combined_text(item).lower()
    aliases = ["小红书", "xiaohongshu", "rednote", "xhs"]
    if not matched_terms(lower, aliases):
        return ""

    if decision.get("low_value") is True or decision.get("substantive") is not True:
        return ""
    if platform_content_comparison_signal(item, lower, aliases):
        return "platform_content_comparison"
    if platform_case_evidence_signal(lower, aliases):
        return "platform_case_evidence"
    if method_structure_score(lower) < 10:
        return ""
    if explicit_platform_application_signal(lower, aliases):
        return "explicit_platform_application"
    return ""


def strict_platform_relevance(item: dict[str, Any]) -> bool:
    lower = combined_text(item).lower()
    topics = matched_topics(lower)
    if not topics:
        return False
    if "逆向与改机" in topics:
        return True
    structure_score = method_structure_score(lower)
    evidence_pattern = re.compile(
        r"(?:实测|数据|结果|步骤|教程|方案|策略|复盘|拆解|案例|如何|怎么|为什么|"
        r"\d+(?:天|周|月|个账号|篇|万|次|%))|(?:how to|case study|playbook|results?|steps?|guide)",
        re.IGNORECASE,
    )
    return structure_score >= 12 or bool(evidence_pattern.search(lower))


def semantic_review_report(
    mode: str,
    reviewed_count: int,
    rejected_count: int,
    fallback_count: int,
    rejection_reasons: dict[str, int] | None = None,
    error: str = "",
    overridden_count: int = 0,
    override_reasons: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "mode": mode,
        "reviewed_count": reviewed_count,
        "accepted_count": max(0, reviewed_count + fallback_count - rejected_count),
        "rejected_count": rejected_count,
        "fallback_count": fallback_count,
        "overridden_count": overridden_count,
        "override_reasons": override_reasons or {},
        "rejection_reasons": rejection_reasons or {},
        "error": error,
    }


def platform_rejection_detail(
    stage: str,
    reason_code: str,
    details: dict[str, Any] | None = None,
    model_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "stage": stage,
        "reason_code": reason_code,
        "reason_label": PLATFORM_REJECTION_REASON_LABELS.get(reason_code, "未通过最终收录规则"),
    }
    if details:
        record["details"] = details
    if model_decision:
        record["model_decision"] = {
            "platform_relation": str(model_decision.get("platform_relation") or ""),
            "content_type": str(model_decision.get("content_type") or ""),
            "specific_signal": bool(model_decision.get("specific_signal")),
            "hard_risk": bool(model_decision.get("hard_risk")),
            "source_status": str(model_decision.get("source_status") or "unknown"),
            "central_subject": bool(model_decision.get("central_subject")),
            "actionable_for_platform": bool(model_decision.get("actionable_for_platform")),
            "relevant_domain": bool(model_decision.get("relevant_domain")),
            "substantive": bool(model_decision.get("substantive")),
            "low_value": bool(model_decision.get("low_value")),
            "domain": str(model_decision.get("domain") or ""),
            "confidence": float(model_decision.get("confidence") or 0),
            "reason": str(model_decision.get("reason") or "")[:300],
        }
    return record


def write_platform_rejection_audit(
    audit_dir: Path,
    report_date: str,
    window_label: str,
    metric_eligible_items: dict[str, dict[str, Any]],
    selected: list[dict[str, Any]],
    rejection_details: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    final_ids = {str(item.get("post_id") or "") for item in selected}
    rejected_items = []
    stage_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    for post_id, item in metric_eligible_items.items():
        if post_id in final_ids:
            continue
        rejection = rejection_details.get(post_id) or platform_rejection_detail("final_filter", "final_filter")
        stage = str(rejection.get("stage") or "final_filter")
        reason_code = str(rejection.get("reason_code") or "final_filter")
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
        reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1
        rejected_items.append(platform_rejection_audit_item(item, rejection))
    rejected_items.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    expected_rejected_count = max(0, len(metric_eligible_items) - len(final_ids))
    pending_count = stage_counts.get("pending_content", 0)
    payload = {
        "schema_version": 1,
        "platform": PLATFORM_KEY,
        "date": report_date,
        "generated_at": to_iso(now_utc()),
        "window_label": window_label,
        "retention_days": PLATFORM_REJECTION_AUDIT_RETENTION_DAYS,
        "summary": {
            "metric_eligible_count": len(metric_eligible_items),
            "accepted_count": len(final_ids),
            "rejected_count": len(rejected_items),
            "decided_rejected_count": max(0, len(rejected_items) - pending_count),
            "pending_count": pending_count,
            "expected_rejected_count": expected_rejected_count,
            "count_matches": len(rejected_items) == expected_rejected_count,
            "stage_counts": stage_counts,
            "reason_counts": reason_counts,
        },
        "items": rejected_items,
    }
    audit_dir.mkdir(parents=True, exist_ok=True)
    write_json(str(audit_dir / f"{report_date}.json"), payload)
    prune_platform_rejection_audits(audit_dir, report_date)
    return payload


def platform_rejection_audit_item(item: dict[str, Any], rejection: dict[str, Any]) -> dict[str, Any]:
    media_types = [str(media.get("type") or "unknown") for media in item.get("media") or [] if isinstance(media, dict)]
    return {
        "post_id": str(item.get("post_id") or ""),
        "url": str(item.get("url") or ""),
        "created_at": str(item.get("created_at") or ""),
        "language": str(item.get("language") or "und"),
        "author": {
            "id": str(item.get("author_id") or ""),
            "name": str(item.get("author_name") or ""),
            "handle": str(item.get("author_handle") or ""),
        },
        "text": str(item.get("clean_text") or item.get("text") or ""),
        "links": item.get("links") or [],
        "media": {"count": len(media_types), "types": media_types},
        "metrics": item.get("metrics") or {},
        "query_group": str(item.get("_audit_query_group") or ""),
        "query_round": int(item.get("_audit_query_round") or 1),
        "topic": str(item.get("topic") or ""),
        "acceptance_path": str(item.get("acceptance_path") or ""),
        "source_status": str(item.get("source_status") or "unknown"),
        "quality_score": item.get("quality_score"),
        "tags": item.get("tags") or [],
        "rejection": rejection,
    }


def prune_platform_rejection_audits(
    audit_dir: Path,
    report_date: str,
    retention_days: int = PLATFORM_REJECTION_AUDIT_RETENTION_DAYS,
) -> list[str]:
    cutoff = date.fromisoformat(report_date) - timedelta(days=max(1, retention_days) - 1)
    removed: list[str] = []
    for path in audit_dir.glob("*.json"):
        try:
            audit_date = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if audit_date < cutoff:
            path.unlink()
            removed.append(path.name)
    return sorted(removed)


def attach_platform_context(items: list[dict[str, Any]], x_source: Any, translation_service: Any, start: Any, end: Any) -> dict[str, Any]:
    clusters = [
        {
            "post_ids": [item.get("post_id")],
            "score": {"ips": item.get("quality_score", 0)},
        }
        for item in items
    ]
    return attach_conversation_contexts(
        items,
        clusters,
        x_source,
        translation_service,
        to_iso(start),
        to_iso(end),
        allow_anchor_threads=True,
    )


def platform_review_evidence_candidate(item: dict[str, Any]) -> bool:
    """Limit pre-review context calls to candidates where surrounding evidence can change the decision."""
    acceptance_path = str(item.get("acceptance_path") or platform_acceptance_path(item))
    if acceptance_path not in PLATFORM_ACCEPTANCE_PATH_TOPICS:
        return False
    has_media = any(isinstance(entry, dict) for entry in item.get("media") or [])
    replies = raw_metric(item, "replies", "reply_count")
    quotes = raw_metric(item, "quotes", "quote_count")
    if acceptance_path in {"platform_observation", "case_lead"}:
        return has_media or replies >= 3 or quotes >= 1
    if acceptance_path in {"platform_update", "tool_resource"}:
        return has_media or replies >= 5 or quotes >= 1
    return False


def merge_platform_context_statuses(
    review_status: dict[str, Any],
    final_status: dict[str, Any],
    selected: list[dict[str, Any]],
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("eligible", "attempted", "filtered_noise", "capped_contexts"):
        merged[key] = int(review_status.get(key) or 0) + int(final_status.get(key) or 0)
    merged["attached"] = sum(
        1
        for item in selected
        if isinstance(item.get("conversation_context"), dict) and item["conversation_context"].get("posts")
    )
    merged["unresolved"] = int(review_status.get("unresolved") or 0) + int(final_status.get("unresolved") or 0)
    merged["fetch_limit"] = max(int(review_status.get("fetch_limit") or 0), int(final_status.get("fetch_limit") or 0))
    summary: dict[str, int] = {}
    for status in (review_status, final_status):
        for name, count in (status.get("summary") or {}).items():
            summary[str(name)] = summary.get(str(name), 0) + int(count or 0)
    merged["summary"] = summary
    warnings: list[str] = []
    for warning in [*(review_status.get("warnings") or []), *(final_status.get("warnings") or [])]:
        append_unique_warning(warnings, str(warning))
    merged["warnings"] = warnings[:5]
    merged["review_evidence_attempted"] = int(review_status.get("attempted") or 0)
    return merged


def refresh_context_status_for_items(context_status: dict[str, Any], items: list[dict[str, Any]]) -> None:
    attached = sum(1 for item in items if isinstance(item.get("conversation_context"), dict) and item["conversation_context"].get("posts"))
    attempted = int(context_status.get("attempted") or len(items))
    deduped = int(context_status.get("deduped_after_context") or 0)
    context_status["attached"] = attached
    context_status["unresolved"] = max(0, attempted - deduped - attached)


def collection_status(
    items: list[dict[str, Any]],
    candidates_seen: int,
    max_items: int | None,
    max_candidates: int | None,
    warnings: list[str],
    source_request_limit_reached: bool = False,
    min_views: int = DEFAULT_MIN_VIEWS,
    min_likes: int = DEFAULT_MIN_LIKES,
    metric_filtered: int = 0,
    conversation_deduped: int = 0,
    semantic_filtered: int = 0,
    query_groups_completed: int = 0,
    configured_query_groups: int = 0,
    query_targets_met: int = 0,
) -> dict[str, Any]:
    status = "complete"
    if (
        configured_query_groups
        and query_groups_completed >= configured_query_groups
        and query_targets_met >= configured_query_groups
    ):
        reason = "query_group_targets_reached"
    elif max_items and len(items) >= max_items:
        reason = "daily_item_target_reached"
    elif max_candidates is not None and candidates_seen >= max_candidates:
        reason = "candidate_cap_reached"
    elif source_request_limit_reached:
        reason = "source_request_limit_reached"
    elif configured_query_groups and query_groups_completed >= configured_query_groups:
        reason = "query_groups_completed"
    else:
        reason = "collection_stopped"
    if warnings:
        status = "partial"
    return {
        "status": status,
        "completion_reason": reason,
        "warnings": warnings[:5],
        "accepted_count": len(items),
        "candidates_inspected": candidates_seen,
        "metric_filtered": metric_filtered,
        "conversation_deduped": conversation_deduped,
        "semantic_filtered": semantic_filtered,
        "configured_query_groups": configured_query_groups,
        "query_groups_completed": query_groups_completed,
        "query_targets_met": query_targets_met,
        "max_items": max_items,
        "max_candidates": max_candidates,
        "source_request_limit_reached": source_request_limit_reached,
        "min_views": min_views,
        "min_likes": min_likes,
    }


def write_platform_payload(target: Path, payload: dict[str, Any]) -> None:
    platform_dir = target / PLATFORM_DATA_ROOT / PLATFORM_KEY
    platform_dir.mkdir(parents=True, exist_ok=True)
    write_json(str(platform_dir / "latest.json"), payload)
    write_json(str(platform_dir / "daily" / f"{payload['date']}.json"), payload)
    shard_json_file(platform_dir / "latest.json", target)
    shard_json_file(platform_dir / "daily" / f"{payload['date']}.json", target)
    write_json(str(platform_dir / "index.json"), platform_index(platform_dir, payload))
    if not shared_asset_rebuild_deferred():
        update_bundle(target.parent / "dashboard-data-bundle.js", target)


def platform_index(platform_dir: Path, current: dict[str, Any]) -> dict[str, Any]:
    daily_dir = platform_dir / "daily"
    records: dict[str, dict[str, Any]] = {}
    if daily_dir.exists():
        for path in daily_dir.glob("*.json"):
            try:
                record = read_json(str(path))
            except Exception:
                continue
            if record.get("date"):
                records[record["date"]] = record
    records[current["date"]] = current
    return {
        "latest_date": current["date"],
        "generated_at": current["generated_at"],
        "items": [
            {
                "date": record.get("date"),
                "generated_at_label": record.get("generated_at_label"),
                "window_label": record.get("window_label"),
                "accepted": len(record.get("items") or []),
                "candidates_inspected": record.get("summary", {}).get("candidates_inspected", 0),
                "collection_status": record.get("collection_status", {}).get("status", "unknown"),
                "tag_counts": platform_tag_counts(record),
            }
            for record in sorted(records.values(), key=lambda item: item.get("date", ""), reverse=True)
        ],
    }


def platform_tag_counts(record: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in record.get("items") or []:
        for tag in set(item.get("tags") or []):
            label = str(tag or "").strip()
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


def update_bundle(bundle_path: Path, data_dir: Path) -> None:
    write_data_bundle(bundle_path, {})


def shared_asset_rebuild_deferred() -> bool:
    return str(os.getenv("BRAND_RADAR_DEFER_SHARED_ASSETS") or "").strip().lower() in {"1", "true", "yes", "on"}


def load_bundle(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    prefix = "window.__DASHBOARD_DATA__ = "
    if text.startswith(prefix):
        text = text[len(prefix) :]
    if text.endswith(";"):
        text = text[:-1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def public_platform_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed = {
        "post_id",
        "created_at",
        "time",
        "url",
        "external_href",
        "language",
        "text",
        "clean_text",
        "original_text",
        "translation_zh",
        "translation_status",
        "summary_zh",
        "platform",
        "brand",
        "source_type",
        "badge",
        "topic",
        "quality_score",
        "quality_label",
        "score_value",
        "score_label",
        "selected_reason",
        "reusable_takeaway",
        "acceptance_path",
        "source_status",
        "tags",
        "author_id",
        "author_name",
        "author_handle",
        "author_avatar_url",
        "author_followers",
        "author_following",
        "author_bio",
        "author_location",
        "author_joined_at",
        "author_verified",
        "reply_to_post_id",
        "reply_to_handle",
        "quoted_post_id",
        "conversation_id",
        "conversation_context",
        "media",
        "links",
        "metrics",
        "post_metrics",
    }
    return [{key: value for key, value in item.items() if key in allowed} for item in items]


def public_translation_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(status.get("configured", True)),
        "counts": status.get("counts", {}),
        "missing_count": status.get("missing_count", 0),
        "fallback_original_count": status.get("fallback_original_count", 0),
    }


def platform_request_stats(x_source: Any) -> dict[str, Any]:
    return {
        "api_requests_used": getattr(x_source, "requests_used", None),
        "max_api_requests": getattr(x_source, "max_requests_per_run", None),
        "request_budget_exhausted": bool(getattr(x_source, "request_budget_exhausted", False)),
        "source_request_limit_reached": source_request_limit_reached(x_source),
        "context_requests_used": getattr(x_source, "context_requests_used", None),
        "max_context_requests": getattr(x_source, "max_context_requests_per_run", None),
        "context_request_budget_exhausted": bool(getattr(x_source, "context_request_budget_exhausted", False)),
    }


def source_request_limit_reached(x_source: Any) -> bool:
    max_requests = getattr(x_source, "max_requests_per_run", None)
    if max_requests is None:
        return bool(getattr(x_source, "request_budget_exhausted", False))
    try:
        return int(getattr(x_source, "requests_used", 0) or 0) >= int(max_requests)
    except (TypeError, ValueError):
        return bool(getattr(x_source, "request_budget_exhausted", False))


def append_unique_warning(warnings: list[str], warning: str) -> None:
    if warning and warning not in warnings:
        warnings.append(warning)


def public_platform_collection_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        **status,
        "warnings": public_platform_warnings(status.get("warnings", [])),
    }


def public_semantic_review_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": status.get("mode", "unknown"),
        "reviewed_count": int(status.get("reviewed_count") or 0),
        "accepted_count": int(status.get("accepted_count") or 0),
        "rejected_count": int(status.get("rejected_count") or 0),
        "fallback_count": int(status.get("fallback_count") or 0),
        "overridden_count": int(status.get("overridden_count") or 0),
        "override_reasons": status.get("override_reasons") or {},
        "rejection_reasons": status.get("rejection_reasons") or {},
    }


def public_platform_warnings(warnings: list[Any]) -> list[str]:
    results: list[str] = []
    for warning in warnings:
        text = str(warning)
        lower = text.lower()
        if "no candidates" in lower:
            message = "平台流变未从数据源取到候选内容，请检查查询配置或稍后补跑。"
        elif "budget" in lower or "request" in lower or "provider" in lower or "twitterapi" in lower:
            continue
        else:
            message = "平台流变采集完成，但存在非关键提醒。"
        if message not in results:
            results.append(message)
    return results[:3]


def clean_post_text(post: dict[str, Any]) -> str:
    text = html.unescape(str(post.get("text") or ""))
    text = strip_media_placeholder_urls(text, post)
    return re.sub(r"[ \t]+", " ", text).strip()


def combined_text(item: dict[str, Any]) -> str:
    links = " ".join(str(link) for link in item.get("links") or [])
    return f"{item.get('clean_text') or item.get('text') or ''} {links}".strip()


def matched_terms(lower: str, terms: list[str]) -> list[str]:
    matches = []
    padded = f" {lower} "
    for term in terms:
        value = term.strip().lower()
        if not value:
            continue
        if len(value) <= 3 and value.isascii():
            if re.search(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", padded):
                matches.append(term)
        elif value in lower:
            matches.append(term)
    return matches


def matched_topics(lower: str) -> list[str]:
    topics = []
    for topic, terms in TOPIC_TERMS.items():
        if matched_terms(lower, [term.lower() for term in terms]):
            topics.append(topic)
    return topics


def platform_focus_signal(lower: str, aliases: list[str]) -> bool:
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    focus_pattern = "|".join(re.escape(term.lower()) for term in PLATFORM_FOCUS_TERMS)
    if not alias_pattern or not focus_pattern:
        return False
    patterns = [
        rf"(?:{alias_pattern})[\s\S]{{0,50}}(?:{focus_pattern})",
        rf"(?:{focus_pattern})[\s\S]{{0,50}}(?:{alias_pattern})",
        rf"(?:支持|适配|覆盖|接入|同步(?:发布)?到?|发布(?:到|至)?)[\s\S]{{0,30}}(?:{alias_pattern})",
        rf"(?:{alias_pattern})[\s\S]{{0,30}}(?:支持|适配|自动化|工作流|发布|预览后手动)",
    ]
    return any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns)


def platform_acceptance_path(
    item: dict[str, Any],
    lower: str | None = None,
    aliases: list[str] | None = None,
) -> str:
    """Return a bounded value path for platform intelligence beyond full tutorials."""
    value = lower if lower is not None else combined_text(item).lower()
    platform_aliases = aliases or ["小红书", "xiaohongshu", "rednote", "xhs"]
    if not matched_terms(value, platform_aliases):
        return ""
    if platform_update_signal(value, platform_aliases):
        return "platform_update"
    if platform_tool_resource_signal(value, platform_aliases):
        return "tool_resource"
    if platform_monetization_opportunity_signal(value, platform_aliases):
        return "monetization_opportunity"
    if platform_case_lead_signal(value, platform_aliases):
        return "case_lead"
    if platform_content_comparison_signal(item, value, platform_aliases):
        return "platform_observation"
    return ""


def platform_update_signal(lower: str, aliases: list[str]) -> bool:
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    if not alias_pattern:
        return False
    update_pattern = (
        r"(?:内测|上线(?:了)?(?:新)?(?:功能|服务|版本|入口)|平台改版|不互通|隔离|分区|账号体系|身份账号|"
        r"算法调整|推荐调整|规则调整|商业化调整|机制变化|规则变化|政策变化|算法变化|生态变化|"
        r"功能新增|功能下线)"
    )
    platform_object = r"(?:账号|身份|用户|互动|点赞|评论|转发|私信|注册|流量|推荐|算法|规则|审核|商业化|生态|功能|平台)"
    nearby = (
        rf"(?:{alias_pattern})[\s\S]{{0,100}}{update_pattern}|"
        rf"{update_pattern}[\s\S]{{0,100}}(?:{alias_pattern})"
    )
    return bool(re.search(nearby, lower, re.IGNORECASE) and re.search(platform_object, lower, re.IGNORECASE))


def platform_tool_resource_signal(lower: str, aliases: list[str]) -> bool:
    if not matched_terms(lower, aliases):
        return False
    resource_pattern = r"(?:\bskills?\b|github|开源(?:项目|仓库)?|代码仓库|提示词(?:库)?|prompt\s*(?:library|repo))"
    production_pattern = r"(?:写|创作|生成|制作|配图|封面|图文|笔记|选题|发布|运营|分析|复盘|账号|内容)"
    if not re.search(resource_pattern, lower, re.IGNORECASE):
        return False
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    return bool(
        re.search(
            rf"(?:{alias_pattern})[^。！？\n]{{0,55}}{production_pattern}|"
            rf"{production_pattern}[^。！？\n]{{0,55}}(?:{alias_pattern})",
            lower,
            re.IGNORECASE,
        )
    )


def platform_monetization_opportunity_signal(lower: str, aliases: list[str]) -> bool:
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    if not alias_pattern:
        return False
    concrete_model = (
        r"(?:数字产品|单品带货|知识产品|商单|带货|店铺|"
        r"咨询服务|代运营|affiliate|digital product)"
    )
    return bool(
        re.search(
            rf"(?:{alias_pattern})[^。！？\n]{{0,45}}{concrete_model}|"
            rf"{concrete_model}[^。！？\n]{{0,45}}(?:{alias_pattern})",
            lower,
            re.IGNORECASE,
        )
    )


def platform_case_lead_signal(lower: str, aliases: list[str]) -> bool:
    if not matched_terms(lower, aliases):
        return False
    subject_pattern = r"(?:@[a-z0-9_]{2,20}|博主|操盘手|高手|团队|账号|项目)"
    result_pattern = r"(?:拿到过结果|跑通|做成|起号成功|爆文|涨粉|利润|收入|阅读|变现)"
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    has_platform_result = bool(
        re.search(
            rf"(?:{alias_pattern})[^。！？\n]{{0,55}}{result_pattern}|"
            rf"{result_pattern}[^。！？\n]{{0,55}}(?:{alias_pattern})",
            lower,
            re.IGNORECASE,
        )
    )
    return has_platform_result and bool(re.search(subject_pattern, lower, re.IGNORECASE))


def platform_specific_hard_risk_reason(text: str) -> str | None:
    lower = str(text or "").lower()
    patterns = {
        "pirated_material_sales": r"(?:小红书[^。！？\n]{0,30})?(?:卖|售卖|销售)[^。！？\n]{0,12}(?:盗版|绝版)(?:电子书|资料|课程)",
        "cloud_drive_referral": r"(?:小红书[^。！？\n]{0,35})?网盘拉新",
        "ai_recharge_lead_generation": r"ai\s*代充[\s\S]{0,180}(?:引流|获客|被动收入|教程|sop|赚钱)",
        "paid_fake_engagement": r"(?:刷赞|付费涨粉|付费评论|打粉|给[^。！？\n]{0,12}(?:元|块钱)[^。！？\n]{0,12}评论)",
        "political_advocacy": (
            r"(?:中共|中国共产党|ccp)[\s\S]{0,80}(?:统战|内外宣|大外宣|干预.{0,12}选举|灭亡)|"
            r"(?:统战|内外宣|大外宣|干预.{0,12}选举|灭亡)[\s\S]{0,80}(?:中共|中国共产党|ccp)"
        ),
    }
    for reason, pattern in patterns.items():
        if re.search(pattern, lower, re.IGNORECASE):
            return reason
    return None


def platform_source_status(text: str) -> str:
    lower = str(text or "").lower()
    if re.search(r"(?:据悉|据.{0,12}爆料|业内人士|传闻|预计|可能|听说|网传)", lower, re.IGNORECASE):
        return "rumor"
    if re.search(r"(?:实测|官方|公告|数据|截图|项目|github|开源|\d+[万千k+%]|拿到过结果)", lower, re.IGNORECASE):
        return "claimed"
    return "unknown"


def platform_case_evidence_signal(lower: str, aliases: list[str]) -> bool:
    """Detect a result that is explicitly tied to a Xiaohongshu action or account."""
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    if not alias_pattern:
        return False
    bound_alias = (
        rf"(?:(?:发到|发布到|同步到|在|做|运营)\s*(?:{alias_pattern})|"
        rf"(?:{alias_pattern})(?:账号|起号|笔记|店铺|发布|发|卖|运营|矩阵|粉丝|上))"
    )
    engagement_result = (
        r"(?:起号第?\s*\d+\s*天|一发就(?:火|爆)|篇篇爆款|"
        r"(?:\d[\d,.]*\s*(?:万|千|k|w|\+)?\s*(?:阅读|浏览|播放|曝光|点赞|赞|收藏|粉丝|涨粉|评论|商单))|"
        r"(?:(?:阅读|浏览|播放|曝光|点赞|赞|收藏|粉丝|涨粉|评论|商单)\s*(?:达到|破|有|为|[:：])?\s*"
        r"\d[\d,.]*\s*(?:万|千|k|w|\+)?))"
    )
    nearby_patterns = [
        rf"{bound_alias}[\s\S]{{0,90}}{engagement_result}",
        rf"{engagement_result}[\s\S]{{0,90}}{bound_alias}",
    ]
    if any(re.search(pattern, lower, re.IGNORECASE) for pattern in nearby_patterns):
        return True
    revenue_pattern = (
        rf"{bound_alias}[\s\S]{{0,35}}(?:卖|售卖|店铺|带货|变现)"
        rf"[\s\S]{{0,35}}(?:赚|收入|收益|成交)[^。！？\n]{{0,12}}\d"
    )
    return bool(re.search(revenue_pattern, lower, re.IGNORECASE))


def explicit_platform_application_signal(lower: str, aliases: list[str]) -> bool:
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    if not alias_pattern:
        return False
    generic_platform_claim = re.search(
        rf"(?:适合|用于|用来|面向)[^。！？\n]{{0,8}}(?:所有|各个?|任何|多)平台"
        rf"[^。！？\n]{{0,45}}(?:{alias_pattern})",
        lower,
        re.IGNORECASE,
    )
    if generic_platform_claim:
        return False
    post_alias_binding = (
        r"(?:适合|用于|用来|面向|配图|图文|提示词|分镜|脚本|模板|工作流|"
        r"自动化|风控|平台限制|内容形式)"
    )
    has_post_alias_binding = bool(
        re.search(
            rf"(?:{alias_pattern})[^。！？\n]{{0,30}}{post_alias_binding}",
            lower,
            re.IGNORECASE,
        )
    )
    pre_alias_matches = re.finditer(
        rf"(?:适合|用于|用来|面向)[^。！？\n]{{0,28}}(?:{alias_pattern})",
        lower,
        re.IGNORECASE,
    )
    other_platform_pattern = re.compile(r"(?:公众号|抖音|视频号|微博|快手|b站|bilibili|tiktok)", re.IGNORECASE)
    has_direct_pre_alias_binding = any(
        not other_platform_pattern.search(match.group(0))
        for match in pre_alias_matches
    )
    if not has_post_alias_binding and not has_direct_pre_alias_binding:
        return False
    method_hits = matched_terms(
        lower,
        ["图文", "配图", "提示词", "分镜", "脚本", "模板", "工作流", "选题", "对标", "复盘", "数据反馈", "内容形式"],
    )
    return len(set(method_hits)) >= 2


def platform_risk_evidence_signal(lower: str, aliases: list[str]) -> bool:
    """Recognize a concrete platform scam or data-risk chain, not a generic privacy mention."""
    if not matched_terms(lower, aliases):
        return False
    risk_terms = matched_terms(
        lower,
        ["外部地址", "外链", "手机号", "个人信息", "个人数据", "数据卖", "诈骗", "骗局", "钓鱼", "盗号"],
    )
    if len(risk_terms) < 2:
        return False
    return bool(re.search(r"(?:然后|后续|流程|会给|引导|让你|不要|千万|小心|再把)", lower))


def platform_content_comparison_signal(
    item: dict[str, Any],
    lower: str,
    aliases: list[str],
) -> bool:
    if item.get("links") or re.search(r"https?://\S+", lower):
        return False
    signal_length = len(re.findall(r"[a-z0-9\u3400-\u9fff]", lower))
    if signal_length < 45:
        return False
    alias_pattern = "|".join(re.escape(str(alias).strip().lower()) for alias in aliases if str(alias).strip())
    if not alias_pattern:
        return False
    format_pattern = r"(?:手写|电脑码字|露脸|不露脸|图文|视频|封面|标题|笔记|口播|实拍)"
    has_platform_format = any(
        re.search(pattern, lower, re.IGNORECASE)
        for pattern in (
            rf"(?:{alias_pattern})[^。！？\n]{{0,70}}{format_pattern}",
            rf"{format_pattern}[^。！？\n]{{0,70}}(?:{alias_pattern})",
        )
    )
    result_pattern = r"(?:爆款|流量|曝光|阅读|播放|点赞|收藏|涨粉)"
    direct_comparison = re.search(
        rf"{format_pattern}[^。！？\n]{{0,45}}{result_pattern}[^。！？\n]{{0,35}}"
        rf"(?:但是|但|一旦|相比|反而|断崖式)[^。！？\n]{{0,45}}{format_pattern}"
        rf"[^。！？\n]{{0,35}}{result_pattern}",
        lower,
        re.IGNORECASE,
    )
    return has_platform_format and bool(direct_comparison)


def method_structure_score(lower: str) -> int:
    score = 0
    if matched_terms(lower, STRUCTURE_SIGNALS):
        score += 12
    if re.search(r"(^|\n|\s)(\d+[\.、)]|[一二三四五六七八九十]+[、.])", lower):
        score += 10
    if len(lower) >= 260:
        score += 8
    if len(lower) >= 600:
        score += 6
    return min(28, score)


def is_short_reaction_link(item: dict[str, Any], lower: str, topics: list[str], structure_score: int) -> bool:
    text_without_urls = re.sub(r"https?://\S+", "", lower)
    signal_length = len(re.findall(r"[a-z0-9\u3400-\u9fff]", text_without_urls))
    has_link = bool(item.get("links")) or bool(re.search(r"https?://\S+", lower))
    return has_link and signal_length < 40 and structure_score < 10 and len(topics) <= 1


def strong_method_signal(lower: str) -> bool:
    return method_structure_score(lower) >= 12 or bool(matched_topics(lower))


def propagation_score(item: dict[str, Any]) -> int:
    metrics = item.get("metrics") or {}
    interactions = sum(int(metrics.get(key) or 0) for key in ("likes", "reposts", "replies", "quotes"))
    views = int(metrics.get("views") or 0)
    followers = int(item.get("author_followers") or 0)
    score = 0
    if interactions:
        score += min(14, round(math.log10(interactions + 1) * 7))
    if views:
        score += min(8, round(math.log10(views + 1) * 2))
    if followers >= 1000:
        score += 4
    if followers >= 10000:
        score += 4
    return min(22, score)


def selection_reason(topic: str, structure_score: int, metric_score: int, acceptance_path: str = "") -> str:
    path_reasons = {
        "platform_update": "内容包含具体的平台产品、规则或生态变化线索",
        "tool_resource": "内容提供可用于小红书创作或运营的工具资源",
        "monetization_opportunity": "内容提出了明确的小红书变现模式",
        "case_lead": "内容提供可继续追踪的小红书人物、账号或案例线索",
        "platform_observation": "内容记录了具体的小红书内容表现差异或讨论证据",
    }
    if acceptance_path in path_reasons:
        spread = "，且已有一定传播反馈" if metric_score >= 8 else ""
        return f"{path_reasons[acceptance_path]}，主题归为「{topic}」{spread}。"
    method = "内容包含可复用的方法、步骤或复盘结构" if structure_score >= 12 else "内容命中明确的小红书运营/增长意图"
    spread = "且已有一定传播反馈" if metric_score >= 8 else "，适合进入当日方法论样本池"
    return f"{method}，主题归为「{topic}」{spread}。"


def reusable_takeaway(topic: str) -> str:
    mapping = {
        "账号冷启动": "关注账号启动阶段的定位、互动和初始内容节奏。",
        "爆文与内容结构": "提炼选题、标题、封面、正文结构中的可复用写法。",
        "流量机制": "观察作者对推荐、曝光和互动反馈机制的判断。",
        "风控对抗": "关注账号安全、审核、限流和违规规避的实操经验。",
        "平台规则": "关注平台规则变化、审核口径和内容边界。",
        "矩阵": "关注账号矩阵、内容矩阵和批量运营的组织方式。",
        "变现": "记录从内容到商单、带货、店铺或服务成交的闭环。",
        "私域引流": "关注从小红书内容到社群、私域或线索承接的路径。",
        "案例复盘": "优先提取案例前提、动作、结果和可迁移限制。",
        "逆向与改机": "关注客户端逆向、接口签名、设备环境与账号风控之间的技术关系。",
    }
    return mapping.get(topic, "提炼可迁移的小红书运营动作。")


def platform_item_tags(topic: str, topics: list[str]) -> list[str]:
    tags = unique_tags([canonical_platform_tag(value) for value in [topic, *topics]])
    return tags or ["小红书方法论"]


def canonical_platform_tag(value: str) -> str:
    tag = re.sub(r"\s+", "_", str(value or "").strip())
    if not tag:
        return ""
    if tag in TOPIC_TERMS:
        return tag
    return PLATFORM_TAG_ALIASES.get(tag, "")


def unique_tags(values: list[str]) -> list[str]:
    tags = []
    for value in values:
        tag = re.sub(r"\s+", "_", str(value).strip())
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def query_label(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip()[:120]


def optional_int_env(name: str, fallback: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    if value < 0:
        return fallback
    return value


def optional_config_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _or_clause(terms: list[str]) -> str:
    return " OR ".join(_format_term(term) for term in terms if str(term).strip())


def _format_term(term: str) -> str:
    value = str(term).strip()
    if " " in value or "." in value:
        return f'"{value}"'
    return value


def _negative_clause(terms: list[str]) -> str:
    return " ".join(f"-{_format_term(term)}" for term in terms if str(term).strip())
