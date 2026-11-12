#!/usr/bin/env python3
"""Preview the complete static site locally, keeping site navigation local."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


class PreviewHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_head(self):
        path = Path(self.translate_path(self.path))
        if path.is_dir():
            if not urlsplit(self.path).path.endswith("/"):
                return super().send_head()
            path = path / "index.html"

        if path.suffix.lower() != ".html" or not path.is_file():
            return super().send_head()

        source = path.read_text(encoding="utf-8")
        # Rewrite responses only; production HTML retains its public domain.
        for origin in (
            "https://www.xulab.cc",
            "http://www.xulab.cc",
            "https://xulab.cc",
            "http://xulab.cc",
        ):
            source = source.replace(origin + "/", "/")
        body = source.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return BytesIO(body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    handler = partial(PreviewHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
        print(f"Full site preview: http://127.0.0.1:{args.port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
