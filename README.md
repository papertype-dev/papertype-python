# papertype

Official Python SDK and command-line tool for the [PaperType](https://papertype.dev) API:
send Markdown or HTML, get a PDF back.

Full API reference: https://papertype.dev/docs

## Install

```
pip install papertype
```

Requires Python 3.9 or newer. The only dependency is `httpx`.

## Authentication

Get an API key at https://papertype.dev/signup (keys start with `dp_`). The SDK and
CLI read it from the `PAPERTYPE_API_KEY` environment variable, or you can pass it
explicitly:

```
export PAPERTYPE_API_KEY=dp_...
```

The key is sent as `Authorization: Bearer dp_...` on every request. Treat it like a
password; it is not stored anywhere by this package.

## Quick start: Python

```python
from papertype import Client

with Client() as client:                      # uses PAPERTYPE_API_KEY
    pdf = client.render(markdown="# Hello\n\nIt works.", theme="report", cover=True)
    open("hello.pdf", "wb").write(pdf)

    # or straight to a file
    client.render_to_file("report.pdf", html="<h1>Receipt</h1><p>Thanks.</p>", page_size="Letter")

    # account info: plan, quota, used_this_month, watermark
    print(client.me())
```

`Client(api_key=None, base_url="https://papertype.dev", timeout=60.0)` is also a
context manager; call `close()` if you don't use `with`.

`render()` accepts exactly the fields of `POST /v1/pdf`:

| Keyword | Type | Notes |
|---|---|---|
| `markdown` | str | Markdown source (tables, fenced code, footnotes, admonitions). |
| `html` | str | HTML document or fragment. Takes precedence over `markdown`. |
| `css` | str | Extra CSS appended after the theme; `@page` rules allowed. |
| `theme` | str | `clean` (default), `report`, `minimal`, `letter`, or `none` (your CSS only). |
| `page_size` | str | `A4` (default), `Letter`, `Legal`, `A5`. |
| `title`, `author`, `date` | str | Cover page and PDF metadata. |
| `cover`, `toc`, `page_numbers` | bool | Cover page; table of contents (Markdown only); page numbers (default on). |
| `footer`, `header` | str | Per-page footer (bottom-left) and running header (top-right). |
| `filename` | str | Suggested download filename. |
| `template`, `data` | str, dict | Hosted template name and its data; passed through unchanged. |

Unknown keyword names raise `TypeError` locally so typos are not silently dropped.

## Quick start: CLI

```
papertype render README.md -o readme.pdf
papertype render report.md -o report.pdf --theme report --page-size Letter --cover --toc
papertype render page.html --html -o page.pdf --css extra.css
cat notes.md | papertype render - -o notes.pdf
papertype me
papertype --version
```

Options: `--api-key KEY` (or `PAPERTYPE_API_KEY`), `--base-url URL`, `--timeout SECONDS`.
`-o -` writes the PDF to stdout. Without `-o`, the output is the input name with a
`.pdf` extension.

Exit codes: `0` success, `1` API or file error (message on stderr), `2` usage error
(including a missing API key).

## Errors

All exceptions derive from `papertype.PaperTypeError` and carry `status_code` and
`detail` (the server's message):

| Exception | HTTP status | Meaning |
|---|---|---|
| `AuthError` | 401 | Missing, malformed or revoked API key. |
| `QuotaExceeded` | 429 | Monthly document quota for the plan is used up. |
| `RenderError` | 400, 413, 422 | No `html`/`markdown` given, input over 2 MB, or the document could not be rendered. The message says why. |
| `TransportError` | none | No HTTP response (connection refused, timeout). |
| `PaperTypeError` | anything else | Unexpected status. |

```python
from papertype import Client, QuotaExceeded, RenderError

try:
    pdf = client.render(markdown=text)
except QuotaExceeded as e:
    print("quota used up:", e.detail)
except RenderError as e:
    print("document rejected:", e.detail)
```

## Limits that matter

- **No external fetching.** The renderer never requests URLs. Inline images and
  fonts as `data:` URIs (`<img src="data:image/png;base64,...">`,
  `@font-face { src: url(data:font/woff2;base64,...) }`).
- **No JavaScript.** Rendering is CSS paged media; scripts are not executed.
- Source is limited to 2 MB and output to 300 pages per document.
- Fonts available on the server: DejaVu, Liberation, Noto, Carlito, Caladea.
  Embed anything else with a `data:` URI.
- Free-plan output carries a small footer mark; paid plans do not. `client.me()`
  reports the plan, quota and usage for the key.

## Development

```
pip install -e ".[test]"
python -m pytest
```

Tests use `httpx.MockTransport` and make no network requests.

## License

MIT. See `LICENSE`.
