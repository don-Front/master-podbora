from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import Http404

REPAIR_MEMO_DOWNLOAD_NAME = "Памятка по отправке оборудования.pdf"


def static_faq_repair_memo_path() -> Path:
    candidates = [
        Path(settings.BASE_DIR) / "static_faq" / "pamyatka_remont.pdf",
        Path(settings.BASE_DIR).parent.parent / "Памятка.pdf",
        Path(settings.BASE_DIR).parent.parent.parent / "Памятка.pdf",
    ]
    for path in candidates:
        try:
            if path.is_file():
                return path.resolve()
        except OSError:
            continue
    raise Http404("FAQ repair memo file not found")


def _looks_like_repair_memo(name: str) -> bool:
    low = (name or "").casefold()
    return "памятка" in low and "отправ" in low


def resolve_message_attachment(msg):
    """Возвращает (path, download_name). Если media-файл пропал — fallback на static_faq."""
    if not msg.attachment:
        raise Http404

    download_name = (msg.attachment.name or "").replace("\\", "/").split("/")[-1] or "attachment"
    candidates = []
    try:
        candidates.append(Path(msg.attachment.path))
    except (ValueError, OSError):
        pass
    if msg.attachment.name:
        candidates.append(Path(settings.MEDIA_ROOT) / str(msg.attachment.name))

    for path in candidates:
        try:
            if path.is_file():
                return path.resolve(), download_name
        except OSError:
            continue

    if _looks_like_repair_memo(download_name):
        return static_faq_repair_memo_path(), REPAIR_MEMO_DOWNLOAD_NAME

    raise Http404
