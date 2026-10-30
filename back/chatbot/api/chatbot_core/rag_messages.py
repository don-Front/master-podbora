"""Пользовательские сообщения RAG: серверная ошибка vs неудачный ответ LLM."""

from __future__ import annotations

MSG_SERVER_ERROR = "Извините, произошла серверная ошибка."
MSG_REPHRASE = (
    "Не удалось подготовить ответ по вашему вопросу. "
    "Попробуйте переформулировать его или задать по-другому."
)

_SYSTEM_ERROR_MARKERS = (
    "connection",
    "connect",
    "refused",
    "unreachable",
    "network",
    "socket",
    "timeout",
    "timed out",
    "502",
    "503",
    "504",
    "api connection",
    "failed to establish",
    "connection error",
    "connection refused",
    "getaddrinfo",
    "name or service not known",
    "ssl",
    "certificate",
    "proxy",
    "lm studio",
    "openai",
    "httpx",
    "httpcore",
    "401",
    "403",
    "invalid_api_key",
    "invalid_request_error",
    "malformed lm studio api token",
    "api token is required",
)


def _looks_like_system_error(text: str) -> bool:
    msg = (text or "").lower()
    return any(marker in msg for marker in _SYSTEM_ERROR_MARKERS)


def is_llm_system_error(exc: BaseException) -> bool:
    """True для сбоев инфраструктуры (LLM недоступен, сеть, таймаут)."""
    return _looks_like_system_error(f"{type(exc).__name__} {exc}")


def is_llm_system_error_text(text: str) -> bool:
    """True для текстового описания инфраструктурной ошибки LLM."""
    return _looks_like_system_error(text)
