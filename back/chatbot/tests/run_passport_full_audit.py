# -*- coding: utf-8 -*-
"""Полный аудит passport/: все 75 файлов × 50 вопросов + база пробелов."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--questions", type=int, default=50)
    p.add_argument("--resume", action="store_true", default=True)
    p.add_argument("--no-resume", action="store_false", dest="resume")
    p.add_argument("--regen-questions", action="store_true")
    args = p.parse_args()
    cmd = [
        sys.executable,
        str(_ROOT / "run_passport_batch_audit.py"),
        "--start-index",
        "0",
        "--questions",
        str(args.questions),
    ]
    if args.resume:
        cmd.append("--resume")
    if args.regen_questions:
        cmd.append("--regen-questions")
    print(" ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
