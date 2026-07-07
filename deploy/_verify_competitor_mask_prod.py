# -*- coding: utf-8 -*-
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check(base: str, label: str) -> None:
    req = urllib.request.Request(
        f"{base}/api/chats/",
        data=json.dumps({"title": "prod-check"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    chat = json.loads(urllib.request.urlopen(req, timeout=20).read())
    payload = json.dumps(
        {
            "content": "РГ-Т-G163-DN100-PN16-О",
            "hint_state": "start",
            "hint_locked": False,
            "is_hint_selection": False,
        }
    ).encode()
    req2 = urllib.request.Request(
        f"{base}/api/chats/{chat['id']}/messages/",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = json.loads(urllib.request.urlopen(req2, timeout=60).read())
    bot = next(m for m in resp["messages"] if not m["is_user"])["content"]
    print(label, "G163" in bot, "нет в РЭ" in bot)
    print(bot[:500])


if __name__ == "__main__":
    check("https://master-turbo-podbor.ru/podbor-api", "prod")
    check("http://127.0.0.1:10112", "local")
