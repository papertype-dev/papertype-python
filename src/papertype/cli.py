"""``papertype`` command-line tool.

Exit codes: 0 success, 1 API or I/O error (message on stderr), 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .client import DEFAULT_BASE_URL, ENV_API_KEY, ENV_BASE_URL, Client
from .errors import AuthError, PaperTypeError

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="papertype",
        description="Render Markdown or HTML to PDF with the PaperType API (https://papertype.dev).",
    )
    p.add_argument("--version", action="version", version=f"papertype {__version__}")
    p.add_argument("--api-key", metavar="KEY", help=f"API key (default: ${ENV_API_KEY})")
    p.add_argument("--base-url", metavar="URL", help=f"API base URL (default: ${ENV_BASE_URL} or {DEFAULT_BASE_URL})")
    p.add_argument("--timeout", type=float, default=60.0, metavar="SECONDS", help="request timeout (default 60)")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    r = sub.add_parser("render", help="render a Markdown (or HTML) file to PDF")
    r.add_argument("input", metavar="INPUT", help="input file (.md by default), or '-' for stdin")
    r.add_argument("-o", "--output", metavar="OUTPUT",
                   help="output PDF path, or '-' for stdout (default: INPUT with .pdf extension)")
    r.add_argument("--html", action="store_true", help="treat INPUT as HTML instead of Markdown")
    r.add_argument("--theme", metavar="T", help="clean (default), report, minimal, letter, or none")
    r.add_argument("--page-size", metavar="S", help="A4 (default), Letter, Legal, A5")
    r.add_argument("--css", metavar="FILE", help="extra CSS file appended after the theme")
    r.add_argument("--title", help="document title (cover page and PDF metadata)")
    r.add_argument("--cover", action="store_true", help="add a cover page")
    r.add_argument("--toc", action="store_true", help="add a table of contents (Markdown only)")

    sub.add_parser("me", help="show plan, quota and usage for the key")
    return p


def _usage_error(msg: str) -> int:
    print(f"papertype: error: {msg}", file=sys.stderr)
    return EXIT_USAGE


def _read_input(spec: str) -> str:
    if spec == "-":
        return sys.stdin.read()
    return Path(spec).read_text(encoding="utf-8")


def _cmd_render(args: argparse.Namespace, client: Client) -> int:
    if args.input == "-" and not args.output:
        return _usage_error("-o OUTPUT is required when reading from stdin")
    output = args.output or str(Path(args.input).with_suffix(".pdf"))
    try:
        source = _read_input(args.input)
        css = Path(args.css).read_text(encoding="utf-8") if args.css else None
    except OSError as e:
        print(f"papertype: error: {e}", file=sys.stderr)
        return EXIT_ERROR

    kwargs = {
        "html" if args.html else "markdown": source,
        "css": css,
        "theme": args.theme,
        "page_size": args.page_size,
    }
    if args.title:
        kwargs["title"] = args.title
    if args.cover:
        kwargs["cover"] = True
    if args.toc:
        kwargs["toc"] = True

    pdf = client.render(**kwargs)
    if output == "-":
        sys.stdout.buffer.write(pdf)
        sys.stdout.buffer.flush()
    else:
        Path(output).write_bytes(pdf)
        print(f"wrote {output} ({len(pdf)} bytes)", file=sys.stderr)
    return EXIT_OK


def _cmd_me(args: argparse.Namespace, client: Client) -> int:
    info = client.me()
    print(json.dumps(info, indent=2))
    return EXIT_OK


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        client = Client(api_key=args.api_key, base_url=args.base_url, timeout=args.timeout)
    except AuthError as e:  # no key at all: a usage problem, not an API error
        return _usage_error(str(e))
    try:
        with client:
            if args.command == "render":
                return _cmd_render(args, client)
            if args.command == "me":
                return _cmd_me(args, client)
            return _usage_error(f"unknown command {args.command}")
    except PaperTypeError as e:
        print(f"papertype: error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as e:
        print(f"papertype: error: {e}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
