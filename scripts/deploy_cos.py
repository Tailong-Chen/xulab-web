#!/usr/bin/env python3
"""Synchronize the static XuLab site to Tencent Cloud COS and purge CDN.

Use a Hong Kong or Singapore COS bucket when the domain cannot use mainland
China acceleration without an ICP filing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Iterator


ROOT_FILES = {"index.html", "robots.txt"}
EXCLUDED_DIRECTORIES = {
    ".agents",
    ".codex",
    ".git",
    ".github",
    "docs",
    "scripts",
}
HTML_CACHE_CONTROL = "public, max-age=0, s-maxage=300, must-revalidate"
ASSET_CACHE_CONTROL = "public, max-age=604800, stale-while-revalidate=86400"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--site-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Static site root (defaults to the repository root).",
    )
    parser.add_argument(
        "--prefix",
        default=os.environ.get("TENCENT_COS_PREFIX", ""),
        help="Optional COS key prefix.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete COS objects under the prefix that are absent locally.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned operations without changing COS or CDN state.",
    )
    parser.add_argument(
        "--skip-cdn-purge",
        action="store_true",
        help="Do not purge TENCENT_CDN_DOMAIN after a changed deployment.",
    )
    return parser.parse_args()


def required_environment(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def normalize_prefix(raw_prefix: str) -> str:
    prefix = raw_prefix.strip().strip("/")
    if not prefix:
        return ""
    if any(part in {"", ".", ".."} for part in PurePosixPath(prefix).parts):
        raise SystemExit(f"Unsafe COS prefix: {raw_prefix!r}")
    return f"{prefix}/"


def iter_site_files(site_root: Path) -> Iterator[tuple[Path, str]]:
    for root_file in sorted(ROOT_FILES):
        path = site_root / root_file
        if not path.is_file():
            raise SystemExit(f"Required site file is missing: {path}")
        yield path, root_file

    for child in sorted(site_root.iterdir()):
        if not child.is_dir() or child.name in EXCLUDED_DIRECTORIES or child.name.startswith("."):
            continue
        for path in sorted(child.rglob("*")):
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(site_root).parts):
                yield path, path.relative_to(site_root).as_posix()


def md5_hex(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_type(path: Path) -> str:
    overrides = {
        ".eot": "application/vnd.ms-fontobject",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
    }
    if path.suffix.lower() in overrides:
        return overrides[path.suffix.lower()]
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed in {"text/css", "text/html", "text/plain"}:
        return f"{guessed}; charset=utf-8"
    return guessed or "application/octet-stream"


def cache_control(path: Path) -> str:
    if path.suffix.lower() == ".html" or path.name == "robots.txt":
        return HTML_CACHE_CONTROL
    return ASSET_CACHE_CONTROL


def list_remote_objects(client, bucket: str, prefix: str) -> dict[str, str]:
    objects: dict[str, str] = {}
    marker = ""
    while True:
        response = client.list_objects(Bucket=bucket, Prefix=prefix, Marker=marker, MaxKeys=1000)
        for item in response.get("Contents", []):
            objects[item["Key"]] = item.get("ETag", "").strip('"')
        is_truncated = response.get("IsTruncated", False)
        if is_truncated in {False, None, 0, "0", "false", "False"}:
            break
        if is_truncated not in {True, 1, "1", "true", "True"}:
            raise RuntimeError(f"COS returned an invalid IsTruncated value: {is_truncated!r}")
        marker = response.get("NextMarker", "")
        if not marker:
            raise RuntimeError("COS returned a truncated listing without NextMarker")
    return objects


def purge_cdn(secret_id: str, secret_key: str, domain: str, dry_run: bool) -> None:
    domain = domain.strip().rstrip("/")
    if not domain:
        return
    if "://" not in domain:
        domain = f"https://{domain}"
    # Purge the complete static site because the exported pages share versioned
    # asset paths but do not use content-hashed filenames.
    purge_path = f"{domain}/"
    if dry_run:
        print(f"PURGE {purge_path}")
        return

    try:
        from tencentcloud.cdn.v20180606 import cdn_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
    except ImportError as error:
        raise SystemExit(
            "CDN purge requires tencentcloud-sdk-python. "
            "Install it or pass --skip-cdn-purge."
        ) from error

    credentials = credential.Credential(secret_id, secret_key)
    http_profile = HttpProfile()
    http_profile.endpoint = "cdn.tencentcloudapi.com"
    profile = ClientProfile(httpProfile=http_profile)
    client = cdn_client.CdnClient(credentials, "", profile)
    request = models.PurgePathCacheRequest()
    request.from_json_string(json.dumps({"Paths": [purge_path], "FlushType": "flush"}))
    response = client.PurgePathCache(request)
    print(f"PURGED {purge_path} request={response.RequestId}")


def main() -> int:
    args = parse_args()
    site_root = args.site_root.resolve()
    if not site_root.is_dir():
        raise SystemExit(f"Site root does not exist: {site_root}")

    secret_id = required_environment("TENCENTCLOUD_SECRET_ID")
    secret_key = required_environment("TENCENTCLOUD_SECRET_KEY")
    bucket = required_environment("TENCENT_COS_BUCKET")
    region = required_environment("TENCENT_COS_REGION")
    prefix = normalize_prefix(args.prefix)
    cdn_domain = os.environ.get("TENCENT_CDN_DOMAIN", "").strip()

    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as error:
        raise SystemExit(
            "COS deployment requires cos-python-sdk-v5: "
            "python -m pip install cos-python-sdk-v5"
        ) from error

    client = CosS3Client(
        CosConfig(
            Region=region,
            SecretId=secret_id,
            SecretKey=secret_key,
            Scheme="https",
        )
    )
    local_files = list(iter_site_files(site_root))
    local_keys = {f"{prefix}{relative}" for _, relative in local_files}
    remote_objects = list_remote_objects(client, bucket, prefix)

    uploads: list[tuple[Path, str]] = []
    for path, relative in local_files:
        key = f"{prefix}{relative}"
        if remote_objects.get(key) != md5_hex(path):
            uploads.append((path, key))

    stale_keys = sorted(set(remote_objects) - local_keys) if args.delete else []
    print(
        f"PLAN bucket={bucket} region={region} prefix={prefix or '/'} "
        f"files={len(local_files)} upload={len(uploads)} delete={len(stale_keys)}"
    )

    for path, key in uploads:
        print(f"UPLOAD {key} ({path.stat().st_size} bytes)")
        if args.dry_run:
            continue
        with path.open("rb") as body:
            client.put_object(
                Bucket=bucket,
                Key=key,
                Body=body,
                ContentType=content_type(path),
                CacheControl=cache_control(path),
            )

    for key in stale_keys:
        print(f"DELETE {key}")
        if not args.dry_run:
            client.delete_object(Bucket=bucket, Key=key)

    changed = bool(uploads or stale_keys)
    if changed and cdn_domain and not args.skip_cdn_purge:
        purge_cdn(secret_id, secret_key, cdn_domain, args.dry_run)
    elif changed and not cdn_domain and not args.skip_cdn_purge:
        print("SKIP CDN purge: TENCENT_CDN_DOMAIN is not configured")
    else:
        print("CDN purge not required")
    return 0


if __name__ == "__main__":
    sys.exit(main())
