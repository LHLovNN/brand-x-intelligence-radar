#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.adapters.provider_factory import get_x_source
from src.pipeline.conversation_context import attach_conversation_contexts
from src.pipeline.dashboard_builder import build_dashboard_data
from src.pipeline.translation import build_translation_service
from src.utils.io import read_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Attach conversation context to the latest processed local preview.")
    parser.add_argument(
        "--no-context-translation",
        action="store_true",
        help="Skip translating thread items; the summary can still use the configured model service.",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            text = line.strip()
            if text:
                rows.append(json.loads(text))
    return rows


def sync_cluster_posts(clusters: list[dict[str, Any]], posts: list[dict[str, Any]]) -> None:
    post_by_id = {str(post.get("post_id") or ""): post for post in posts}
    for cluster in clusters:
        synced = []
        for post in cluster.get("posts", []):
            synced.append(post_by_id.get(str(post.get("post_id") or ""), post))
        cluster["posts"] = synced


def main() -> None:
    args = parse_args()
    checkpoint = read_json(str(ROOT / "data" / "checkpoints" / "daily" / "latest.json"))
    report_date = checkpoint["report_date"]
    log_path = ROOT / "data" / "logs" / f"daily-{report_date}.json"
    if not log_path.exists():
        raise SystemExit(f"Missing daily log: {log_path}")
    run_log = read_json(str(log_path))
    provider = run_log["provider"]
    processed_path = ROOT / "data" / "processed" / "normalized-posts.jsonl"
    clusters_path = ROOT / "data" / "clusters" / "joybuy-clusters.json"
    normalized = read_jsonl(processed_path)
    clusters = read_json(str(clusters_path))

    if args.no_context_translation:
        os.environ["CONVERSATION_CONTEXT_TRANSLATE_POSTS"] = "0"

    x_source = get_x_source(provider)
    translation_service = build_translation_service(provider)
    collection_status = dict(run_log.get("collection_status") or {})
    context_status = attach_conversation_contexts(
        normalized,
        clusters,
        x_source,
        translation_service,
        run_log["window_start"],
        run_log["window_end"],
    )
    collection_status["conversation_context"] = context_status
    sync_cluster_posts(clusters, normalized)
    overview = build_dashboard_data(
        clusters,
        normalized,
        str(ROOT / "public" / "dashboard-data"),
        provider_hint=provider,
        report_date=report_date,
        window_label=run_log.get("window_label"),
        collection_status=collection_status,
    )
    print(
        "Conversation context preview generated:",
        {
            "eligible": context_status.get("eligible", 0),
            "attempted": context_status.get("attempted", 0),
            "attached": context_status.get("attached", 0),
            "primary_signals": overview.get("metrics", {}).get("effective_intelligence"),
        },
    )


if __name__ == "__main__":
    main()
