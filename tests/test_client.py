"""Offline tests for the PaperType SDK using httpx.MockTransport (no network)."""
import json

import httpx
import pytest

import papertype
from papertype import AuthError, Client, PaperTypeError, QuotaExceeded, RenderError, TransportError
from papertype.cli import main as cli_main

PDF = b"%PDF-1.7\n%fake\n"
KEY = "dp_testkey"


def make_client(handler, **kw):
    kw.setdefault("api_key", KEY)
    kw.setdefault("base_url", "https://api.test")
    return Client(transport=httpx.MockTransport(handler), **kw)


def json_error(status, detail):
    return httpx.Response(status, json={"detail": detail})


# -- success -----------------------------------------------------------------

def test_render_success_sends_only_set_fields():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["ua"] = req.headers["user-agent"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf", "x-pages": "1"})

    with make_client(handler) as c:
        out = c.render(markdown="# Hi", theme="report", page_size="Letter", cover=True, title="T")
    assert out == PDF
    assert seen["url"] == "https://api.test/v1/pdf"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["ua"].startswith("papertype-python/")
    assert seen["body"] == {"markdown": "# Hi", "theme": "report", "page_size": "Letter", "cover": True, "title": "T"}
    assert "html" not in seen["body"] and "css" not in seen["body"]


def test_render_template_passthrough():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, content=PDF)

    with make_client(handler) as c:
        c.render(template="invoice", data={"total": 5})
    assert seen["body"] == {"template": "invoice", "data": {"total": 5}}


def test_render_to_file(tmp_path):
    with make_client(lambda req: httpx.Response(200, content=PDF)) as c:
        p = c.render_to_file(tmp_path / "out.pdf", html="<p>x</p>")
    assert p.read_bytes() == PDF


def test_me():
    info = {"email": "a@b.c", "plan": "free", "quota": 50, "used_this_month": 3, "watermark": True}

    def handler(req):
        assert req.method == "GET" and req.url.path == "/v1/me"
        return httpx.Response(200, json=info)

    with make_client(handler) as c:
        assert c.me() == info


def test_api_key_from_env(monkeypatch):
    monkeypatch.setenv("PAPERTYPE_API_KEY", "dp_env")
    c = make_client(lambda req: httpx.Response(200, content=PDF), api_key=None)
    assert c.api_key == "dp_env"
    c.close()


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("PAPERTYPE_API_KEY", raising=False)
    with pytest.raises(AuthError):
        Client()


def test_unknown_option_is_type_error():
    with make_client(lambda req: httpx.Response(200, content=PDF)) as c:
        with pytest.raises(TypeError, match="pagesize"):
            c.render(markdown="x", pagesize="A4")


def test_no_source_raises_locally():
    with make_client(lambda req: pytest.fail("should not hit network")) as c:
        with pytest.raises(RenderError):
            c.render(theme="clean")


# -- error mapping -------------------------------------------------------------

def test_401_auth_error():
    msg = "Missing or invalid API key. Send 'Authorization: Bearer dp_...'."
    with make_client(lambda req: json_error(401, msg)) as c:
        with pytest.raises(AuthError) as ei:
            c.render(markdown="x")
    assert ei.value.status_code == 401
    assert msg in str(ei.value) and "401" in str(ei.value)
    assert isinstance(ei.value, PaperTypeError)


def test_429_quota_exceeded():
    msg = "Monthly quota reached (50 documents on the Free plan). Upgrade at https://papertype.dev/account."
    with make_client(lambda req: json_error(429, msg)) as c:
        with pytest.raises(QuotaExceeded) as ei:
            c.render(markdown="x")
    assert ei.value.status_code == 429 and ei.value.detail == msg
    assert "Monthly quota reached" in str(ei.value)


def test_402_also_quota_exceeded():
    with make_client(lambda req: json_error(402, "Payment required")) as c:
        with pytest.raises(QuotaExceeded):
            c.render(markdown="x")


def test_422_render_error():
    msg = "Rendering failed: bad CSS at line 3"
    with make_client(lambda req: json_error(422, msg)) as c:
        with pytest.raises(RenderError) as ei:
            c.render(html="<p>", css="}{")
    assert ei.value.status_code == 422 and msg in str(ei.value)


def test_400_and_413_render_error():
    with make_client(lambda req: json_error(400, "Provide 'html' or 'markdown'.")) as c:
        with pytest.raises(RenderError):
            c.render(markdown="")  # empty string is sent; the server rejects it
    with make_client(lambda req: json_error(413, "Input too large (max 2 MB).")) as c:
        with pytest.raises(RenderError, match="too large"):
            c.render(markdown="x")


def test_422_validation_list_detail_is_flattened():
    detail = [{"loc": ["body", "cover"], "msg": "Input should be a valid boolean", "type": "bool_parsing"}]
    with make_client(lambda req: json_error(422, detail)) as c:
        with pytest.raises(RenderError) as ei:
            c.render(markdown="x", cover="maybe")
    assert "cover: Input should be a valid boolean" in str(ei.value)
    assert ei.value.detail == detail


def test_other_status_is_base_error_with_text_body():
    with make_client(lambda req: httpx.Response(503, text="upstream down")) as c:
        with pytest.raises(PaperTypeError) as ei:
            c.me()
    assert type(ei.value) is PaperTypeError
    assert ei.value.status_code == 503 and "upstream down" in str(ei.value)


def test_transport_error():
    def handler(req):
        raise httpx.ConnectError("connection refused")

    with make_client(handler) as c:
        with pytest.raises(TransportError, match="connection refused"):
            c.me()


# -- CLI -----------------------------------------------------------------------

def test_cli_render_and_exit_codes(tmp_path, monkeypatch, capsys):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        if req.headers["authorization"] != f"Bearer {KEY}":
            return json_error(401, "bad key")
        return httpx.Response(200, content=PDF)

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real_client(**{**kw, "transport": httpx.MockTransport(handler)}))
    src = tmp_path / "doc.md"; src.write_text("# Title\n\nbody")
    css = tmp_path / "x.css"; css.write_text("p{color:red}")
    out = tmp_path / "doc.pdf"

    monkeypatch.setenv("PAPERTYPE_API_KEY", KEY)
    rc = cli_main(["render", str(src), "-o", str(out), "--theme", "report", "--page-size", "A5", "--css", str(css), "--toc"])
    assert rc == 0 and out.read_bytes() == PDF
    assert seen["body"] == {"markdown": "# Title\n\nbody", "css": "p{color:red}", "theme": "report", "page_size": "A5", "toc": True}

    # --html switches the field
    rc = cli_main(["render", str(src), "--html", "-o", str(out)])
    assert rc == 0 and "html" in seen["body"] and "markdown" not in seen["body"]

    # API error -> 1, message on stderr
    rc = cli_main(["--api-key", "dp_wrong", "render", str(src), "-o", str(out)])
    assert rc == 1 and "bad key" in capsys.readouterr().err

    # no key -> usage error 2
    monkeypatch.delenv("PAPERTYPE_API_KEY")
    rc = cli_main(["render", str(src), "-o", str(out)])
    assert rc == 2

    # missing input file -> 1
    monkeypatch.setenv("PAPERTYPE_API_KEY", KEY)
    rc = cli_main(["render", str(tmp_path / "nope.md"), "-o", str(out)])
    assert rc == 1

    # no command -> 2
    assert cli_main([]) == 2


def test_cli_version(capsys):
    with pytest.raises(SystemExit) as ei:
        cli_main(["--version"])
    assert ei.value.code == 0
    assert papertype.__version__ in capsys.readouterr().out
