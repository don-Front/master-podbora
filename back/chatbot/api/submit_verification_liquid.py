# -*- coding: utf-8 -*-
"""POST /api/submit-verification-liquid-request на сервисе VERIFICATION_SERVICE_ORIGIN (обычно :8010)."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

LIQUID_SUBMIT_MAX_BYTES = 10 * 1024 * 1024


def submit_verification_liquid_url() -> str:
    full = (getattr(settings, 'SUBMIT_VERIFICATION_LIQUID_URL', None) or '').strip().rstrip('/')
    if full:
        return full
    origin = getattr(settings, 'VERIFICATION_SERVICE_ORIGIN', 'http://master-turbo-podbor.ru')
    return f"{str(origin).rstrip('/')}/api/submit-verification-liquid-request"


def _normalize_url_path(url: str) -> str:
    """Путь из URL: без query/fragment, декодирование, схлопывание // в пути."""
    raw = (url or '').strip()
    if not raw:
        return ''
    path = urlparse(raw).path if '://' in raw else raw.split('?', 1)[0].split('#', 1)[0]
    path = unquote(path or '')
    while '//' in path:
        path = path.replace('//', '/')
    if path and not path.startswith('/'):
        path = '/' + path
    return path


def media_path_from_attachment_url(url: str) -> Optional[str]:
    """Публичный URL вложения → абсолютный путь к файлу на диске."""
    if not url or not isinstance(url, str):
        return None

    from .attachment_urls import extract_chat_attachment_relpath, extract_message_id_from_attachment_url
    from .models import Message

    message_id = extract_message_id_from_attachment_url(url)
    if message_id:
        try:
            msg = Message.objects.get(pk=message_id)
            if msg.attachment:
                p = Path(msg.attachment.path)
                if p.is_file():
                    return str(p)
        except Message.DoesNotExist:
            pass
        except OSError:
            pass

    rel = extract_chat_attachment_relpath(url)
    if rel:
        full = Path(settings.MEDIA_ROOT) / "chat_attachments" / rel
        try:
            if full.is_file():
                return str(full)
        except OSError:
            pass

    path = _normalize_url_path(url)
    if not path:
        return None
    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    if not str(media_url).startswith('/'):
        media_url = '/' + str(media_url)
    media_url = str(media_url)
    if not media_url.endswith('/'):
        media_url = media_url + '/'
    if not path.startswith(media_url):
        base = media_url.rstrip('/') + '/'
        pos = path.find(base)
        if pos >= 0:
            rel_alt = path[pos + len(base) :].lstrip('/')
            if rel_alt:
                full_alt = Path(settings.MEDIA_ROOT) / rel_alt
                try:
                    if full_alt.is_file():
                        return str(full_alt)
                except OSError:
                    pass
        return None
    rel = path[len(media_url) :].lstrip('/')
    if not rel:
        return None
    full = Path(settings.MEDIA_ROOT) / rel
    try:
        if full.is_file():
            return str(full)
    except OSError:
        pass
    return None


def latest_user_attachment_path_for_chat(chat_id) -> Optional[str]:
    """Последнее пользовательское сообщение с файлом — запасной путь к ТЗ на диске."""
    try:
        from .models import Message

        msg = (
            Message.objects.filter(chat_id=chat_id, is_user=True)
            .exclude(attachment='')
            .order_by('-created_at')
            .first()
        )
        if not msg or not msg.attachment:
            return None
        p = Path(msg.attachment.path)
        if p.is_file():
            return str(p)
    except Exception as e:
        logger.debug('latest_user_attachment_path_for_chat: %s', e)
    return None


def resolve_liquid_tz_file_path(chat_id, attachment_url: Optional[str]) -> Optional[str]:
    """Сначала URL из анкеты, если не вышло — последнее вложение пользователя в чате."""
    u = (attachment_url or '').strip()
    if u:
        got = media_path_from_attachment_url(u)
        if got:
            return got
    return latest_user_attachment_path_for_chat(chat_id)


def submit_verification_liquid_request(
    *,
    fullname: str,
    contact: str,
    comment: str,
    tz_file_path: Optional[str] = None,
    timeout: int = 120,
) -> Dict[str, Any]:
    url = submit_verification_liquid_url()
    data = {
        'fullname': fullname or '',
        'contact': contact or '',
        'comment': comment or '',
    }
    files = None
    fh = None
    try:
        if tz_file_path:
            p = Path(tz_file_path)
            if p.is_file():
                size = p.stat().st_size
                if size > LIQUID_SUBMIT_MAX_BYTES:
                    logger.warning('tz_file exceeds %s bytes, omitting: %s', LIQUID_SUBMIT_MAX_BYTES, p)
                else:
                    fh = open(p, 'rb')
                    ctype = mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
                    files = {'tz_file': (p.name, fh, ctype)}
        r = requests.post(url, data=data, files=files, timeout=timeout)
        try:
            out = r.json()
        except Exception:
            out = {'status': 'error', 'message': (r.text or '')[:500]}
        if not isinstance(out, dict):
            out = {'status': 'error', 'message': str(out)}
        if r.status_code and r.status_code >= 400:
            out.setdefault('status', 'error')
        out.setdefault('http_status', r.status_code)
        return out
    except Exception as e:
        logger.warning('submit_verification_liquid_request failed: %s', e)
        return {'status': 'error', 'message': str(e), 'email_sent': False}
    finally:
        if fh is not None:
            try:
                fh.close()
            except Exception:
                pass
