"""HTTP client for the PaperType API (POST /v1/pdf, GET /v1/me)."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, Union

import httpx

from .errors import AuthError, PaperTypeError, QuotaExceeded, RenderError, TransportError

DEFAULT_BASE_URL = "https://papertype.dev"
ENV_API_KEY = "PAPERTYPE_API_KEY"
ENV_BASE_URL = "PAPERTYPE_BASE_URL"

# Every field POST /v1/pdf accepts. Anything else passed to render() is a TypeError,
# so typos are caught locally instead of being silently ignored by the server.
RENDER_FIELDS = frozenset({
    "html", "markdown", "css", "theme", "page_size",
    "title", "author", "date",
    "cover", "toc", "page_numbers",
    "footer", "header", "filename",
    "template", "data",  # hosted templates: passed through untouched
})


def _version() -> str:
    from . import __version__
    return __version__


def _extract_detail(resp: httpx.Response) -> Any:
    """Return the server's error detail: a string, or a list for validation errors."""
    try:
        body = resp.json()
    except ValueError:
        text = resp.text.strip()
        return text or f"HTTP {resp.status_code}"
    if isinstance(body, dict) and "detail" in body:
        return body["detail"]
    return body


def _detail_to_message(detail: Any) -> str:
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):  # FastAPI/pydantic validation errors
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(x) for x in item.get("loc", []) if x != "body")
                msg = item.get("msg", "")
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(p for p in parts if p) or "validation error"
    return str(detail)


def raise_for_response(resp: httpx.Response) -> None:
    """Map a non-2xx response onto the PaperTypeError hierarchy."""
    if 200 <= resp.status_code < 300:
        return
    status = resp.status_code
    detail = _extract_detail(resp)
    message = f"{_detail_to_message(detail)} (HTTP {status})"
    if status == 401:
        raise AuthError(message, status_code=status, detail=detail)
    if status in (402, 429):
        raise QuotaExceeded(message, status_code=status, detail=detail)
    if status in (400, 413, 422):
        raise RenderError(message, status_code=status, detail=detail)
    raise PaperTypeError(message, status_code=status, detail=detail)


class Client:
    """Synchronous PaperType API client.

    >>> with Client(api_key="dp_...") as c:
    ...     pdf = c.render(markdown="# Hello")

    ``api_key`` defaults to the ``PAPERTYPE_API_KEY`` environment variable;
    ``base_url`` defaults to ``PAPERTYPE_BASE_URL`` or https://papertype.dev.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self.api_key = api_key if api_key is not None else os.environ.get(ENV_API_KEY, "")
        self.api_key = self.api_key.strip()
        if not self.api_key:
            raise AuthError(
                f"No API key. Pass api_key=... or set {ENV_API_KEY}. Get a key at {DEFAULT_BASE_URL}/signup."
            )
        self.base_url = (base_url or os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": f"papertype-python/{_version()}",
                "Accept": "application/pdf, application/json",
            },
        )

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- internals ---------------------------------------------------------
    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        try:
            resp = self._http.request(method, path, **kw)
        except httpx.HTTPError as e:  # connect/read/timeout errors, no response
            raise TransportError(f"{type(e).__name__}: {e}") from e
        raise_for_response(resp)
        return resp

    # -- public API --------------------------------------------------------
    def render(
        self,
        *,
        markdown: Optional[str] = None,
        html: Optional[str] = None,
        css: Optional[str] = None,
        theme: Optional[str] = None,
        page_size: Optional[str] = None,
        template: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        **options: Any,
    ) -> bytes:
        """Render a document and return the PDF bytes.

        Provide ``markdown`` or ``html`` (or ``template`` + ``data`` for a hosted
        template). ``options`` may contain any other POST /v1/pdf field:
        title, author, date, cover, toc, page_numbers, footer, header, filename.
        Unknown option names raise ``TypeError``.
        """
        unknown = sorted(set(options) - RENDER_FIELDS)
        if unknown:
            raise TypeError(f"render() got unexpected option(s): {', '.join(unknown)}. "
                            f"Allowed: {', '.join(sorted(RENDER_FIELDS))}")
        payload: Dict[str, Any] = {
            "markdown": markdown, "html": html, "css": css, "theme": theme,
            "page_size": page_size, "template": template, "data": data,
        }
        payload.update(options)
        payload = {k: v for k, v in payload.items() if v is not None}
        if not any(k in payload for k in ("markdown", "html", "template")):
            raise RenderError("Provide markdown=, html= or template=.")
        resp = self._request("POST", "/v1/pdf", json=payload)
        return resp.content

    def render_to_file(self, path: Union[str, "os.PathLike[str]"], **kwargs: Any) -> Path:
        """Render and write the PDF to ``path``. Returns the path as a ``Path``."""
        pdf = self.render(**kwargs)
        out = Path(path)
        out.write_bytes(pdf)
        return out

    def me(self) -> Dict[str, Any]:
        """Return the key's account info: email, plan, quota, used_this_month, watermark."""
        return self._request("GET", "/v1/me").json()
