"""FAQ-слой поверх RAG на основе файла `чатбот вопрос-ответ.xlsx`."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

from django.conf import settings

from ..attachment_urls import faq_repair_memo_api_path


CONSULTATION_HINT = "Консультация"
REPAIR_ATTACHMENT_TITLE = "Памятка по отправке оборудования"
PERSONAL_CABINET_URL = (
    "https://web.turbo-don.ru/web1C/?n=user&p=turbo-don&/"
    "#e1cib/app/Обработка.ТД_ЛичныйКабинет"
)
REPAIR_EQUIPMENT_FAQ_QUESTION = "Где посмотреть список ремонтных приборов"


_FAQ_ROWS = [
    (
        "Где скачать по для расходомера UFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/ufg-viwer-1.3.172.zip",
    ),
    (
        "Где скачать руководство по эксплуатации UFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/rje_ufg-mod.-f-z-akt-1.pdf",
    ),
    (
        "Где скачать Руководство по эксплуатации на выносной терминал UFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/RE_VT_2020.pdf",
    ),
    (
        "Где скачать Описание типа UFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/ot-ufg-56432-14-do-16.11.2030.pdf",
    ),
    (
        "Где скачать Методика поверки UFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/metodika-poverki-mp-208-112-2024.pdf",
    ),
    (
        "Где скачать по для расходомера TFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/TFG2-S-v2-1-%D0%BA%D0%B0%D0%BD%D0%B0%D0%BB.zip",
    ),
    (
        "Где скачать руководство по эксплуатации TFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/09/rje-na-tfg-2.pdf",
    ),
    (
        "Где скачать Руководство по эксплуатации на выносной терминал TFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/RE_TFG_VT_2020.pdf",
    ),
    (
        "Где скачать Описание типа TFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/OT_TFG_2018-1.pdf",
    ),
    (
        "Где скачать Методика поверки TFG",
        "https://www.turbo-don.ru/wp-content/uploads/2022/08/MP_2018-1.pdf",
    ),
    (
        "Где посмотреть сведения о расходомере? Где посмотреть настроечные параметры?",
        PERSONAL_CABINET_URL,
    ),
    (
        REPAIR_EQUIPMENT_FAQ_QUESTION,
        PERSONAL_CABINET_URL,
    ),
    (
        "Где посмотреть сведения о поверке расходомера?",
        "https://fgis.gost.ru/fundmetrology/cm/results",
    ),
    ("Техподдержка", "Макс + 7 928 960 92 42"),
    (
        "Что необходимо подготовить чтобы провести удаленную диагностику расходомера?",
        "Необходим конвертер интерфейсов RS485-USB, программа RuDesktop или его отечественные аналоги, ноутбук с Windows 10 или 11 со стабильным интернетом",
    ),
    (
        "Как найти сервисный центр по промышленному оборудованию в городе №",
        "ссылка на конкретные СЦ в регионе https://www.turbo-don.ru/diler-card/ooo-kip-inzhiniring/",
    ),
    (
        "Как написать официальное письмо",
        'Директор ООО НПО "ТУРБУЛЕНТНОСТЬ-ДОН" Донцова Анна Егоровна, официальное письмо необходимо отправить на регистрацию на почту info@turbo-don.ru',
    ),
    (
        "Как отправить оборудование для платного или гарантийного ремонта",
        REPAIR_ATTACHMENT_TITLE,
    ),
    (
        "Что необходимо предоставить в техподдержку для предватительной оценки работоспособности расходомера",
        'Необходимо сформировать Отчёт за месяц в ПО UFG Viewer, установив галочки в пунктах "Архив данных", "Основные настройки", "Журнал событий", "Журнал изменений", "Состав газа", а также прислать скриншот вкладки "Диагностика". Все полученные данные прислать с вопросом на почту технической поддержки npo_pto2@turbo-don.ru, либо в мессенджер Макс + 7 928 960 92 42',
    ),
]


_TOKEN_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
_STOP_WORDS = {
    "где",
    "как",
    "что",
    "для",
    "или",
    "по",
    "на",
    "в",
    "с",
    "и",
    "о",
    "об",
    "от",
    "это",
    "нужно",
    "необходимо",
    "можно",
    "скачать",
    "посмотреть",
    "расходомер",
    "расходомера",
}


@dataclass(frozen=True)
class FaqEntry:
    id: str
    question: str
    answer: str
    tokens: frozenset[str]
    normalized: str


@dataclass(frozen=True)
class FaqMatch:
    entry: FaqEntry
    score: float
    mode: str


@dataclass(frozen=True)
class FaqAnswer:
    handled: bool
    text: str = ""
    hints: tuple[str, ...] = ()
    attachment_path: Optional[Path] = None
    attachment_name: str = ""
    match: Optional[FaqMatch] = None
    needs_rag: bool = False
    card: Optional[dict] = None


def _normalize(text: str) -> str:
    value = (text or "").casefold().replace("ё", "е")
    value = re.sub(r"\bуфг\b", " ufg ", value)
    value = re.sub(r"\bтфг\b", " tfg ", value)
    value = re.sub(r"\bвт\b", " выносной терминал ", value)
    value = re.sub(r"\bмп\b", " методика поверки ", value)
    value = re.sub(r"\bот\b", " описание типа ", value)
    value = re.sub(r"\bрэ\b", " руководство эксплуатация ", value)
    value = re.sub(r"\bмануал\w*\b|\bинструкц\w*\b", " руководство эксплуатация ", value)
    value = re.sub(r"\bсофт\w*\b|\bпрограмм\w*\b|\bviewer\b", " software ", value)
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token
        for token in _TOKEN_RE.findall(_normalize(text))
        if len(token) > 1 and token not in _STOP_WORDS
    )


def _looks_like_document_fact_question(text: str) -> bool:
    """Фактические вопросы по РЭ/МП/ОТ/сертификатам должны идти в RAG, не FAQ."""
    raw = (text or "").casefold().replace("ё", "е")
    if not raw:
        return False
    if re.search(r"\b(скачать|ссылка|где взять|открой|загрузить)\b", raw):
        return False
    has_doc_marker = bool(
        re.search(
            r"\b(рэ|руководств|мп|методик|от|описани[ея]\s+типа|паспорт|сертификат|декларац|фгис|приказ|приложени[ея])\b",
            raw,
        )
    )
    asks_document_fact = bool(
        re.search(
            r"(в документе|документа|на страниц|стр\.|что указано|что описано|какой срок|какой номер|какие характеристики)",
            raw,
        )
    )
    return has_doc_marker and asks_document_fact


def _entry_id(question: str) -> str:
    slug = re.sub(r"[^a-zа-я0-9]+", "-", _normalize(question)).strip("-")
    return slug[:80] or "faq"


def _aliases_for_question(question: str) -> str:
    q = _normalize(question)
    aliases = []
    if "скачать software" in q or "скачать по для" in q:
        aliases.extend(["software", "программа", "софт", "драйвер", "viewer"])
    if "руководство" in q:
        aliases.extend(["рэ", "мануал", "инструкция", "эксплуатация"])
    if "описание типа" in q:
        aliases.extend(["от", "описание", "типа", "свидетельство", "регистрационный"])
    if "методика поверки" in q:
        aliases.extend(["мп", "поверка", "методика", "поверить"])
    if "сведения о расходомере" in q:
        aliases.extend(["настроечные", "параметры", "личный кабинет", "серийный"])
    if "список ремонтных приборов" in q:
        aliases.extend(
            [
                "ремонтные",
                "ремонтный",
                "прибор",
                "приборы",
                "оборудование",
                "личный кабинет",
                "кабинет",
                "список",
                "номер",
                "серийный",
                "заводской",
            ]
        )
    if "сведения о поверке" in q:
        aliases.extend(["аршин", "фгис", "результаты", "поверка"])
    if "техподдержка" in q:
        aliases.extend(["техническая поддержка", "контакт", "телефон", "макс"])
    if "удаленную диагностику" in q:
        aliases.extend(["диагностика", "удаленно", "работоспособность", "отчет", "архив", "rudesktop"])
    if "сервисный центр" in q:
        aliases.extend(["сц", "дилер", "регион", "город", "ремонт"])
    if "официальное письмо" in q:
        aliases.extend(["директор", "почта", "регистрация", "обращение"])
    if "отправить оборудование" in q:
        aliases.extend(["ремонт", "гарантийный", "платный", "прибор", "отправка", "сломался", "починить"])
    if "предватительной оценки" in q or "предварительной оценки" in q:
        aliases.extend(["предварительная", "оценка", "работоспособность", "техподдержка", "отчет", "диагностика"])
    return " ".join(aliases)


FAQ_ENTRIES = tuple(
    FaqEntry(
        id=_entry_id(question),
        question=question,
        answer=answer,
        tokens=_tokens(f"{question} {_aliases_for_question(question)}"),
        normalized=_normalize(question),
    )
    for question, answer in _FAQ_ROWS
)


_FAQ_INTENT_WORDS = {
    "скачать",
    "по",
    "руководство",
    "эксплуатации",
    "выносной",
    "терминал",
    "описание",
    "типа",
    "методика",
    "поверки",
    "сведения",
    "настроечные",
    "параметры",
    "техподдержка",
    "диагностика",
    "сервисный",
    "центр",
    "письмо",
    "ремонт",
    "ремонтные",
    "гарантийный",
    "платный",
    "документ",
}


def _jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    sa = set(a)
    sb = set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _coverage(query_tokens: frozenset[str], entry_tokens: frozenset[str]) -> float:
    if not query_tokens or not entry_tokens:
        return 0.0
    return len(query_tokens & entry_tokens) / min(len(query_tokens), len(entry_tokens))


def _contains_model_mismatch(query_tokens: frozenset[str], entry_tokens: frozenset[str]) -> bool:
    models = {"ufg", "tfg", "ufl", "cfm", "gfg", "udm"}
    q_models = query_tokens & models
    e_models = entry_tokens & models
    return bool(q_models and e_models and not (q_models & e_models))


def _score(query: str, entry: FaqEntry) -> float:
    normalized = _normalize(query)
    query_tokens = _tokens(query)
    if not normalized or not query_tokens:
        return 0.0
    if normalized == entry.normalized:
        return 1.0
    if _contains_model_mismatch(query_tokens, entry.tokens):
        return 0.0
    seq = SequenceMatcher(None, normalized, entry.normalized).ratio()
    jac = _jaccard(query_tokens, entry.tokens)
    cov = _coverage(query_tokens, entry.tokens)
    score = 0.45 * seq + 0.35 * cov + 0.20 * jac
    if entry.normalized in normalized or normalized in entry.normalized:
        score = max(score, 0.82)
    return min(1.0, score)


def _entry_by_question_start(prefix: str) -> Optional[FaqEntry]:
    return next((entry for entry in FAQ_ENTRIES if entry.question.startswith(prefix)), None)


def _entry_containing(*parts: str) -> Optional[FaqEntry]:
    lowered = [_normalize(part) for part in parts]
    return next(
        (
            entry
            for entry in FAQ_ENTRIES
            if all(part in entry.normalized for part in lowered)
        ),
        None,
    )


def _entry_repair_equipment_list() -> Optional[FaqEntry]:
    return _entry_by_question_start(REPAIR_EQUIPMENT_FAQ_QUESTION)


def _is_repair_equipment_list_intent(question: str) -> bool:
    """Список ремонтных приборов в личном кабинете — не путать с отправкой на ремонт."""
    raw = (question or "").casefold().replace("ё", "е")
    normalized = _normalize(question)
    if not raw.strip():
        return False

    shipping_markers = (
        "отправ",
        "отправк",
        "гарантийн",
        "платн",
        "почин",
        "сломал",
        "памятк",
        "упаков",
        "пересыл",
    )
    if any(marker in raw for marker in shipping_markers):
        return False

    if "личный кабинет" in raw and "ремонт" in normalized:
        return True

    has_repair_equipment_topic = (
        ("ремонтн" in raw or "ремонтные" in normalized or "ремонтный" in normalized)
        and ("прибор" in raw or "оборудован" in raw)
    )
    if has_repair_equipment_topic:
        return True

    list_markers = ("список", "перечень", "какие", "какой", "где посмотреть", "где найти", "где узнать")
    if any(marker in raw for marker in list_markers) and "ремонт" in normalized and (
        "прибор" in raw or "оборудован" in raw
    ):
        return True

    if re.search(r"\b(на\s+ремонте|в\s+ремонте)\b", raw) and (
        "прибор" in raw or "оборудован" in raw or "расходомер" in raw or "счетчик" in raw
    ):
        return True

    return False


def _special_match(question: str) -> Optional[FaqMatch]:
    raw = (question or "").casefold().replace("ё", "е")
    normalized = _normalize(question)
    tokens = _tokens(question)
    for model in ("UFG", "TFG"):
        model_token = model.casefold()
        if model_token not in tokens:
            continue
        if "терминал" in normalized or "выносной" in normalized:
            entry = next(
                (
                    item
                    for item in FAQ_ENTRIES
                    if "выносной" in item.normalized
                    and "терминал" in item.normalized
                    and model_token in item.tokens
                ),
                None,
            )
            if entry:
                return FaqMatch(entry=entry, score=0.92, mode="terminal_manual_download_intent")
        if re.search(r"\b(мп|методик\w*|поверк\w*)\b", raw):
            entry = _entry_containing("Методика поверки", model)
            if entry:
                return FaqMatch(entry=entry, score=0.93, mode="verification_method_download_intent")
        if re.search(r"\b(от|описани\w*\s+тип\w*)\b", raw):
            entry = _entry_containing("Описание типа", model)
            if entry:
                return FaqMatch(entry=entry, score=0.93, mode="type_description_download_intent")
        if model_token in tokens and "руководство" in tokens and (
            "эксплуатация" in tokens or "эксплуатации" in tokens
        ):
            entry = next(
                (
                    item
                    for item in FAQ_ENTRIES
                    if item.normalized.startswith(
                        _normalize(f"где скачать руководство по эксплуатации {model_token}")
                    )
                ),
                None,
            )
            if entry:
                return FaqMatch(entry=entry, score=0.9, mode="manual_download_intent")
        if (
            ("скач" in raw or "ссыл" in raw or "нужн" in raw or "взять" in raw)
            and re.search(r"\b(по|viewer|software|софт\w*|программ\w*)\b", raw)
        ):
            entry = _entry_containing("по для расходомера", model)
            if entry:
                return FaqMatch(entry=entry, score=0.92, mode="software_download_intent")

    if ("поверк" in raw or "аршин" in raw or "фгис" in raw) and (
        "сведен" in raw
        or "посмотреть" in raw
        or "найти" in raw
        or "проверить" in raw
        or "ссыл" in raw
    ):
        entry = _entry_by_question_start("Где посмотреть сведения о поверке")
        if entry:
            return FaqMatch(entry=entry, score=0.91, mode="verification_registry_intent")

    if (
        "настроеч" in raw
        or ("сведен" in raw and "расходомер" in raw)
        or ("параметр" in raw and "расходомер" in raw)
        or ("данн" in raw and "счетчик" in raw)
        or ("настрой" in raw and "расходомер" in raw)
    ):
        entry = _entry_by_question_start("Где посмотреть сведения о расходомере")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="meter_info_intent")

    if _is_repair_equipment_list_intent(question):
        entry = _entry_repair_equipment_list()
        if entry:
            return FaqMatch(entry=entry, score=0.94, mode="repair_equipment_list_intent")

    if "ремонт" in normalized and "город" in raw and (
        "оборудован" in raw or "оборудования" in tokens
    ):
        entry = _entry_by_question_start("Как найти сервисный центр")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="service_center_intent")

    if "ремонт" in normalized and (
        "отправить" in tokens
        or "отправить" in raw
        or "отправка" in tokens
        or "гарантийный" in tokens
        or "платный" in tokens
        or "починить" in tokens
        or "завод" in raw
        or "счетчик" in raw
    ):
        entry = _entry_by_question_start("Как отправить оборудование")
        if entry:
            return FaqMatch(entry=entry, score=0.92, mode="repair_intent")

    if (
        "памятка" in tokens
        and ("отправке" in tokens or "отправка" in tokens or "оборудования" in tokens)
    ) or (
        "ремонт" in normalized
        and ("сломался" in tokens or "сломан" in tokens or "завод" in raw or "счетчик" in raw)
    ):
        entry = _entry_by_question_start("Как отправить оборудование")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="repair_intent")

    if "диагностики" in tokens or "диагностика" in tokens:
        if "удаленной" in tokens or "удаленно" in tokens or "удаленная" in tokens:
            entry = _entry_by_question_start("Что необходимо подготовить")
            if entry:
                return FaqMatch(entry=entry, score=0.9, mode="remote_diagnostics_intent")

    if "диагност" in normalized and ("удален" in normalized or "удаленн" in normalized):
        entry = _entry_by_question_start("Что необходимо подготовить")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="remote_diagnostics_intent")

    if ("работоспособ" in normalized or "предварительн" in normalized) and (
        "техподдерж" in normalized or "поддерж" in normalized or "оцен" in normalized
    ):
        entry = _entry_by_question_start("Что необходимо предоставить")
        if entry:
            return FaqMatch(entry=entry, score=0.88, mode="support_data_intent")

    if (
        "отчет" in raw
        or "архив" in raw
        or "скриншот" in raw
        or "работоспособ" in normalized
        or ("предварительн" in normalized and ("провер" in normalized or "оцен" in normalized))
    ) and ("поддерж" in raw or "техподдерж" in raw or "расходомер" in raw or "ufg" in tokens):
        entry = _entry_by_question_start("Что необходимо предоставить")
        if entry:
            return FaqMatch(entry=entry, score=0.89, mode="support_data_intent")

    if (
        "дистанцион" in raw
        or "удален" in raw
        or "интернет" in raw
        or "подключен" in raw
    ) and ("диагност" in raw or "проверк" in raw or "оборудован" in raw):
        entry = _entry_by_question_start("Что необходимо подготовить")
        if entry:
            return FaqMatch(entry=entry, score=0.88, mode="remote_diagnostics_intent")

    if (
        ("сервисн" in raw and ("центр" in raw or "город" in raw))
        or "сц" in tokens
        or ("дилер" in raw and ("сервис" in raw or "центр" in raw))
    ):
        entry = _entry_by_question_start("Как найти сервисный центр")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="service_center_intent")

    if ("официальн" in raw and "письм" in raw) or (
        "директор" in raw and ("письм" in raw or "обращен" in raw)
    ) or (
        ("официальн" in raw or "реквизит" in raw or "турбулентность" in raw)
        and ("обращен" in raw or "письм" in raw)
    ):
        entry = _entry_by_question_start("Как написать официальное письмо")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="official_letter_intent")

    if (
        "техподдерж" in raw
        or ("техническ" in raw and ("поддерж" in raw or "вопрос" in raw))
        or ("контакт" in raw and "поддерж" in raw)
        or ("поддержк" in raw and ("телефон" in raw or "контакт" in raw))
    ):
        entry = _entry_by_question_start("Техподдержка")
        if entry:
            return FaqMatch(entry=entry, score=0.9, mode="support_contact_intent")

    return None


def find_best_match(question: str) -> Optional[FaqMatch]:
    special = _special_match(question)
    if special:
        return special

    scores = sorted(
        (FaqMatch(entry=entry, score=_score(question, entry), mode="faq") for entry in FAQ_ENTRIES),
        key=lambda item: item.score,
        reverse=True,
    )
    best = scores[0] if scores else None
    if not best or math.isclose(best.score, 0.0):
        return None
    return best


def _repair_attachment_path() -> Path:
    candidates = [
        Path(settings.BASE_DIR) / "static_faq" / "pamyatka_remont.pdf",
        Path(settings.BASE_DIR).parent.parent / "Памятка.pdf",
    ]
    for path in candidates:
        if path.is_file():
            return path.resolve()
    return candidates[0].resolve()


def _repair_equipment_list_text() -> str:
    return (
        "Сведения о ремонтных приборах доступны в личном кабинете на портале учёта оборудования "
        'НПО «Турбулентность-ДОН».\n\n'
        "Для просмотра списка:\n"
        "1. Нажмите кнопку «Личный кабинет».\n"
        "2. На открывшейся странице входа в систему 1С перейдите на вкладку «Ремонтные приборы».\n"
        "3. В поле поиска укажите заводской или серийный номер — будет доступен список "
        "ремонтных приборов по вашему запросу."
    )


def _format_answer(entry: FaqEntry) -> str:
    if entry.question == REPAIR_EQUIPMENT_FAQ_QUESTION:
        return _repair_equipment_list_text()
    if "сервисный центр" in entry.question.casefold():
        return (
            "Выберите направление: промышленная группа или счётчики газа «Гранд». "
            "Затем укажите страну, регион и нужный сервисный центр."
        )
    if entry.answer.startswith(("http://", "https://")):
        return f"Откройте ссылку:\n{entry.answer}"
    if entry.answer == REPAIR_ATTACHMENT_TITLE:
        return (
            "Памятка по отправке оборудования для платного или гарантийного ремонта.\n\n"
            "Скачайте PDF-файл ниже и приложите к отправке необходимые документы."
        )
    return entry.answer


def _entry_title(entry: FaqEntry) -> str:
    q = entry.question.strip().rstrip("?")
    replacements = [
        ("Где скачать ", ""),
        ("Где посмотреть ", ""),
        ("Как ", ""),
        ("Что необходимо ", ""),
        ("Что ", ""),
    ]
    for old, new in replacements:
        if q.startswith(old):
            q = new + q[len(old):]
            break
    return q[:1].upper() + q[1:]


def _url_action_label(url: str, title: str) -> str:
    low = url.lower()
    if low.endswith(".zip"):
        return "Скачать архив"
    if low.endswith(".pdf"):
        return "Скачать PDF"
    if "fgis.gost.ru" in low:
        return "Открыть реестр ФГИС"
    if "diler-card" in low:
        return "Открыть сервисный центр"
    return "Перейти по ссылке"


def _href_phone(raw: str) -> str:
    digits = re.sub(r"\D+", "", raw)
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    if digits and not digits.startswith("7"):
        digits = "7" + digits
    return f"tel:+{digits}" if digits else ""


def _base_card(entry: FaqEntry, *, title: Optional[str] = None, description: str = "") -> dict:
    return {
        "id": entry.id,
        "title": title or _entry_title(entry),
        "description": description,
        "actions": [],
    }


def _card_for_entry(entry: FaqEntry) -> dict:
    answer = entry.answer.strip()
    if entry.question == REPAIR_EQUIPMENT_FAQ_QUESTION:
        card = _base_card(
            entry,
            title="Ремонтные приборы",
            description=_repair_equipment_list_text(),
        )
        card["actions"].append(
            {
                "type": "url",
                "label": "Личный кабинет",
                "href": PERSONAL_CABINET_URL,
                "value": PERSONAL_CABINET_URL,
            }
        )
        return card

    if answer.startswith(("http://", "https://")):
        title = _entry_title(entry)
        label = _url_action_label(answer, title)
        if answer.lower().endswith(".zip"):
            description = "Архив с программным обеспечением откроется в новой вкладке."
        elif answer.lower().endswith(".pdf"):
            description = "Документ откроется в новой вкладке, его можно скачать."
        elif "fgis.gost.ru" in answer.lower():
            description = "Переход в реестр сведений о поверке расходомеров."
        elif answer == PERSONAL_CABINET_URL:
            description = "Портал со сведениями и настроечными параметрами расходомера."
        else:
            description = "Откройте ресурс в новой вкладке."
        card = _base_card(entry, title=title, description=description)
        card["actions"].append(
            {"type": "url", "label": label, "href": answer, "value": answer}
        )
        return card

    if entry.question == "Техподдержка":
        phone = "+7 928 960 92 42"
        card = _base_card(
            entry,
            title="Техническая поддержка",
            description="Свяжитесь со специалистом по техническим вопросам.",
        )
        card["actions"].append(
            {"type": "phone", "label": f"Макс {phone}", "href": _href_phone(phone), "value": phone}
        )
        return card

    if entry.answer == REPAIR_ATTACHMENT_TITLE:
        card = _base_card(
            entry,
            title="Памятка по отправке оборудования",
            description=(
                "Инструкция для отправки оборудования на платный или гарантийный ремонт. "
                "Скачайте PDF и приложите необходимые документы."
            ),
        )
        card["actions"].append(
            {
                "type": "file",
                "label": "Скачать памятку",
                "href": faq_repair_memo_api_path(),
                "value": "Памятка по отправке оборудования.pdf",
            }
        )
        return card

    if "официальное письмо" in entry.question.casefold():
        card = _base_card(
            entry,
            title="Официальное письмо",
            description='Адресуйте письмо директору ООО НПО "ТУРБУЛЕНТНОСТЬ-ДОН" Донцовой Анне Егоровне.',
        )
        card["actions"].append(
            {"type": "email", "label": "Отправить на info@turbo-don.ru", "href": "mailto:info@turbo-don.ru", "value": "info@turbo-don.ru"}
        )
        return card

    if "сервисный центр" in entry.question.casefold():
        card = _base_card(
            entry,
            title="Сервисные центры",
            description=(
                "Выберите направление: промышленная группа или счётчики газа «Гранд». "
                "Затем укажите страну, регион и нужный сервисный центр."
            ),
        )
        card["picker"] = "service_center"
        return card

    if "предватительной оценки" in entry.question.casefold():
        card = _base_card(
            entry,
            title="Данные для предварительной оценки",
            description=(
                'Сформируйте отчёт за месяц в UFG Viewer: "Архив данных", "Основные настройки", '
                '"Журнал событий", "Журнал изменений", "Состав газа". Приложите скриншот вкладки "Диагностика".'
            ),
        )
        card["actions"].extend(
            [
                {"type": "email", "label": "Написать в техподдержку", "href": "mailto:npo_pto2@turbo-don.ru", "value": "npo_pto2@turbo-don.ru"},
                {"type": "phone", "label": "Макс +7 928 960 92 42", "href": _href_phone("+7 928 960 92 42"), "value": "+7 928 960 92 42"},
            ]
        )
        return card

    if "удаленную диагностику" in entry.question.casefold():
        return _base_card(
            entry,
            title="Удаленная диагностика расходомера",
            description=(
                "Подготовьте конвертер RS485-USB, программу RuDesktop или отечественный аналог, "
                "ноутбук с Windows 10/11 и стабильный интернет."
            ),
        )

    return _base_card(entry, title=_entry_title(entry), description=answer)


def _faq_intent_present(question: str) -> bool:
    return bool(_tokens(question) & _FAQ_INTENT_WORDS)


def answer(question: str, *, from_hint: bool = False) -> FaqAnswer:
    text = (question or "").strip()
    if not text:
        return FaqAnswer(handled=False, needs_rag=True)

    if not from_hint and _looks_like_document_fact_question(text):
        return FaqAnswer(handled=False, needs_rag=True)

    if text.casefold() == CONSULTATION_HINT.casefold():
        return FaqAnswer(
            handled=True,
            text=(
                "Для консультации можно обратиться в техническую поддержку: "
                "Макс +7 928 960 92 42. Также можно написать на info@turbo-don.ru."
            ),
            card={
                "id": "consultation",
                "title": "Консультация",
                "description": "Позвоните или напишите нам, если нужна помощь специалиста.",
                "actions": [
                    {"type": "phone", "label": "+7 (863) 203-77-80", "href": "tel:+78632037780", "value": "+7 (863) 203-77-80"},
                    {"type": "email", "label": "info@turbo-don.ru", "href": "mailto:info@turbo-don.ru", "value": "info@turbo-don.ru"},
                ],
            },
        )

    exact_entry = next(
        (entry for entry in FAQ_ENTRIES if text.casefold() == entry.question.casefold()),
        None,
    )
    match = FaqMatch(exact_entry, 1.0, "faq_hint") if exact_entry else find_best_match(text)
    if not match:
        return FaqAnswer(handled=False, needs_rag=True)

    high_confidence = 0.72
    maybe_confidence = 0.42
    if from_hint or match.score >= high_confidence:
        attachment_path = None
        attachment_name = ""
        if match.entry.answer == REPAIR_ATTACHMENT_TITLE:
            path = _repair_attachment_path()
            if path.is_file():
                attachment_path = path
                attachment_name = "Памятка по отправке оборудования.pdf"
        return FaqAnswer(
            handled=True,
            text=_format_answer(match.entry),
            attachment_path=attachment_path,
            attachment_name=attachment_name,
            match=match,
            card=_card_for_entry(match.entry),
        )

    if match.score >= maybe_confidence and _faq_intent_present(text):
        return FaqAnswer(
            handled=True,
            text=(
                "Похоже, вопрос может относиться к справочному разделу. "
                f"Если нужен ответ из справочника, напишите: «{match.entry.question}». "
                "Если нужна помощь специалиста, напишите: «Консультация». "
                "Или уточните вопрос — я отвечу через базу знаний."
            ),
            match=match,
        )

    return FaqAnswer(handled=False, needs_rag=True, match=match)


def apply_to_context(ctx, *, from_hint: bool = False) -> bool:
    faq_answer = answer(ctx.question, from_hint=from_hint)
    if not faq_answer.handled:
        return False

    ctx.bot_response = faq_answer.text
    ctx.next_state = "start"
    ctx.hint_locked = False
    ctx.rag_llm_ms = 0.0
    ctx.gas_hints = [{"text": hint, "next_state": "start"} for hint in faq_answer.hints]
    ctx.gas_expects = False
    if faq_answer.attachment_path:
        ctx.bot_attachment_path = faq_answer.attachment_path
        ctx.bot_attachment_name = faq_answer.attachment_name
    if faq_answer.card:
        ctx.faq_card = faq_answer.card
    return True
