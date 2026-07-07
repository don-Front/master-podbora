# -*- coding: utf-8 -*-
"""Smoke-тест RAG: UFG+TFG, rag_sources в API, без inline [Документ: …]."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("PODBOR_API", "http://127.0.0.1:10112/api")
QUESTION = "Под какие диапазоны давления существуют серия расходомеров UFG и TFG?"


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    chat = _post(f"{API}/chats/", {"title": "RAG test"})
    chat_id = chat["id"]
    print(f"chat_id={chat_id}")

    result = _post(
        f"{API}/chats/{chat_id}/messages/",
        {
            "content": QUESTION,
            "hint_state": "start",
            "is_hint_selection": "false",
            "hint_locked": "false",
        },
    )

    bot = next((m for m in result.get("messages", []) if not m.get("is_user")), {})
    text = (bot.get("content") or "").strip()
    sources = result.get("rag_sources") or []

    print("--- bot (first 500 chars) ---")
    print(text[:500])
    print("--- checks ---")
    print("inline_citations:", "[Документ:" in text)
    print("rag_sources_count:", len(sources))
    for i, src in enumerate(sources[:4], 1):
        actions = src.get("actions") or []
        href = actions[0].get("href") if actions else ""
        print(f"  [{i}] {src.get('title')} | {src.get('description')} | {href}")

    ok = bool(text) and "[Документ:" not in text and len(sources) >= 1
    low = text.lower()
    has_ufg = "ufg" in low
    has_tfg = "tfg" in low
    print("mentions_ufg:", has_ufg)
    print("mentions_tfg:", has_tfg)
    print("RESULT:", "OK" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as exc:
        print("API error:", exc, file=sys.stderr)
        raise SystemExit(2)
