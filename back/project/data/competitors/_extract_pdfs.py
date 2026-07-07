"""One-off PDF text extraction for competitor mask catalogs."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

BASE = Path(__file__).resolve().parent / "_sources"
FILES = ["vympel_500.pdf", "ktm_600.pdf"]
OUT = Path(__file__).resolve().parent / "_extract_vympel_ktm.txt"


def main() -> None:
    parts: list[str] = []
    for name in FILES:
        path = BASE / name
        reader = PdfReader(str(path))
        parts.append(f"\n{'=' * 80}\nFILE: {name}\npages: {len(reader.pages)}\n")
        for index, page in enumerate(reader.pages, 1):
            text = page.extract_text() or ""
            parts.append(f"\n--- page {index} ---\n{text}\n")
    OUT.write_text("".join(parts), encoding="utf-8")
    print(f"written {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
