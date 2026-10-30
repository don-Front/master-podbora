# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:10112"
MASKS = [
    ("ktm_700", "КТМ700 РУС 2P01DN0050PN0160GB1N20NL3N01AC1"),
    ("ktm_rumass", "КТМ РуМАСС050-0-0-386-00-25-1-1"),
    ("elmetro_flomak", "ЭЛМЕТРО-Фломак-ExB-S025-LEU-301-RS-LUM-C-G-CZX-IXX"),
    ("elmetro_flous_dru", "ЭЛМЕТРО-Флоус.1-Ex-C050-CI-BN-XXXS-015-OM-AC-G-CZX-XX"),
    (
        "emis_mass_260",
        "ЭМИС-МАСС-260 – Ex – 050К – И – Ж – 2,5 – 100 – 24 – А1 – 0,25 – 1,0 – 1,0 – НК – У – ГП – Е – ГОСТ",
    ),
]


def main() -> int:
    for label, mask in MASKS:
        create_req = urllib.request.Request(
            f"{BASE}/api/chats/",
            data=json.dumps({"title": "check"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        chat = json.loads(urllib.request.urlopen(create_req, timeout=20).read())
        payload = json.dumps(
            {
                "content": mask,
                "hint_state": "start",
                "hint_locked": False,
                "is_hint_selection": False,
            }
        ).encode()
        msg_req = urllib.request.Request(
            f"{BASE}/api/chats/{chat['id']}/messages/",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = json.loads(urllib.request.urlopen(msg_req, timeout=60).read())
        card = resp.get("competitor_mask_card") or {}
        print(
            label,
            "catalog=",
            card.get("catalog_id"),
            "valid=",
            card.get("is_valid"),
            "params=",
            len(card.get("parameters") or []),
            "analog=",
            bool(resp.get("competitor_analog_specs")),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
