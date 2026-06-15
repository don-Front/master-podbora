# -*- coding: utf-8 -*-
"""
Генератор 3 вопросов на каждый PDF из documents/.
Использует ручные вопросы (если есть) или чанки из chunks.json.

Запуск из back/chatbot:
  py tests/generate_rag_3q_per_file.py
"""

from __future__ import annotations

import glob
import json
import os
import re
from collections import defaultdict

_TESTS = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.normpath(os.path.join(_TESTS, "..", "..", "project", "data", "documents"))
_CHUNKS = os.path.normpath(os.path.join(_TESTS, "..", "..", "project", "data", "chunks.json"))
_MANUAL = os.path.join(_TESTS, "rag_benchmark_questions.json")
_OUT = os.path.join(_TESTS, "rag_3q_per_file.json")
_PER_FILE = 3

_STOP = {
    "который", "которая", "которые", "данный", "данная", "данные", "документ",
    "указано", "указан", "указана", "согласно", "настоящий", "настоящего",
    "является", "применяется", "описание", "характеристика", "значение",
    "товар", "название", "раздел", "страница", "таблица", "приложение",
}


def _q(source_file: str, id_: int, topic: str, question: str, keys: list[str]) -> dict:
    return {
        "source_file": source_file,
        "id": id_,
        "topic": topic,
        "question": question,
        "expected_keys": keys,
    }


def _keywords(text: str, n: int = 3) -> list[str]:
    words = re.findall(r"[а-яёa-z0-9][а-яёa-z0-9\-\./]{2,}", text.lower().replace("ё", "е"))
    scored: dict[str, int] = {}
    for w in words:
        if w in _STOP or (w.isdigit() and len(w) < 3):
            continue
        if re.match(r"^\d+$", w):
            scored[w] = scored.get(w, 0) + 3
        elif len(w) >= 6:
            scored[w] = scored.get(w, 0) + 3
        elif len(w) >= 4:
            scored[w] = scored.get(w, 0) + 2
        else:
            scored[w] = scored.get(w, 0) + 1
    ranked = sorted(scored.items(), key=lambda x: (-x[1], -len(x[0])))
    out: list[str] = []
    for w, _ in ranked:
        if w not in out:
            out.append(w)
        if len(out) >= n:
            break
    stem = (text.split(".")[0] or text)[:80].strip()
    if stem and len(stem) >= 8:
        out = [stem[:40]] + [k for k in out if k not in stem][: n - 1]
    return out[:n] or ["документ"]


def _topic_from_chunk(chunk: dict) -> str:
    meta = chunk.get("metadata") or {}
    return meta.get("document_name") or chunk.get("product_title") or "документ"


def _question_from_chunk(source_file: str, chunk: dict, qid: int) -> dict:
    topic = _topic_from_chunk(chunk)
    content = (chunk.get("content") or "").strip()
    keys = _keywords(content, 3)
    sentence = re.split(r"[.!?\n]", content)
    sentence = next((s.strip() for s in sentence if len(s.strip()) > 40), content[:200])
    short = sentence[:120].strip()
    if len(short) < 20:
        short = topic
    question = f"Что указано в документе «{topic}» ({source_file}) о: {short[:80]}?"
    return _q(source_file, qid, topic[:60], question, keys)


def _load_manual() -> dict[str, list[dict]]:
    if not os.path.isfile(_MANUAL):
        return {}
    data = json.load(open(_MANUAL, encoding="utf-8"))
    items = data.get("questions") or data if isinstance(data, list) else []
    by_file: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_file[item["source_file"]].append(item)
    return by_file


def _load_chunks_by_file() -> dict[str, list[dict]]:
    data = json.load(open(_CHUNKS, encoding="utf-8"))
    chunks = data.get("chunks") or []
    by_file: dict[str, list[dict]] = defaultdict(list)
    for ch in chunks:
        meta = ch.get("metadata") or {}
        sf = meta.get("source_file") or ch.get("source_file")
        if sf and meta.get("doc_type") in ("gost", "passport", None) or sf:
            if meta.get("doc_type") in ("gost", "passport") or (
                sf and not ch.get("product_url")
            ):
                by_file[sf].append(ch)
    return by_file


def _pick_chunks(chunks: list[dict], n: int) -> list[dict]:
    if len(chunks) <= n:
        return chunks
    step = max(1, len(chunks) // n)
    picked = [chunks[i * step] for i in range(n)]
    return picked[:n]


def main() -> None:
    pdfs = sorted(
        {os.path.basename(p) for p in glob.glob(os.path.join(_DOCS, "**", "*.*"), recursive=True)
         if p.lower().endswith((".pdf", ".docx", ".txt"))}
    )
    manual = _load_manual()
    by_file = _load_chunks_by_file()
    all_q: list[dict] = []
    no_chunks: list[str] = []

    for name in pdfs:
        qs: list[dict] = []
        if name in manual:
            qs = list(manual[name][: _PER_FILE])
        if name in by_file and by_file[name]:
            picked = _pick_chunks(by_file[name], _PER_FILE)
            for i, ch in enumerate(picked):
                if len(qs) >= _PER_FILE:
                    break
                qid = len(qs) + 1
                qs.append(_question_from_chunk(name, ch, qid))
        if not by_file.get(name):
            if name not in no_chunks:
                no_chunks.append(name)
        while len(qs) < _PER_FILE:
            n = len(qs) + 1
            qs.append(
                _q(
                    name,
                    n,
                    f"Тема {n}",
                    f"По документу ({name}): какое содержание в разделе {n}?",
                    ["документ", name.split(".")[0][:20].lower()],
                )
            )
        for item in qs[:_PER_FILE]:
            qtext = item.get("question", "")
            if name.casefold() not in qtext.casefold():
                item = dict(item)
                item["question"] = f"По документу ({name}): {qtext}"
            all_q.append(item)

    payload = {
        "version": 1,
        "per_file": _PER_FILE,
        "total_files": len(pdfs),
        "total_questions": len(all_q),
        "files_without_chunks": no_chunks,
        "questions": all_q,
    }
    with open(_OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Written {len(all_q)} questions for {len(pdfs)} files -> {_OUT}")
    if no_chunks:
        print(f"WARNING: {len(no_chunks)} files without chunks (RAG cannot answer)")


if __name__ == "__main__":
    main()
