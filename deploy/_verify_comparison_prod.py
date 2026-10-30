# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:10112/api"
MASKS = [
    ("irvis_ultra", "ИРВИС-Ультра-Пп-16-DN200-100-ГОТ"),
    ("ktm_600", "КТМ600 РУС 2P01DN100PN0160L0300GB1N-М1-DC5"),
    ("ktm_700", "КТМ700 РУС 2P01DN0050PN0160GB1N20NL3N01AC1"),
    ("ktm_rumass", "КТМ РуМАСС050-0-0-386-00-25-1-1"),
    ("vympel_500", "Вымпел-500-500-И6-0,5-1-4К-01-ТП200-ИБП-БИ-С-G"),
    ("ultramag", "ULTRAMAG-Б-А-PTZ-50-G25-1:160-1-1А-П-R"),
    ("rg_t", "РГ-Т-G400-DN100-PN16-О"),
    ("rsg_signal", "РСГ СИГНАЛ-40-G10-1-PN16-B"),
    ("elmetro_flomak", "ЭЛМЕТРО-Фломак-ExB-S025-LEU-301-RS-LUM-C-G-CZX-IXX"),
    ("elmetro_flous_dru", "ЭЛМЕТРО-Флоус.1-Ex-C050-CI-BN-XXXS-015-OM-AC-G-CZX-XX"),
    ("emis_mass_260", "ЭМИС-МАСС-260 – Ex – 050К – И – Ж – 2,5 – 100 – 24 – А1 – 0,25 – 1,0 – 1,0 – НК – У – ГП – Е – ГОСТ"),
]


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read())


def main() -> int:
    failed = 0
    for catalog_id, mask in MASKS:
        chat = post(f"{BASE}/chats/", {"title": f"cmp-{catalog_id}"})
        resp = post(
            f"{BASE}/chats/{chat['id']}/messages/",
            {
                "content": mask,
                "hint_state": "start",
                "hint_locked": False,
                "is_hint_selection": False,
            },
        )
        card = resp.get("competitor_comparison_card") or {}
        rows = card.get("rows") or []
        labels = [row.get("label") for row in rows]
        ok = card.get("catalog_id") == catalog_id and len(rows) >= 4
        print(
            catalog_id,
            "OK" if ok else "FAIL",
            "rows=",
            len(rows),
            "labels=",
            labels,
        )
        if not ok:
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
