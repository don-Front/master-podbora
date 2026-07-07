# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = Path(__file__).resolve().parents[1] / "back" / "project" / "data" / "competitors" / "_sources"
OUT = Path(__file__).resolve().parents[1] / "back" / "project" / "data" / "competitors" / "_extract_all.txt"

KEYWORDS = (
    "Приложение",
    "условн",
    "обознач",
    "маск",
    "G16",
    "G400",
    "DN50",
    "PN16",
    "ИРВИС",
    "ULTRAMAG",
    "Сигнал",
    "РСГ",
    "2У",
    "типоразмер",
)


def main() -> int:
    lines: list[str] = []
    for pdf in sorted(SRC.glob("*.pdf")):
        lines.append(f"\n{'=' * 80}\nFILE: {pdf.name}\npages: ")
        reader = PdfReader(str(pdf))
        lines.append(str(len(reader.pages)))
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            low = text.lower()
            if any(k.lower() in low for k in KEYWORDS):
                lines.append(f"\n--- page {i + 1} ---")
                lines.append(text[:4500])
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
