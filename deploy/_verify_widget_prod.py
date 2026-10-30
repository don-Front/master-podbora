# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://master-turbo-podbor.ru"


def main() -> int:
    html = urllib.request.urlopen(f"{BASE}/podbor-chat/", timeout=20).read().decode("utf-8", "replace")
    scripts = re.findall(r'src="([^"]+)"', html)
    print("scripts", scripts[:3])
    for src in scripts[:2]:
        url = f"{BASE}{src}" if src.startswith("/") else src
        resp = urllib.request.urlopen(url, timeout=20)
        print(url, resp.status, "ok")

    create_req = urllib.request.Request(
        f"{BASE}/podbor-api/api/chats/",
        data=json.dumps({"title": "widget-check"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chat = json.loads(urllib.request.urlopen(create_req, timeout=20).read())
    print("chat id", chat["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
