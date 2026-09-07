#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.pipeline.dashboard_builder import refresh_index_asset_versions, write_data_bundle
from src.pipeline.lazy_payloads import prune_unreferenced_lazy_payloads


def main() -> None:
    public_dir = ROOT / "public"
    removed = prune_unreferenced_lazy_payloads(public_dir / "dashboard-data")
    write_data_bundle(public_dir / "dashboard-data-bundle.js", {})
    refresh_index_asset_versions(public_dir / "index.html")
    print(f"Rebuilt shared static bootstrap and content-hash asset versions; pruned {removed} orphan lazy payloads.")


if __name__ == "__main__":
    main()
