# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://master-turbo-podbor.ru"
SITE = "https://www.turbo-don.ru/"


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return resp.read().decode("utf-8", "replace")


def main() -> int:
    failed = 0

    site_html = fetch(SITE)
    has_widget = "podbor-chat/widget.js" in site_html
    print(("OK" if has_widget else "FAIL") + " | turbo-don.ru widget.js")
    failed += 0 if has_widget else 1

    widget_js = fetch(f"{BASE}/podbor-chat/widget.js")
    checks = [
        ("DEFAULT_TEASER_TEXT", "DEFAULT_TEASER_TEXT" in widget_js),
        ("scheduleDefaultTeaser", "scheduleDefaultTeaser" in widget_js),
        ("launcher pulse", "turbo-don-widget-launcher-pulse" in widget_js),
    ]
    for name, ok in checks:
        print(("OK" if ok else "FAIL") + f" | widget.js {name}")
        failed += 0 if ok else 1

    index_html = fetch(f"{BASE}/podbor-chat/")
    js_match = re.search(r"/podbor-chat/static/js/main\.([a-f0-9]+)\.js", index_html)
    if not js_match:
        print("FAIL | main js hash")
        return 1
    js_hash = js_match.group(1)
    main_js = fetch(f"{BASE}/podbor-chat/static/js/main.{js_hash}.js")
    ok_bundle = "shouldScheduleGreetingTeaser" in main_js and "FALLBACK_HINTS_START" in main_js
    print(("OK" if ok_bundle else "FAIL") + f" | bundle main.{js_hash}.js")
    failed += 0 if ok_bundle else 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
