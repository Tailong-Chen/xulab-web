#!/usr/bin/env python3
"""Unit tests for the COS deployment helper."""

from __future__ import annotations

import unittest

from deploy_cos import list_remote_objects


class FakeCosClient:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = iter(responses)
        self.markers: list[str] = []

    def list_objects(self, **kwargs: object) -> dict[str, object]:
        self.markers.append(str(kwargs["Marker"]))
        return next(self.responses)


class ListRemoteObjectsTests(unittest.TestCase):
    def test_empty_bucket_accepts_cos_string_false(self) -> None:
        client = FakeCosClient([{"IsTruncated": "false"}])

        self.assertEqual(list_remote_objects(client, "bucket", ""), {})
        self.assertEqual(client.markers, [""])

    def test_paginated_listing_uses_next_marker(self) -> None:
        client = FakeCosClient(
            [
                {
                    "Contents": [{"Key": "index.html", "ETag": '"abc"'}],
                    "IsTruncated": "true",
                    "NextMarker": "index.html",
                },
                {
                    "Contents": [{"Key": "style.css", "ETag": '"def"'}],
                    "IsTruncated": "false",
                },
            ]
        )

        self.assertEqual(
            list_remote_objects(client, "bucket", ""),
            {"index.html": "abc", "style.css": "def"},
        )
        self.assertEqual(client.markers, ["", "index.html"])


if __name__ == "__main__":
    unittest.main()
