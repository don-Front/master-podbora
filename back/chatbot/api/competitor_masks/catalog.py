"""Загрузка справочников масок конкурентов из YAML."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _competitors_data_dir() -> str:
    current_file = os.path.abspath(__file__)
    project_root = os.path.normpath(
        os.path.join(os.path.dirname(current_file), "..", "..", "..", "project")
    )
    return os.path.join(project_root, "data", "competitors")


@lru_cache(maxsize=1)
def load_competitor_catalogs() -> dict[str, dict[str, Any]]:
    """Загрузить все YAML-каталоги из back/project/data/competitors/."""
    catalogs: dict[str, dict[str, Any]] = {}
    data_dir = _competitors_data_dir()
    if not os.path.isdir(data_dir):
        logger.warning("Competitor catalogs directory not found: %s", data_dir)
        return catalogs

    for name in sorted(os.listdir(data_dir)):
        if not name.endswith(".yaml"):
            continue
        path = os.path.join(data_dir, name)
        try:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            catalog_id = str(data.get("id") or name[:-5])
            catalogs[catalog_id] = data
        except Exception as exc:
            logger.exception("Failed to load competitor catalog %s: %s", path, exc)
    return catalogs


def get_catalog(catalog_id: str) -> dict[str, Any] | None:
    """Вернуть каталог по id или None."""
    return load_competitor_catalogs().get(catalog_id)
