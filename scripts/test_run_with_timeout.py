#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_with_timeout.py"


def main() -> None:
    completed = subprocess.run(
        [sys.executable, str(RUNNER), "--seconds", "2", "--", sys.executable, "-c", "print('ok')"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "ok"

    started = time.monotonic()
    timed_out = subprocess.run(
        [sys.executable, str(RUNNER), "--seconds", "1", "--", sys.executable, "-c", "import time; time.sleep(30)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert timed_out.returncode == 124
    assert time.monotonic() - started < 5
    assert "timed out" in timed_out.stderr

    with tempfile.TemporaryDirectory() as temporary_dir:
        pid_path = Path(temporary_dir) / "child.pid"
        wrapper = subprocess.Popen(
            [
                sys.executable,
                str(RUNNER),
                "--seconds",
                "30",
                "--",
                sys.executable,
                "-c",
                f"import os,time; open({str(pid_path)!r}, 'w').write(str(os.getpid())); time.sleep(30)",
            ]
        )
        deadline = time.monotonic() + 3
        while not pid_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pid_path.exists()
        child_pid = int(pid_path.read_text())
        wrapper.terminate()
        assert wrapper.wait(timeout=5) == 143
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise AssertionError("Timed command child survived wrapper termination")
    print("Command timeout tests passed.")


if __name__ == "__main__":
    main()
