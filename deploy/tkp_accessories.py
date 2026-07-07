# -*- coding: utf-8 -*-
"""POST /api/tkp-accessories — дополнительные комплектующие для ТКП."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TkpAccessoriesRequest(BaseModel):
    equipment: Dict[str, Any]
    dn: Optional[float] = None
    pressure_max_mpa: Optional[float] = None
    accuracy_percent: float = 1.0


class TkpAccessoryRow(BaseModel):
    id: str
    name: str
    desc: str
    price: Optional[int] = None


class TkpAccessoriesResponse(BaseModel):
    status: str = "success"
    equipment_id: str
    tkp_profile: str
    accessories: List[TkpAccessoryRow]
    note: Optional[str] = None


_GENERIC_ACCESSORIES: List[Dict[str, Any]] = [
    {
        "id": "straight",
        "name": "Прямые участки",
        "desc": "Прямые участки необходимые для формирования потока",
        "price": None,
    },
    {
        "id": "sensors",
        "name": "Датчики давления и температуры",
        "desc": "Датчики давления Turbo Flow PS + датчик температуры",
        "price": None,
    },
    {
        "id": "spool",
        "name": "Катушка-имитатор",
        "desc": "Для замены прибора без остановки процесса",
        "price": None,
    },
    {
        "id": "cable",
        "name": "Кабель связи",
        "desc": "Кабель RS-485 (15 м) + клеммная коробка (стандарт)",
        "price": None,
    },
]


def tkp_discovery_message() -> Dict[str, Any]:
    return {
        "status": "ok",
        "message": "POST с телом TkpAccessoriesRequest (equipment + dn + pressure_max_mpa + accuracy_percent). См. /docs.",
        "post_paths": ["/api/tkp-accessories", "/api/tkp_accessories"],
    }


def _norm_id(raw: Any) -> str:
    return str(raw or "").strip().lower()


def _fmt_dn(dn: Optional[float]) -> str:
    if dn is None:
        return "100"
    try:
        return str(int(round(float(dn))))
    except (TypeError, ValueError):
        return "100"


def _fmt_pressure_mpa(pressure: Optional[float]) -> str:
    if pressure is None:
        return "1.6"
    try:
        value = float(pressure)
    except (TypeError, ValueError):
        return "1.6"
    text = f"{value:g}"
    return text.replace(".", ",")


def _resolve_profile(equipment_id: str) -> str:
    eid = _norm_id(equipment_id)
    if not eid:
        return "generic"
    if eid in {"ufgfc", "ufg-f-c", "ufgfc1"} or "ufg-f-c" in eid or eid.startswith("ufgfc"):
        return "ufg-f-c"
    if eid in {"ufg2", "ufgfv", "ufg-f-v", "ufg_f_v"} or "ufg-f-v" in eid or eid.startswith("ufg2"):
        return "ufg-f-v"
    if eid.startswith("cfm") or "cfm" in eid:
        return "cfm"
    if eid.startswith("ufl") or eid == "ufl1":
        return "ufl"
    if eid.startswith("gfg"):
        return "generic"
    return "generic"


def _ufg_accessories(model_code: str, dn_text: str, pressure_text: str) -> List[TkpAccessoryRow]:
    return [
        TkpAccessoryRow(
            id="kmch",
            name="Комплект монтажных частей",
            desc="КМЧ УЗПР (углеродистая сталь, стандарт ОСТ)",
            price=47783,
        ),
        TkpAccessoryRow(
            id="flange_kit",
            name="Комплект ответных фланцев",
            desc=f"Комплект ответных фланцев {model_code} Ду{dn_text} ({pressure_text} МПа)",
            price=4158,
        ),
        TkpAccessoryRow(
            id="flow_straightener",
            name="Устройство формирования потока (УФП)",
            desc=f"УФП-{dn_text} (корпус С, ГОСТ)",
            price=22834,
        ),
        TkpAccessoryRow(
            id="straight",
            name="Прямые участки, комплект (20Dn + 5Dn)",
            desc="ПУУ до и после прибора (низкотемп. угл. сталь)",
            price=None,
        ),
        TkpAccessoryRow(
            id="pressure_sensor",
            name="Датчик давления",
            desc="Turbo Flow PS-BP-10-ДИ-25000 кПа-0,15%-Exi",
            price=46616,
        ),
        TkpAccessoryRow(
            id="temp_sensor",
            name="Датчик температуры",
            desc=f"Преобразователь температуры UFG-050-16.05.20.000-08 (Dn15-100 кр/кр, ПУУ 5Dn)",
            price=30356,
        ),
        TkpAccessoryRow(
            id="spool",
            name="Катушка-имитатор",
            desc=f"Катушка-имитатор {model_code}, Ду {dn_text}, 2 луча",
            price=14339,
        ),
        TkpAccessoryRow(
            id="cable",
            name="Кабель связи",
            desc="Кабель RS-485 (15 м) + клеммная коробка (стандарт)",
            price=49735,
        ),
        TkpAccessoryRow(
            id="terminal",
            name="Терминал выносной",
            desc="Терминал выносной ВТ.00.00.000 (12В, 1 канал)",
            price=91470,
        ),
        TkpAccessoryRow(
            id="psu",
            name="Блок питания",
            desc="БПИ-12-18-1-NY (без USB, 1 ПП)",
            price=49800,
        ),
        TkpAccessoryRow(
            id="calibration",
            name="Поверка",
            desc=(
                "Поверка: Комплекс-расходомер газа UFG (до 4 лучей) с учётом ДД и ДТ, "
                f"Ду 50–200, КТ 1,0% — стандарт завода-изготовителя"
            ),
            price=66083,
        ),
    ]


def _cfm_accessories(dn_text: str) -> List[TkpAccessoryRow]:
    return [
        TkpAccessoryRow(
            id="kmch",
            name="Комплект монтажных частей",
            desc="КМЧ CFM (углеродистая сталь)",
            price=64785,
        ),
        TkpAccessoryRow(
            id="spool",
            name="Катушка-имитатор",
            desc="Катушка-имитатор CFM (углеродистая сталь)",
            price=161140,
        ),
        TkpAccessoryRow(
            id="cable",
            name="Кабель связи",
            desc="Кабель RS-485 (15 м) + клеммная коробка (стандарт)",
            price=49735,
        ),
        TkpAccessoryRow(
            id="terminal",
            name="Терминал выносной",
            desc="Терминал выносной ВТ.00.00.000 (12В, 1 канал)",
            price=91470,
        ),
        TkpAccessoryRow(
            id="psu",
            name="Блок питания",
            desc="БПИ-12-18-1-NY (без USB, 1 ПП)",
            price=49800,
        ),
        TkpAccessoryRow(
            id="calibration",
            name="Поверка",
            desc=f"Поверка CFM на заводе-изготовителе (Ду {dn_text}, КТ 1%)",
            price=25498,
        ),
    ]


def _ufl_accessories(dn_text: str, pressure_text: str) -> List[TkpAccessoryRow]:
    return [
        TkpAccessoryRow(
            id="kmch",
            name="Комплект монтажных частей",
            desc="КМЧ УЗПР (углеродистая сталь, стандарт ОСТ)",
            price=47783,
        ),
        TkpAccessoryRow(
            id="flange_kit",
            name="Комплект ответных фланцев",
            desc=f"Комплект ответных фланцев UFL Ду{dn_text} ({pressure_text} МПа)",
            price=40862,
        ),
        TkpAccessoryRow(
            id="straight",
            name="Прямые участки, комплект (20Dn + 5Dn)",
            desc=(
                f"Прямые участки UFL, комплект (10Dn до + 6Dn после), Ду{dn_text} "
                f"({pressure_text} МПа, нерж.), кл.т. 1.0%"
            ),
            price=1532257,
        ),
        TkpAccessoryRow(
            id="cable",
            name="Кабель связи",
            desc="Кабель RS-485 (15 м) + клеммная коробка (стандарт)",
            price=49735,
        ),
        TkpAccessoryRow(
            id="terminal",
            name="Терминал выносной",
            desc="Терминал выносной ВТ.00.00.000 (12В, 1 канал)",
            price=91470,
        ),
        TkpAccessoryRow(
            id="psu",
            name="Блок питания",
            desc="БПИ-12-18-1-NY (без USB, 1 ПП)",
            price=49800,
        ),
        TkpAccessoryRow(
            id="calibration",
            name="Поверка",
            desc=f"Поверка UFL на заводе-изготовителе (Ду {dn_text}, КТ 1%)",
            price=25498,
        ),
    ]


def _generic_accessories() -> List[TkpAccessoryRow]:
    return [TkpAccessoryRow(**row) for row in _GENERIC_ACCESSORIES]


def _build_accessories(profile: str, dn: Optional[float], pressure: Optional[float]) -> List[TkpAccessoryRow]:
    dn_text = _fmt_dn(dn)
    pressure_text = _fmt_pressure_mpa(pressure)
    if profile == "ufg-f-c":
        return _ufg_accessories("UFG-F-C", dn_text, pressure_text)
    if profile == "ufg-f-v":
        return _ufg_accessories("UFG-F-V", dn_text, pressure_text)
    if profile == "cfm":
        return _cfm_accessories(dn_text)
    if profile == "ufl":
        return _ufl_accessories(dn_text, pressure_text)
    return _generic_accessories()


def tkp_accessories_from_request(body: TkpAccessoriesRequest) -> TkpAccessoriesResponse:
    equipment_raw = body.equipment or {}
    equipment_id = _norm_id(equipment_raw.get("id") or equipment_raw.get("equipment_id"))
    profile = _resolve_profile(equipment_id)

    try:
        accessories = _build_accessories(profile, body.dn, body.pressure_max_mpa)
    except Exception as exc:
        logger.exception(
            "tkp_accessories profile=%s equipment_id=%s failed: %s",
            profile,
            equipment_id,
            exc,
        )
        profile = "generic"
        accessories = _generic_accessories()

    return TkpAccessoriesResponse(
        equipment_id=equipment_id or "unknown",
        tkp_profile=profile,
        accessories=accessories,
        note=None,
    )
