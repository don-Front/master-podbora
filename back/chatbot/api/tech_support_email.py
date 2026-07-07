# -*- coding: utf-8 -*-
"""HTML-письмо оператору при обращении в техподдержку (стиль «Запрос ТКП»)."""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from .hints_tree import HINTS_TREE

TECH_SUPPORT_ENTRY = "Техническая поддержка"
EQUIPMENT_HINTS = {"Промышленное оборудование", "Бытовые счетчики"}

_COLORS = {
    "navy": "#002D56",
    "orange": "#FF6600",
    "grey": "#888888",
    "light_grey": "#E8E8E8",
    "text": "#333333",
}


def _known_hint_texts() -> set[str]:
    texts: set[str] = set()
    for node in HINTS_TREE.values():
        for hint in node.get("hints", []):
            text = (hint.get("text") or "").strip()
            if text:
                texts.add(text)
    return texts


def _escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def resolve_region(ip_address: str) -> str:
    """Определяет регион пользователя по IP (ipapi.co, как в админке)."""
    ip = (ip_address or "").strip()
    if not ip or ip in ("0.0.0.0", "127.0.0.1", "Неизвестен"):
        return "Не определён"
    try:
        response = requests.get(
            f"https://ipapi.co/{ip}/json/",
            timeout=5,
            headers={"User-Agent": "Turbo-Don-Chatbot/1.0"},
        )
        if response.status_code != 200:
            return "Не определён"
        data = response.json()
        if data.get("error"):
            return "Не определён"
        parts = [
            p
            for p in (
                data.get("city"),
                data.get("region"),
                data.get("country_name"),
            )
            if p
        ]
        return ", ".join(parts) if parts else "Не определён"
    except Exception as exc:
        print(f"[WARNING] Geo lookup failed for {ip}: {exc}")
        return "Не определён"


def build_tech_support_context(messages: List[dict]) -> Dict[str, str]:
    """
    Извлекает контекст обращения в техподдержку из истории чата.
    """
    msgs = list(messages or [])
    known_hints = _known_hint_texts()

    entry_index: Optional[int] = None
    for idx, msg in enumerate(msgs):
        if msg.get("is_user") and (msg.get("content") or "").strip() == TECH_SUPPORT_ENTRY:
            entry_index = idx
            break

    trigger_message = "—"
    search_until = entry_index if entry_index is not None else len(msgs)
    for idx in range(search_until - 1, -1, -1):
        content = (msgs[idx].get("content") or "").strip()
        if not content:
            continue
        sender = "Клиент" if msgs[idx].get("is_user") else "Бот"
        trigger_message = f"{sender}: {content[:800]}"
        break

    scenario_parts: List[str] = []
    for msg in msgs[: search_until + (1 if entry_index is not None else 0)]:
        if not msg.get("is_user"):
            continue
        text = (msg.get("content") or "").strip()
        if text in known_hints:
            scenario_parts.append(text)

    scenario_path = " → ".join(scenario_parts) if scenario_parts else "Прямой переход"

    user_after_entry = [
        (msg.get("content") or "").strip()
        for msg in msgs[search_until:]
        if msg.get("is_user") and (msg.get("content") or "").strip()
    ]
    if user_after_entry and user_after_entry[0] == TECH_SUPPORT_ENTRY:
        user_after_entry = user_after_entry[1:]

    equipment_type = "Не указано"
    problem_description = "Не указано"
    contact_info = "Не указано"

    if user_after_entry:
        first = user_after_entry[0]
        if first in EQUIPMENT_HINTS:
            equipment_type = first
            if len(user_after_entry) > 1:
                problem_description = user_after_entry[1]
            if len(user_after_entry) > 2:
                contact_info = user_after_entry[2]
        else:
            equipment_type = "Не указано"
            problem_description = first
            if len(user_after_entry) > 1:
                contact_info = user_after_entry[1]

    return {
        "scenario_path": scenario_path,
        "trigger_message": trigger_message,
        "equipment_type": equipment_type,
        "problem_description": problem_description,
        "contact_info": contact_info,
    }


def build_tech_support_html(
    *,
    scenario_path: str,
    trigger_message: str,
    equipment_type: str,
    problem_description: str,
    contact_info: str,
    client_email: str,
    client_phone: str,
    region: str,
    request_time: datetime,
    ip_address: str,
) -> str:
    """Собирает HTML письма в корпоративном стиле Turbo Flow."""
    ts = request_time.strftime("%d.%m.%Y %H:%M:%S")
    ts_short = request_time.strftime("%d.%m.%Y %H:%M:%S")

    email_display = client_email if client_email and client_email != "Не указан" else contact_info
    phone_display = client_phone if client_phone and client_phone != "Не указан" else "—"
    if email_display == contact_info and "@" not in str(email_display):
        email_display = "—"

    problem_short = problem_description
    if len(problem_short) > 120:
        problem_short = problem_short[:117] + "..."

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Обращение в техподдержку</title>
</head>
<body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,Helvetica,sans-serif;color:{_COLORS['text']};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#ffffff;">
          <tr>
            <td style="padding:28px 32px 12px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="vertical-align:top;">
                    <div style="font-size:13px;font-weight:bold;color:{_COLORS['navy']};letter-spacing:0.3px;">
                      ТУРБУЛЕНТНОСТЬ-ДОН
                    </div>
                    <div style="font-size:11px;color:{_COLORS['grey']};margin-top:2px;">Turbo Flow</div>
                  </td>
                  <td align="right" style="vertical-align:top;">
                    <span style="display:inline-block;background:{_COLORS['navy']};color:#ffffff;font-size:11px;font-weight:bold;padding:8px 14px;letter-spacing:0.5px;">
                      ТЕХПОДДЕРЖКА
                    </span>
                  </td>
                </tr>
              </table>
              <h1 style="margin:20px 0 8px 0;font-size:30px;line-height:1.2;color:{_COLORS['navy']};font-weight:bold;">
                Обращение в техподдержку
              </h1>
              <p style="margin:0 0 6px 0;font-size:14px;color:{_COLORS['grey']};">
                Клиент запросил связь с технической поддержкой
              </p>
              <p style="margin:0;font-size:11px;color:#aaaaaa;">
                Чатбот API · внешний API
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:8px 32px 16px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_COLORS['light_grey']};">
                <tr>
                  <td style="padding:20px 22px;">
                    <div style="font-size:16px;font-weight:bold;color:{_COLORS['navy']};margin-bottom:8px;">
                      {_escape(equipment_type)}
                    </div>
                    <div style="font-size:13px;color:{_COLORS['orange']};text-decoration:underline;margin-bottom:16px;">
                      {_escape(scenario_path)}
                    </div>
                    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{_COLORS['navy']};">
                      <tr>
                        <td style="padding:16px 18px;color:#ffffff;">
                          <div style="font-size:10px;letter-spacing:1px;opacity:0.85;margin-bottom:6px;">
                            ОПИСАНИЕ ПРОБЛЕМЫ
                          </div>
                          <div style="font-size:20px;font-weight:bold;line-height:1.35;">
                            {_escape(problem_short)}
                          </div>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 16px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_COLORS['light_grey']};">
                <tr>
                  <td style="padding:16px 22px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:8px;">
                      ПОСЛЕ СООБЩЕНИЯ / СЦЕНАРИЯ
                    </div>
                    <div style="font-size:13px;color:#666666;line-height:1.5;word-break:break-word;">
                      {_escape(trigger_message)}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:0 32px 16px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {_COLORS['light_grey']};">
                <tr>
                  <td style="padding:16px 22px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:8px;">
                      ПОЛНОЕ ОПИСАНИЕ
                    </div>
                    <div style="font-size:13px;color:#666666;line-height:1.5;white-space:pre-wrap;word-break:break-word;">
                      {_escape(problem_description)}
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="background:{_COLORS['navy']};color:#ffffff;text-align:center;padding:14px 24px;font-size:14px;font-weight:bold;">
              Свяжитесь с пользователем для решения проблемы
            </td>
          </tr>

          <tr>
            <td style="padding:24px 32px 8px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="33%" style="vertical-align:top;padding-right:8px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:6px;">РЕГИОН</div>
                    <div style="font-size:14px;color:{_COLORS['text']};">{_escape(region)}</div>
                  </td>
                  <td width="33%" style="vertical-align:top;padding:0 8px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:6px;">ТЕЛЕФОН</div>
                    <div style="font-size:14px;color:{_COLORS['text']};">{_escape(phone_display)}</div>
                  </td>
                  <td width="33%" style="vertical-align:top;padding-left:8px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:6px;">E-MAIL</div>
                    <div style="font-size:14px;color:{_COLORS['text']};word-break:break-all;">{_escape(email_display)}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:8px 32px 24px 32px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="50%" style="vertical-align:top;padding-right:8px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:6px;">ВРЕМЯ ОБРАЩЕНИЯ</div>
                    <div style="font-size:14px;">{_escape(ts)}</div>
                  </td>
                  <td width="50%" style="vertical-align:top;padding-left:8px;">
                    <div style="font-size:10px;letter-spacing:1px;color:{_COLORS['grey']};margin-bottom:6px;">IP АДРЕС</div>
                    <div style="font-size:14px;">{_escape(ip_address)}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="text-align:center;padding:0 32px 28px 32px;font-size:11px;color:#aaaaaa;line-height:1.6;">
              {ts_short}<br>
              Turbo Flow — <a href="https://master-turbo-podbor.ru" style="color:{_COLORS['orange']};text-decoration:underline;">master-turbo-podbor.ru</a>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
