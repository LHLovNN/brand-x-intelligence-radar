#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.promote_platform_audit_items import (  # noqa: E402
    AtomicWriteError,
    PromotionError,
    atomic_replace_files,
    build_promotion_plan,
)


def main() -> None:
    platform = {
        "display_name": "小红书",
        "topic_label": "小红书增长方法",
        "aliases": ["小红书"],
        "intent_terms": ["流量", "选题", "复盘", "工作流"],
        "exclude_terms": [],
        "min_views_per_item": 100,
        "min_likes_per_item": 5,
    }
    payload = {
        "platform": "xiaohongshu",
        "date": "2026-09-09",
        "generated_at": "2026-09-09T00:00:00Z",
        "generated_at_label": "2026-09-09 08:00 BJT",
        "items": [
            {
                "post_id": "existing",
                "created_at": "2026-09-08T10:00:00Z",
                "translation_status": "source_chinese",
                "translation_zh": "已有内容",
                "tags": ["流量机制"],
            }
        ],
        "collection_status": {
            "accepted_count": 1,
            "min_views": 100,
            "min_likes": 5,
            "semantic_filtered": 1,
            "translation": {
                "configured": True,
                "counts": {"source_chinese": 1},
                "missing_count": 0,
                "fallback_original_count": 0,
            },
            "semantic_review": {
                "mode": "model",
                "reviewed_count": 1,
                "rejected_count": 1,
                "fallback_count": 0,
                "rejection_reasons": {"low_value": 1},
            },
        },
        "summary": {"accepted": 1, "semantic_filtered": 1},
    }
    promotable = audit_item(
        "promote-me",
        "小红书流量运营工作流：1. 先找选题；2. 生成内容并发布；3. 复盘数据后调整下一轮内容。",
        stage="semantic_review",
        reason_code="low_value",
    )
    rejected = audit_item(
        "keep-rejected",
        "今天心情不错，顺便提一句小红书。",
        stage="rule_filter",
        reason_code="missing_required_terms",
    )
    audit = {
        "schema_version": 1,
        "platform": "xiaohongshu",
        "date": "2026-09-09",
        "generated_at": "2026-09-09T00:00:00Z",
        "summary": {
            "metric_eligible_count": 3,
            "accepted_count": 1,
            "rejected_count": 2,
            "expected_rejected_count": 2,
            "count_matches": True,
            "stage_counts": {"semantic_review": 1, "rule_filter": 1},
            "reason_counts": {"low_value": 1, "missing_required_terms": 1},
        },
        "items": [promotable, rejected],
    }

    plan = build_promotion_plan(
        payload,
        audit,
        platform,
        ["promote-me"],
        generated_at="2026-09-09T06:00:00Z",
        generated_at_label="2026-09-09 14:00 BJT",
    )
    assert plan["changed"] is True
    assert plan["promoted_ids"] == ["promote-me"]
    assert [item["post_id"] for item in plan["payload"]["items"]] == ["promote-me", "existing"]
    promoted = plan["payload"]["items"][0]
    assert promoted["translation_zh"] == promotable["text"]
    assert promoted["translation_status"] == "source_chinese"
    assert promoted["media"] == []
    assert promoted["conversation_context"] == {}
    assert promoted["conversation_id"] is None
    assert promoted["quality_score"] >= 62
    assert plan["payload"]["collection_status"]["accepted_count"] == 2
    assert plan["payload"]["collection_status"]["translation"]["counts"] == {"source_chinese": 2}
    assert plan["payload"]["collection_status"]["semantic_filtered"] == 0
    assert plan["payload"]["collection_status"]["semantic_review"]["rejected_count"] == 0
    assert plan["audit"]["summary"]["accepted_count"] == 2
    assert plan["audit"]["summary"]["rejected_count"] == 1
    assert plan["audit"]["summary"]["expected_rejected_count"] == 1
    assert plan["audit"]["summary"]["count_matches"] is True
    assert plan["audit"]["summary"]["stage_counts"] == {"rule_filter": 1}
    assert plan["audit"]["summary"]["reason_counts"] == {"missing_required_terms": 1}

    idempotent = build_promotion_plan(
        plan["payload"],
        plan["audit"],
        platform,
        ["promote-me"],
        generated_at="2026-09-09T07:00:00Z",
        generated_at_label="2026-09-09 15:00 BJT",
    )
    assert idempotent["changed"] is False
    assert idempotent["already_present_ids"] == ["promote-me"]

    try:
        build_promotion_plan(
            payload,
            audit,
            platform,
            ["keep-rejected"],
            generated_at="2026-09-09T06:00:00Z",
            generated_at_label="2026-09-09 14:00 BJT",
        )
    except PromotionError as error:
        assert "current rule score rejected" in str(error)
    else:
        raise AssertionError("offline promotion must not bypass the current deterministic score")

    test_atomic_rollback_on_second_replace()
    print("Offline platform audit promotion tests passed.")


def audit_item(post_id: str, text: str, *, stage: str, reason_code: str) -> dict:
    return {
        "post_id": post_id,
        "url": f"https://x.com/example/status/{post_id}",
        "created_at": "2026-09-08T11:00:00Z" if post_id == "promote-me" else "2026-09-08T09:00:00Z",
        "language": "zh",
        "author": {"id": "author", "name": "示例作者", "handle": "example"},
        "text": text,
        "links": [],
        "media": {"count": 1, "types": ["photo"]},
        "metrics": {"likes": 20, "reposts": 2, "replies": 3, "quotes": 0, "bookmarks": 4, "views": 2000},
        "query_group": "content_traffic",
        "rejection": {
            "stage": stage,
            "reason_code": reason_code,
            "reason_label": "测试原因",
        },
    }


def test_atomic_rollback_on_second_replace() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        targets = [
            root / "daily" / "2026-09-09.json",
            root / "latest.json",
            root / "index.json",
            root / "audit" / "2026-09-09.json",
        ]
        originals: dict[Path, bytes] = {}
        updates: dict[Path, bytes] = {}
        for index, target in enumerate(targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            originals[target] = f"original-{index}\n".encode("utf-8")
            updates[target] = f"updated-{index}\n".encode("utf-8")
            target.write_bytes(originals[target])

        replace_calls = 0

        def fail_second_replace(source: str, target: str) -> None:
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("injected second replace failure")
            os.replace(source, target)

        try:
            atomic_replace_files(updates, replace_func=fail_second_replace)
        except AtomicWriteError as error:
            assert "injected second replace failure" in str(error)
        else:
            raise AssertionError("the injected second replace failure should abort the transaction")

        assert replace_calls == 3, "one commit, one failure and one rollback replace should occur"
        for target in targets:
            assert target.read_bytes() == originals[target], f"rollback should restore {target.name}"
        assert not list(root.rglob("*.tmp")), "transaction should clean all temporary files after rollback"


if __name__ == "__main__":
    main()
