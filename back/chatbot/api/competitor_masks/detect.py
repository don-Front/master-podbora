"""Детектор масок конкурентов в свободном тексте."""

from __future__ import annotations

import re

from .catalog import load_competitor_catalogs

_RG_T_MARKER = re.compile(r"РГ[\s\-]*Т|RG[\s\-]*T", re.IGNORECASE)
_RSG_MARKER = re.compile(r"РСГ[\s\-]*СИГНАЛ|RSG[\s\-]*SIGNAL", re.IGNORECASE)
_IRVIS_MARKER = re.compile(r"ИРВИС[\s\-]*УЛЬТРА|IRVIS[\s\-]*ULTRA", re.IGNORECASE)
_ULTRAMAG_MARKER = re.compile(r"ULTRAMAG", re.IGNORECASE)
_KTM_MARKER = re.compile(r"КТМ[\s\-]*600|KTM[\s\-]*600", re.IGNORECASE)
_VYMPEL_MARKER = re.compile(r"ВЫМПЕЛ[\s\-]*500|VYMPEL[\s\-]*500", re.IGNORECASE)
_G_TOKEN = re.compile(r"(?:^|[\s\-/])G(\d+)(?:$|[\s\-/])", re.IGNORECASE)
_DN_TOKEN = re.compile(r"(?:^|[\s\-/])DN(\d+)(?:$|[\s\-/])", re.IGNORECASE)
_KTM_DN = re.compile(r"DN\d+", re.IGNORECASE)
_PN_TOKEN = re.compile(r"(?:^|[\s\-/])PN(\d+)(?:$|[\s\-/])", re.IGNORECASE)
_RSG_DN = re.compile(r"(?:^|[\s\-/])(25|40|50|80|100|150)(?:$|[\s\-/])")


def _normalize_for_detection(text: str) -> str:
    return " ".join((text or "").strip().split())


def _catalog_loaded(catalog_id: str) -> bool:
    return catalog_id in load_competitor_catalogs()


def detect_catalog_id(text: str) -> str | None:
    """Определить каталог конкурента по тексту сообщения."""
    normalized = _normalize_for_detection(text)
    if not normalized:
        return None

    padded = f" {normalized} "

    if _ULTRAMAG_MARKER.search(normalized) and _catalog_loaded("ultramag"):
        return "ultramag"

    if _IRVIS_MARKER.search(normalized) and _DN_TOKEN.search(padded) and _catalog_loaded("irvis_ultra"):
        return "irvis_ultra"

    if _RSG_MARKER.search(normalized) and _G_TOKEN.search(padded) and _catalog_loaded("rsg_signal"):
        return "rsg_signal"

    if _KTM_MARKER.search(normalized) and _KTM_DN.search(normalized) and _catalog_loaded("ktm_600"):
        return "ktm_600"

    if _VYMPEL_MARKER.search(normalized) and _catalog_loaded("vympel_500"):
        return "vympel_500"

    if _RG_T_MARKER.search(normalized) and _G_TOKEN.search(padded) and _catalog_loaded("rg_t"):
        return "rg_t"

    return None


def looks_like_competitor_mask(text: str) -> bool:
    """Похоже ли сообщение на заказную маску конкурента, а не на вопрос к RAG."""
    return detect_catalog_id(text) is not None
