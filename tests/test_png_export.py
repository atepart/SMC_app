"""Regression checks for the fatal post-export PySide receiver lifetime bug."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("run", [1, 2, 3])
def test_export_and_destroy_windows_in_fresh_process(run, tmp_path) -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "rtk",
            "proxy",
            "uv",
            "--cache-dir",
            str(tmp_path / "uv-cache"),
            "run",
            "--no-sync",
            "python",
            "-X",
            "faulthandler",
            str(root / "tests/qt_png_lifecycle_probe.py"),
            str(tmp_path / f"png-{run}"),
        ],
        cwd=root,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "destroyed 40" in result.stdout
