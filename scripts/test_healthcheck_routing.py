#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_DATE = "2026-09-18"


def write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def make_fixture(root: Path) -> Path:
    repo = root / "repo"
    macos = repo / "scripts" / "macos"
    macos.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "macos" / "run_daily_healthcheck.sh", macos)
    write_executable(macos / "local_env.sh", "#!/usr/bin/env bash\n:\n")
    write_executable(
        repo / "scripts" / "check_public_freshness.py",
        """#!/usr/bin/env python3
import argparse, json, os
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--base-url")
p.add_argument("--expected-date")
p.add_argument("--output")
a = p.parse_args()
stale = set(filter(None, os.environ.get("FIXTURE_LOCAL_STALE", "").split(",")))
components = {
    kind: {
        "fresh": kind not in stale,
        "expected": a.expected_date,
        "observed": "old" if kind in stale else a.expected_date,
        "error": "",
    }
    for kind in ("brand", "xiaohongshu", "ai", "tg")
}
report = {"reachable": True, "fresh": not stale, "components": components}
Path(a.output).parent.mkdir(parents=True, exist_ok=True)
Path(a.output).write_text(json.dumps(report), encoding="utf-8")
raise SystemExit(0 if not stale else 1)
""",
    )
    write_executable(
        repo / "scripts" / "check_diting_upstream.py",
        """#!/usr/bin/env python3
import argparse, json, os
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--base-url")
p.add_argument("--expected-date")
p.add_argument("--output")
a = p.parse_args()
fresh = set(filter(None, os.environ.get("FIXTURE_UPSTREAM_FRESH", "").split(",")))
reachable = os.environ.get("FIXTURE_UPSTREAM_REACHABLE", "1") == "1"
components = {
    kind: {
        "fresh": reachable and kind in fresh,
        "expected": a.expected_date,
        "observed": a.expected_date if kind in fresh else "old",
        "error": "" if reachable else "unreachable",
    }
    for kind in ("ai", "tg")
}
report = {
    "expected_date": a.expected_date,
    "reachable": reachable,
    "fresh": reachable and len(fresh) == 2,
    "components": components,
}
Path(a.output).write_text(json.dumps(report), encoding="utf-8")
raise SystemExit(0 if report["fresh"] else (1 if reachable else 2))
""",
    )
    write_executable(
        macos / "run_diting_digest_sync.sh",
        """#!/usr/bin/env bash
printf '%s|%s\\n' "$BRAND_RADAR_DITING_KINDS" "$BRAND_RADAR_DITING_DATE" >> "$FIXTURE_CAPTURE"
""",
    )
    write_executable(macos / "run_local_daily.sh", "#!/usr/bin/env bash\nexit 99\n")
    return repo


def run_healthcheck(repo: Path, state: Path, capture: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ,
        "TMPDIR": str(repo.parent / "tmp"),
        "FIXTURE_CAPTURE": str(capture),
        "BRAND_RADAR_HEALTH_STATE_DIR": str(state),
        "BRAND_RADAR_HEALTH_EXPECTED_DATE": EXPECTED_DATE,
        "BRAND_RADAR_HEALTH_RUN_HOUR": "11",
        **extra,
    }
    Path(environment["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        ["bash", str(repo / "scripts" / "macos" / "run_daily_healthcheck.sh")],
        text=True,
        capture_output=True,
        env=environment,
        check=False,
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="healthcheck-routing-") as temporary:
        root = Path(temporary)
        repo = make_fixture(root)
        capture = root / "capture.txt"

        first_state = root / "state-one"
        first = run_healthcheck(
            repo,
            first_state,
            capture,
            FIXTURE_LOCAL_STALE="ai,tg",
            FIXTURE_UPSTREAM_FRESH="ai",
        )
        assert first.returncode == 1, first.stderr
        block = json.loads((first_state / f"diting-upstream-manual-{EXPECTED_DATE}.json").read_text())
        assert set(block["blocked_components"]) == {"tg"}, block

        second_state = root / "state-two"
        second_state.mkdir()
        (second_state / f"diting-upstream-manual-{EXPECTED_DATE}.json").write_text(
            json.dumps({"blocked_components": {"ai": {"reason": "upstream_missing"}}}),
            encoding="utf-8",
        )
        second = run_healthcheck(
            repo,
            second_state,
            capture,
            FIXTURE_LOCAL_STALE="ai,tg",
            FIXTURE_UPSTREAM_FRESH="ai,tg",
        )
        assert second.returncode == 1, second.stderr

        third = run_healthcheck(
            repo,
            second_state,
            capture,
            FIXTURE_LOCAL_STALE="ai,tg",
            FIXTURE_UPSTREAM_FRESH="ai,tg",
            BRAND_RADAR_HEALTH_OVERRIDE_DITING_UPSTREAM_BLOCK="1",
        )
        assert third.returncode == 1, third.stderr
        assert capture.read_text(encoding="utf-8").splitlines() == [
            f"ai|{EXPECTED_DATE}",
            f"tg|{EXPECTED_DATE}",
            f"ai,tg|{EXPECTED_DATE}",
        ]

    print("Health-check routing tests passed.")


if __name__ == "__main__":
    main()
