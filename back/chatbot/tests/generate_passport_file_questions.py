# -*- coding: utf-8 -*-
"""Автогенерация N вопросов для аудита RAG по одному passport-файлу из chunks.json."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_CHATBOT_DIR = _TESTS_DIR.parent
_CHUNKS_PATH = _CHATBOT_DIR.parent / "project" / "data" / "chunks.json"
_FILES_LIST = _TESTS_DIR / "_passport_files_list.txt"
_QUESTIONS_DIR = _TESTS_DIR / "passport_file_questions"

_RE_NUM = re.compile(r"±?\d+[,.]?\d*")
_RE_REG = re.compile(r"\d{5}-\d{2}")
_RE_ORDER = re.compile(r"№\s*(\d+)", re.I)
_RE_SECTION = re.compile(r"^\d+(?:\.\d+)*\s+[А-ЯA-ZЁ][^\n]{8,90}", re.M)

# Ограничения для «битых» PDF (fail-otobrazhenija): иначе regex/цикл доп. вопросов зависает.
_MAX_TEXT_SCAN = 200_000
_MAX_SECTIONS = 40
_MAX_REGS = 15
_MAX_NUMS = 30
_MAX_FILLER_ATTEMPTS = 200

_CHUNKS_CACHE: list[dict] | None = None


def _load_chunks() -> list[dict]:
    global _CHUNKS_CACHE
    if _CHUNKS_CACHE is not None:
        return _CHUNKS_CACHE
    raw = json.loads(_CHUNKS_PATH.read_text(encoding="utf-8"))
    _CHUNKS_CACHE = raw if isinstance(raw, list) else raw.get("chunks") or []
    return _CHUNKS_CACHE


def _passport_files() -> list[str]:
    if _FILES_LIST.is_file():
        return [
            ln.strip()
            for ln in _FILES_LIST.read_text(encoding="utf-8").splitlines()
            if ln.strip() and ln.strip() != ".gitkeep"
        ]
    passport_dir = _CHATBOT_DIR.parent / "project" / "data" / "documents" / "passport"
    return sorted(p.name for p in passport_dir.iterdir() if p.is_file() and p.name != ".gitkeep")


def _chunks_for(source_file: str) -> list[dict]:
    out = []
    for ch in _load_chunks():
        meta = ch.get("metadata") or {}
        if meta.get("source_file") == source_file and meta.get("doc_type") == "passport":
            out.append(ch)
    return sorted(out, key=lambda c: (c.get("metadata") or {}).get("page_number") or 0)


def _title_short(source_file: str) -> str:
    return re.sub(r"\.(pdf|PDF|docx|DOCX)$", "", source_file)


def _keys_from_snippet(snippet: str, limit: int = 3) -> list[str]:
    keys: list[str] = []
    for m in _RE_REG.findall(snippet):
        if m not in keys:
            keys.append(m)
    for tok in re.findall(r"[А-ЯA-ZЁ][А-ЯA-ZЁa-zа-яё\-]{2,}|\d+[,.]?\d*", snippet):
        t = tok.strip()
        if len(t) >= 2 and t.lower() not in ("для", "или", "при", "что", "как"):
            if t not in keys:
                keys.append(t)
        if len(keys) >= limit:
            break
    return keys[:limit] or ["документ"]


def _base_templates(title: str, product: str) -> list[tuple[str, str, list[str]]]:
    doc = title[:80]
    prod = product or doc
    return [
        ("назначение", f"Для чего предназначен прибор или документ «{doc}»?", ["назнач", "предназнач", prod.split()[0][:12] if prod else "прибор"]),
        ("изготовитель", f"Кто указан изготовителем или правообладателем в документе «{doc}»?", ["Турбулентность", "изготов", "ДОН"]),
        ("регистрация", f"Какой регистрационный или сертификационный номер указан в «{doc}»?", ["номер", "регистр", "№"]),
        ("срок действия", f"Какой срок действия утверждения типа или сертификата в документе «{doc}»?", ["срок", "действ", "до"]),
        ("методика", f"Какая методика поверки или нормативный документ упомянуты в «{doc}»?", ["методик", "поверк", "МП"]),
        ("метрология", f"Какие метрологические характеристики приведены в документе «{doc}»?", ["погрешност", "диапазон", "измерен"]),
        ("техника", f"Какие технические характеристики (давление, температура, расход) указаны в «{doc}»?", ["давлен", "температур", "расход"]),
        ("ПО", f"Какие сведения о программном обеспечении есть в документе «{doc}»?", ["программ", "ПО", "версия"]),
        ("комплектность", f"Что входит в комплект поставки согласно «{doc}»?", ["комплект", "паспорт", "РЭ"]),
        ("нормативы", f"На какие приказы, ГОСТ или ТУ ссылается документ «{doc}»?", ["приказ", "ГОСТ", "ТУ"]),
    ]


def generate_questions(source_file: str, count: int = 50) -> dict:
    chunks = _chunks_for(source_file)
    title = _title_short(source_file)
    meta0 = (chunks[0].get("metadata") or {}) if chunks else {}
    product = meta0.get("product_title") or title
    is_stub = bool(meta0.get("is_text_stub"))
    full_text = "\n".join((c.get("text") or c.get("content") or "") for c in chunks)
    scan_text = full_text[:_MAX_TEXT_SCAN]

    items: list[dict] = []
    seen_q: set[str] = set()

    def add(topic: str, question: str, keys: list[str]) -> None:
        if len(items) >= count:
            return
        qn = question.strip().lower()
        if qn in seen_q:
            return
        seen_q.add(qn)
        items.append(
            {
                "id": len(items) + 1,
                "topic": topic,
                "question": question,
                "expected_keys": keys[:4],
                "auto_generated": True,
                "is_stub_doc": is_stub,
            }
        )

    for topic, q, keys in _base_templates(title, product):
        add(topic, q, keys)

    for ch in chunks:
        if len(items) >= count:
            break
        page = (ch.get("metadata") or {}).get("page_number")
        text = (ch.get("text") or ch.get("content") or "").strip()
        if len(text) < 40:
            continue
        snippet = re.sub(r"\s+", " ", text)[:220]
        keys = _keys_from_snippet(snippet)
        add(
            f"стр.{page}",
            f"Что указано на странице {page} документа «{title}» о: {snippet[:120]}?",
            keys,
        )

    for sec in _RE_SECTION.findall(scan_text)[:_MAX_SECTIONS]:
        if len(items) >= count:
            break
        sec_clean = re.sub(r"\s+", " ", sec.strip())[:100]
        add(
            "раздел",
            f"Что описано в разделе «{sec_clean}» документа «{title}»?",
            _keys_from_snippet(sec_clean),
        )

    for m in list(dict.fromkeys(_RE_REG.findall(scan_text)))[:_MAX_REGS]:
        if len(items) >= count:
            break
        add(
            "рег.номер",
            f"Где в документе «{title}» упоминается регистрационный номер {m} и в каком контексте?",
            [m, "регистр", "номер"],
        )

    nums = list(dict.fromkeys(_RE_NUM.findall(scan_text)))[:_MAX_NUMS]
    for num in nums:
        if len(items) >= count:
            break
        if len(num) < 2:
            continue
        add(
            "значение",
            f"Какое значение {num} и для какой характеристики указано в документе «{title}»?",
            [num.replace(".", ","), "характеристик", title.split()[0][:10]],
        )

    orders = list(dict.fromkeys(_RE_ORDER.findall(scan_text)))[:8]
    for onum in orders:
        if len(items) >= count:
            break
        add(
            "приказ",
            f"Что говорится в документе «{title}» о приказе № {onum}?",
            [onum, "приказ", "Росстандарт"],
        )

    fillers = [
        ("применение", f"Где и как применяется продукция по документу «{title}»?", ["применен", "эксплуат", "использован"]),
        ("поверка", f"Какие требования к поверке указаны в «{title}»?", ["поверк", "метролог", "эталон"]),
        ("безопасность", f"Какие требования безопасности есть в «{title}»?", ["безопасност", "электр", "охран"]),
        ("маркировка", f"Как наносится маркировка и знак утверждения типа в «{title}»?", ["маркиров", "знак", "типа"]),
        ("гарантия", f"Какие гарантийные обязательства указаны в «{title}»?", ["гарант", "срок", "месяц"]),
        ("транспорт", f"Условия транспортирования и хранения в «{title}»?", ["транспорт", "хранен", "температур"]),
        ("надёжность", f"Показатели надёжности (наработка, срок службы) в «{title}»?", ["наработк", "служб", "отказ"]),
        ("интерфейс", f"Какие интерфейсы связи указаны в «{title}»?", ["RS-485", "интерфейс", "Modbus"]),
        ("взрывозащита", f"Какая взрывозащита или степень защиты IP указана в «{title}»?", ["взрывозащ", "IP", "Ex"]),
        ("испытатель", f"Какой испытательный центр указан в «{title}»?", ["ВНИИМС", "испытатель", "аккредит"]),
    ]
    for topic, q, keys in fillers:
        if len(items) >= count:
            break
        add(topic, q, keys)

    attempts = 0
    while len(items) < count and chunks and attempts < _MAX_FILLER_ATTEMPTS:
        attempts += 1
        ch = chunks[attempts % len(chunks)]
        page = (ch.get("metadata") or {}).get("page_number")
        snippet = re.sub(r"\s+", " ", (ch.get("text") or ch.get("content") or ""))[:160]
        prev = len(items)
        add(
            f"доп.{page}",
            f"Приведите факты из документа «{title}» (фрагмент стр. {page}, #{attempts}): {snippet[:90]}",
            _keys_from_snippet(snippet),
        )
        if len(items) == prev and attempts >= len(chunks) * 2:
            break

    return {
        "source_file": source_file,
        "product": product,
        "questions": items[:count],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file-index", type=int, required=True)
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--all-from", type=int, default=None, help="сгенерировать для всех файлов начиная с индекса")
    args = p.parse_args()
    _QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    files = _passport_files()
    indices = range(args.all_from, len(files)) if args.all_from is not None else [args.file_index]
    for idx in indices:
        sf = files[idx]
        payload = generate_questions(sf, count=args.count)
        stem = re.sub(r"[^\w\-]+", "_", sf, flags=re.UNICODE).strip("_")[:40]
        out = _QUESTIONS_DIR / f"{idx + 1:02d}_{stem}.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"#{idx + 1} {sf}: {len(payload['questions'])} questions -> {out.name}")


if __name__ == "__main__":
    main()
