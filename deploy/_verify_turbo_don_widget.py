# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(name: str, ok: bool, detail: object) -> None:
    status = "OK" if ok else "FAIL"
    print(f"{status} | {name} | {detail}")


def main() -> int:
    failed = 0

    try:
        req = urllib.request.Request(
            "https://www.turbo-don.ru/",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")
        has_widget = any(
            token in html
            for token in (
                "master-turbo-podbor.ru",
                "podbor-chat",
                "widget.js",
                "turbo-don-widget",
            )
        )
        refs = re.findall(
            r'https?://[^"\']+(?:widget|podbor|master-turbo)[^"\']*',
            html,
            re.I,
        )
        check("turbo-don.ru widget embed", has_widget, refs[:5] or "no refs")
        failed += 0 if has_widget else 1
    except Exception as exc:
        check("turbo-don.ru widget embed", False, exc)
        failed += 1

    for url in (
        "https://master-turbo-podbor.ru/podbor-chat/widget.js",
        "https://master-turbo-podbor.ru/podbor-chat/",
        "https://master-turbo-podbor.ru/podbor-api/health/",
    ):
        try:
            resp = urllib.request.urlopen(url, timeout=20)
            check(url, resp.status == 200, resp.headers.get("Content-Type", ""))
            failed += 0 if resp.status == 200 else 1
        except Exception as exc:
            check(url, False, exc)
            failed += 1

    try:
        req = urllib.request.Request(
            "https://master-turbo-podbor.ru/podbor-api/api/chats/",
            data=json.dumps({"title": "turbo-don-check"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        chat = json.loads(urllib.request.urlopen(req, timeout=20).read())
        ok = bool(chat.get("id"))
        check("API create chat", ok, chat.get("id"))
        failed += 0 if ok else 1
    except Exception as exc:
        check("API create chat", False, exc)
        failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
