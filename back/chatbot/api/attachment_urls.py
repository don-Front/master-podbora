from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote, unquote


def _safe_relpath(relative_name: str) -> str:
    rel = (relative_name or "").strip().replace("\\", "/").lstrip("/")
    parts = [part for part in rel.split("/") if part and part not in ("..", ".")]
    return "/".join(parts)


def message_attachment_api_path(message_id: int) -> str:
    return f"message-attachments/{int(message_id)}/"


def faq_repair_memo_api_path() -> str:
    return "faq-attachments/repair-memo/"


def chat_attachment_api_path(relative_name: str) -> str:
    rel = _safe_relpath(relative_name)
    if not rel:
        return ""
    segments = [quote(unquote(seg), safe="") for seg in rel.split("/") if seg]
    return f"chat-attachments/{'/'.join(segments)}"


def extract_message_id_from_attachment_url(url: str) -> Optional[int]:
    if not url:
        return None
    match = re.search(r"message-attachments/(\d+)/?", str(url))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def extract_chat_attachment_relpath(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"chat-attachments/(.+?)(?:\?|#|$)", str(url))
    if match:
        return unquote(match.group(1))
    match = re.search(r"/media/chat_attachments/(.+?)(?:\?|#|$)", str(url))
    if match:
        return unquote(match.group(1))
    return ""
