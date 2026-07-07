from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "service_centers.json"


@lru_cache(maxsize=1)
def get_service_center_catalog() -> dict:
    if not _CATALOG_PATH.is_file():
        return {"categories": {}}
    with _CATALOG_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        return {"categories": {}}
    categories = data.get("categories")
    if not isinstance(categories, dict):
        return {"categories": {}}
    return {"categories": categories}
