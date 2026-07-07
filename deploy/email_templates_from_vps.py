"""Общие HTML-виджеты писем Turbo Flow (табличная вёрстка, без VML)."""
from __future__ import annotations

import html
import smtplib
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, List, Optional, Tuple

BRAND_NAVY = "#0A2F52"
BRAND_NAVY_LIGHT = "#0D3B66"
BRAND_ORANGE = "#FF6B35"
BRAND_BG = "#0A2F52"
BRAND_CARD_BG = "#F6F8FB"
BRAND_MUTED = "#718096"
GRADIENT = f"linear-gradient(135deg, {BRAND_NAVY} 0%, {BRAND_NAVY_LIGHT} 70%, {BRAND_ORANGE} 100%)"
GRADIENT_SOFT = "linear-gradient(135deg, #f6f8fb 0%, #e9ecef 100%)"
LOGO_URL = "https://turbo-podbor.ru/static/images/logo-turbo-don.png?v=2"
LOGO_CID = "turbo_logo"
SITE_URL = "https://turbo-podbor.ru"
BASE_DIR = Path(__file__).resolve().parent
LOGO_LOCAL = BASE_DIR / "static" / "images" / "logo-turbo-don.png"

FONT = "Arial, Helvetica, sans-serif"
CARD_W = 520
R = "12px"


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def load_logo_bytes() -> Optional[bytes]:
    if LOGO_LOCAL.is_file():
        return LOGO_LOCAL.read_bytes()
    try:
        req = urllib.request.Request(LOGO_URL, headers={"User-Agent": "TurboPodbor/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()
    except Exception:
        return None


def logo_html(use_cid: bool) -> str:
    if use_cid:
        return (
            f'<img src="cid:{LOGO_CID}" alt="Турбулентность-Дон" width="190" height="50" '
            f'style="display:block;border:0;max-width:190px;height:auto;">'
        )
    return (
        f'<div style="font-family:{FONT};font-size:10px;font-weight:700;letter-spacing:0.15em;'
        f'color:{BRAND_ORANGE};">TURBO FLOW</div>'
        f'<div style="font-family:{FONT};font-size:18px;font-weight:700;color:{BRAND_NAVY};'
        f'margin-top:2px;">Турбулентность-ДОН</div>'
    )


def badge_html(text: str) -> str:
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" align="right">
  <tr>
    <td bgcolor="{BRAND_NAVY}" style="background-color:{BRAND_NAVY};background:{GRADIENT};
        border-radius:20px;padding:6px 12px;font-family:{FONT};font-size:10px;font-weight:700;
        color:#FFFFFF;white-space:nowrap;">{esc(text)}</td>
  </tr>
</table>"""


def panel_html(inner: str, *, bgcolor: str = "#FFFFFF", border: str = "#E2E8F0") -> str:
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:separate;border-spacing:0;">
  <tr>
    <td bgcolor="{bgcolor}" style="background-color:{bgcolor};border:1px solid {border};
        border-radius:{R};padding:14px 16px;font-family:{FONT};">
      {inner}
    </td>
  </tr>
</table>"""


def navy_panel_html(inner: str) -> str:
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="border-collapse:separate;border-spacing:0;">
  <tr>
    <td bgcolor="{BRAND_NAVY}" style="background-color:{BRAND_NAVY};background:{GRADIENT};
        border-radius:{R};padding:14px 16px;font-family:{FONT};color:#FFFFFF;">
      {inner}
    </td>
  </tr>
</table>"""


def footer_html(text: str) -> str:
    return f"""
<div style="font-family:{FONT};font-size:11px;color:{BRAND_MUTED};text-align:center;line-height:1.6;">
  {text}<br>
  <span style="color:{BRAND_NAVY};font-weight:600;">Turbo Flow</span> ·
  <a href="{SITE_URL}" style="color:{BRAND_ORANGE};text-decoration:none;">turbo-podbor.ru</a>
</div>"""


def widget_email(*, title: str, badge: str, body_rows: str, footer_text: str, logo_use_cid: bool) -> str:
    """Цельное письмо-виджет: тёмный фон + белая карточка по центру."""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{esc(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:{BRAND_BG};">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{BRAND_BG}"
         style="background-color:{BRAND_BG};">
    <tr>
      <td align="center" style="padding:24px 12px;">
        <table role="presentation" width="{CARD_W}" cellpadding="0" cellspacing="0" bgcolor="#FFFFFF"
               style="width:100%;max-width:{CARD_W}px;background-color:#FFFFFF;border-collapse:separate;
                      border-spacing:0;border-radius:16px;overflow:hidden;">
          <tr>
            <td height="4" bgcolor="{BRAND_ORANGE}" style="background-color:{BRAND_ORANGE};
                font-size:0;line-height:0;">&nbsp;</td>
          </tr>
          <tr>
            <td style="padding:18px 20px 8px;">
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td valign="middle" width="60%">{logo_html(logo_use_cid)}</td>
                  <td valign="middle" width="40%">{badge_html(badge)}</td>
                </tr>
              </table>
            </td>
          </tr>
          {body_rows}
          <tr>
            <td style="padding:8px 20px 20px;">
              {footer_html(footer_text)}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def row_html(content: str, *, pad: str = "0 20px 12px") -> str:
    return f'<tr><td style="padding:{pad};">{content}</td></tr>'


def tkp_open_button_html(url: str) -> str:
    """Кнопка «Открыть ТКП» — ссылка внутри ячейки (кликабельно в mail.ru)."""
    safe_url = esc(url)
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" align="right"
       style="border-collapse:separate;border-spacing:0;">
  <tr>
    <td bgcolor="{BRAND_NAVY}" align="center"
        style="background-color:{BRAND_NAVY};border-radius:10px;padding:0;">
      <a href="{safe_url}" target="_blank" rel="noopener noreferrer"
         style="display:block;padding:10px 14px;font-family:{FONT};text-decoration:none;
                color:#FFFFFF;min-width:100px;box-sizing:border-box;">
        <span style="display:block;font-size:9px;font-weight:700;letter-spacing:0.14em;
            text-transform:uppercase;color:rgba(255,255,255,0.85);margin-bottom:2px;">PDF</span>
        <span style="display:block;font-size:14px;font-weight:700;line-height:1.25;">Открыть ТКП</span>
      </a>
    </td>
  </tr>
</table>"""


def tkp_plain_link_html(url: str) -> str:
    """Текстовая ссылка на ТКП — fallback, если кнопка в почтовом клиенте не кликается."""
    safe_url = esc(url)
    return f"""
<div style="font-family:{FONT};font-size:12px;margin-top:8px;line-height:1.5;">
  <a href="{safe_url}" target="_blank" rel="noopener noreferrer"
     style="color:{BRAND_ORANGE};font-weight:700;text-decoration:underline;">Открыть PDF ТКП пользователя</a>
</div>"""


def send_branded_email(
    *,
    to_email: str,
    subject: str,
    plain_body: str,
    html_body: str,
    embed_logo: bool = True,
    attachments: Optional[List[Tuple[str, bytes]]] = None,
) -> Tuple[bool, Optional[str]]:
    try:
        from email_config import (
            SEND_EMAIL,
            SMTP_PORT,
            SMTP_SERVER,
            SENDER_EMAIL,
            SENDER_PASSWORD,
        )
    except ImportError:
        return False, "email_config не настроен"

    if not SEND_EMAIL:
        return False, None

    logo_bytes = load_logo_bytes() if embed_logo else None

    try:
        msg = MIMEMultipart("mixed")
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        msg["Subject"] = subject

        alt = MIMEMultipart("alternative")
        msg.attach(alt)
        alt.attach(MIMEText(plain_body, "plain", "utf-8"))

        if logo_bytes:
            related = MIMEMultipart("related")
            alt.attach(related)
            related.attach(MIMEText(html_body, "html", "utf-8"))
            img = MIMEImage(logo_bytes, _subtype="png")
            img.add_header("Content-ID", f"<{LOGO_CID}>")
            img.add_header("Content-Disposition", "inline", filename="logo-turbo-don.png")
            related.attach(img)
        else:
            alt.attach(MIMEText(html_body, "html", "utf-8"))

        for fname, data in attachments or []:
            part = MIMEApplication(data, _subtype="pdf")
            part.add_header("Content-Disposition", "attachment", filename=fname)
            msg.attach(part)

        timeout = 20
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=timeout) as server:
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=timeout) as server:
                server.starttls()
                server.login(SENDER_EMAIL, SENDER_PASSWORD)
                server.send_message(msg)
        return True, None
    except Exception as exc:
        return False, str(exc)


def build_verification_code_email(code: str) -> Tuple[str, str]:
    logo_ok = load_logo_bytes() is not None
    plain = f"""Код подтверждения Turbo Flow: {code}

Код действителен 5 минут.
Если вы не запрашивали код, проигнорируйте это письмо.

{SITE_URL}
"""
    code_inner = f"""
<div style="font-size:10px;font-weight:700;letter-spacing:0.1em;text-transform:uppercase;
    color:rgba(255,255,255,0.85);margin-bottom:8px;">Ваш код</div>
<div style="font-size:36px;font-weight:700;letter-spacing:0.25em;line-height:1.1;">{esc(code)}</div>
<div style="font-size:11px;color:rgba(255,255,255,0.75);margin-top:10px;">Действителен 5 минут</div>"""

    hint_inner = f"""
<div style="font-size:14px;color:#2D3748;line-height:1.55;">
  Введите код в форме на сайте
  <a href="{SITE_URL}" style="color:{BRAND_NAVY};font-weight:600;text-decoration:none;">turbo-podbor.ru</a>,
  чтобы подтвердить e-mail и узнать цену.
</div>
<div style="font-size:12px;color:{BRAND_MUTED};margin-top:10px;line-height:1.45;">
  Если вы не запрашивали код — проигнорируйте письмо.
</div>"""

    body = (
        row_html(
            f'<div style="font-family:{FONT};font-size:20px;font-weight:700;color:{BRAND_NAVY};">'
            f"Код подтверждения</div>"
            f'<div style="font-family:{FONT};font-size:13px;color:{BRAND_MUTED};margin-top:4px;">'
            f"Подтверждение e-mail на сайте мастера подбора</div>"
        )
        + row_html(navy_panel_html(code_inner))
        + row_html(panel_html(hint_inner, bgcolor="#FAFBFC"))
    )

    html_body = widget_email(
        title="Код подтверждения",
        badge="Подтверждение",
        body_rows=body,
        footer_text="Автоматическое сообщение",
        logo_use_cid=logo_ok,
    )
    return plain, html_body


def send_demo_verification_email(
    to_email: str = "sktb_razvitie5@turbo-don.ru",
    code: str = "482916",
) -> Tuple[bool, Optional[str]]:
    plain, html_body = build_verification_code_email(code)
    return send_branded_email(
        to_email=to_email,
        subject="[ДЕМО] Код подтверждения Turbo Flow",
        plain_body=plain,
        html_body=html_body,
    )


if __name__ == "__main__":
    ok, err = send_demo_verification_email()
    print("OK" if ok else f"FAIL: {err}")
