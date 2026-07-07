# -*- coding: utf-8 -*-
"""Проверка сценария техподдержки и email_sent на работающем API."""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:10112"


def req(method, path, data=None):
    url = BASE.rstrip("/") + path
    body = None
    headers = {"Content-Type": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main():
    print(f"API base: {BASE}")
    status, _ = req("GET", "/health/")
    print("health:", status)
    assert status == 200

    _, chat = req("POST", "/api/chats/", {"title": "deploy verify tech support"})
    chat_id = chat["id"]
    print("chat:", chat_id)

    steps = [
        ("Обратная связь", "start", False, True),
        ("Техническая поддержка", "feedback_pick", True, True),
        ("Промышленное оборудование", "tech_support", True, True),
        ("UFG-F test deploy, zav 777", "tech_support_industrial", True, False),
        ("+7 903 111-22-33 deploy-check@example.com", "tech_support_contact", True, False),
    ]

    data = None
    for content, hint_state, hint_locked, is_hint_selection in steps:
        status, data = req(
            "POST",
            f"/api/chats/{chat_id}/messages/",
            {
                "content": content,
                "hint_state": hint_state,
                "hint_locked": hint_locked,
                "is_hint_selection": is_hint_selection,
            },
        )
        hs = data.get("hint_state", {})
        print(
            f"step [{content[:40]}]: http={status} "
            f"state={hs.get('current_state')} email_sent={data.get('email_sent')} "
            f"email_error={data.get('email_error', '')}"
        )

    assert data["hint_state"]["current_state"] == "tech_support_final"
    assert data.get("email_sent") is True, data
    print("TECH SUPPORT DEPLOY VERIFY: OK")


if __name__ == "__main__":
    main()
