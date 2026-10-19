"""Exception hierarchy for the PaperType SDK.

Every error raised for a non-2xx API response carries ``status_code`` and
``detail`` (the server's own message) and is a subclass of ``PaperTypeError``.
"""
from __future__ import annotations

from typing import Any, Optional


class PaperTypeError(Exception):
    """Base class for all SDK errors. Also raised directly for unexpected HTTP statuses."""

    def __init__(self, message: str, *, status_code: Optional[int] = None, detail: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class AuthError(PaperTypeError):
    """HTTP 401: the API key is missing, malformed, or revoked."""


class QuotaExceeded(PaperTypeError):
    """HTTP 429 (or 402): the key's monthly document quota is used up."""


class RenderError(PaperTypeError):
    """HTTP 400, 413 or 422: the server rejected the document (missing source,
    input too large, or a rendering failure). ``detail`` says why."""


class TransportError(PaperTypeError):
    """The request never produced an HTTP response (connection refused, timeout, DNS)."""
