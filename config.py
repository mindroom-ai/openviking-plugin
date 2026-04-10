"""Configuration for the OpenViking MindRoom plugin."""

from __future__ import annotations

import os

OPENVIKING_URL: str = os.environ.get("OPENVIKING_URL", "http://localhost:1933")

RECALL_MAX_TOKENS: int = int(os.environ.get("OPENVIKING_RECALL_MAX_TOKENS", "2000"))

COMMIT_TOKEN_THRESHOLD: int = int(
    os.environ.get("OPENVIKING_COMMIT_TOKEN_THRESHOLD", "8000"),
)
