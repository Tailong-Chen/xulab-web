#!/usr/bin/env python3
"""Run deployment-focused checks against the exported static site."""

from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = {".git", ".github", ".agents", ".codex", "docs", "scripts"}


class ResourceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.resources: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"iframe", "img", "link", "script"}:
            self.resources.append((tag, {key: value or "" for key, value in attrs}))


def html_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.html")
        if not any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(ROOT).parts)
    )


def local_resource_path(page: Path, value: str) -> Path | None:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    decoded = unquote(parsed.path)
    # WordPress export metadata points to endpoints that are intentionally not
    # part of this static deployment.
    if decoded in {
        "/xmlrpc.php",
        "/wp-comments-post.php",
        "/wp-json/",
        "/feed/",
        "/comments/feed/",
        "/wp-sitemap.xml",
    } or decoded.startswith("/wp-json/"):
        return None
    if decoded.startswith("/"):
        return ROOT / decoded.lstrip("/")
    return page.parent / decoded


def main() -> int:
    errors: list[str] = []
    pages = html_files()
    if not pages:
        errors.append("No HTML pages found")

    parsed_pages: dict[Path, ResourceParser] = {}
    for page in pages:
        source = page.read_text(encoding="utf-8")
        relative = page.relative_to(ROOT)
        if "fonts.googleapis.com" in source or "fonts.gstatic.com" in source:
            errors.append(f"{relative}: external Google Fonts dependency remains")

        parser = ResourceParser()
        parser.feed(source)
        parsed_pages[page] = parser
        for tag, attrs in parser.resources:
            attribute = "href" if tag == "link" else "src"
            value = attrs.get(attribute, "")
            target = local_resource_path(page, value)
            if target is not None and value and not target.is_file():
                errors.append(f"{relative}: missing local resource {value}")

    members = ROOT / "lab-members/index.html"
    member_images = [
        (tag, attrs)
        for tag, attrs in parsed_pages[members].resources
        if tag == "img"
    ]
    for index, (_, attrs) in enumerate(member_images):
        if index == 0 and attrs.get("fetchpriority") == "high":
            continue
        if attrs.get("loading") != "lazy":
            errors.append(f"lab-members/index.html: image is not lazy-loaded: {attrs.get('src', '')}")

    videos = ROOT / "video/index.html"
    for tag, attrs in parsed_pages[videos].resources:
        if tag == "iframe" and attrs.get("loading") != "lazy":
            errors.append(f"video/index.html: iframe is not lazy-loaded: {attrs.get('src', '')}")

    if errors:
        print("Site checks failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    member_images = sum(tag == "img" for tag, _ in parsed_pages[members].resources)
    video_frames = sum(tag == "iframe" for tag, _ in parsed_pages[videos].resources)
    print(
        f"Site checks passed: pages={len(pages)} "
        f"lazy_member_images={member_images} lazy_video_iframes={video_frames}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
