#!/usr/bin/env python3
"""Upload one Help Center article to an OpenAI vector store and report indexing.

Uses the current Files and Vector Stores endpoints. Does not call the retired
Assistants API. Reads API_KEY or OPENAI_API_KEY from the environment and never
prints the key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API_BASE = "https://api.openai.com/v1"
ARTICLE_ID = 360051014713
ARTICLE_PATH = Path("data/articles") / f"{ARTICLE_ID}.md"
POLL_SECONDS = 180
REQUEST_TIMEOUT = 60

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9_\-\.]+)")
_COUNT_KEY_RE = re.compile(r"count|usage|chunk|byte|token", re.IGNORECASE)


def _api_key() -> str:
    key = os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key or not key.strip():
        raise SystemExit(
            "API_KEY is not set. Export API_KEY or OPENAI_API_KEY. No request was sent."
        )
    return key.strip()


def _redact(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text)


def _request(
    method: str,
    path: str,
    key: str,
    *,
    payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
) -> Any:
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    data = body
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif content_type is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(
        API_BASE + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise SystemExit(
            f"HTTP {exc.code} {method} {path}: {_redact(detail[:500])}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Request failed {method} {path}: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Response from {method} {path} was not JSON.") from exc


def _multipart(filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----optibotfeasibility"
    parts = [
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="purpose"\r\n\r\n',
        b"user_data\r\n",
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        ).encode(),
        b"Content-Type: text/markdown\r\n\r\n",
        content,
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _count_fields(value: Any, prefix: str = "") -> list[str]:
    """Numeric count and size fields. Skips ``chunking_strategy`` settings."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key == "chunking_strategy":
                continue
            if isinstance(item, dict) and _COUNT_KEY_RE.search(str(key)):
                found.extend(_numeric_leaves(item, path))
                continue
            if _COUNT_KEY_RE.search(str(key)) and _is_number(item):
                found.append(f"{path}={item}")
            found.extend(_count_fields(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_count_fields(item, f"{prefix}[{index}]"))
    return found


def _strategy_settings(value: Any) -> list[str]:
    """Numeric ``chunking_strategy`` settings. These configure chunking; they are not counts."""
    if not isinstance(value, dict):
        return []
    strategy = value.get("chunking_strategy")
    if not isinstance(strategy, dict):
        return []
    return _numeric_leaves(strategy, "chunking_strategy")


def _numeric_leaves(value: Any, prefix: str) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}"
            if _is_number(item):
                found.append(f"{path}={item}")
            else:
                found.extend(_numeric_leaves(item, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_numeric_leaves(item, f"{prefix}[{index}]"))
    return found


def indexed_chunk_count_lines(count_field_lines: list[str]) -> list[str]:
    """Lines that name an indexed chunk count. Strategy settings are not included."""
    return [line for line in count_field_lines if re.search(r"chunk", line, re.IGNORECASE)]


def _keys(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(str(key) for key in value)


def main() -> int:
    key = _api_key()
    if not ARTICLE_PATH.is_file():
        raise SystemExit(f"Missing {ARTICLE_PATH}. Run export_articles.py first.")

    content = ARTICLE_PATH.read_bytes()
    digest = hashlib.sha256(content).hexdigest()[:16]
    filename = f"{ARTICLE_ID}-{digest}.md"

    store_id = (os.environ.get("VECTOR_STORE_ID") or "").strip()
    created_store = False
    if not store_id:
        store = _request(
            "POST",
            "/vector_stores",
            key,
            payload={"name": f"feasibility-{ARTICLE_ID}"},
        )
        store_id = str(store.get("id", ""))
        created_store = True
        if not store_id.startswith("vs_"):
            raise SystemExit("Vector store response did not include an id.")

    body, content_type = _multipart(filename, content)
    uploaded = _request(
        "POST",
        "/files",
        key,
        body=body,
        content_type=content_type,
    )
    file_id = str(uploaded.get("id", ""))
    if not file_id:
        raise SystemExit("File upload response did not include an id.")

    _request(
        "POST",
        f"/vector_stores/{store_id}/files",
        key,
        payload={"file_id": file_id},
    )

    deadline = time.monotonic() + POLL_SECONDS
    vector_file: dict[str, Any] = {}
    while True:
        retrieved = _request(
            "GET",
            f"/vector_stores/{store_id}/files/{file_id}",
            key,
        )
        if not isinstance(retrieved, dict):
            raise SystemExit("Vector store file response was not an object.")
        vector_file = retrieved
        status = vector_file.get("status")
        if status in {"completed", "failed", "cancelled"}:
            break
        if time.monotonic() >= deadline:
            break
        time.sleep(2)

    store = _request("GET", f"/vector_stores/{store_id}", key)
    file_counts = _count_fields(vector_file)
    store_counts = _count_fields(store)
    last_error = vector_file.get("last_error")
    error_code = last_error.get("code") if isinstance(last_error, dict) else None

    print(f"article_id={ARTICLE_ID}")
    print(f"upload_filename={filename}")
    print(f"vector_store_id={store_id}")
    print(f"vector_store_created={created_store}")
    print(f"file_id={file_id}")
    print(f"vector_store_file_status={vector_file.get('status')}")
    print(f"vector_store_status={store.get('status') if isinstance(store, dict) else None}")
    print(f"last_error_code={error_code}")
    print(f"vector_store_file_keys={','.join(_keys(vector_file))}")
    print(f"vector_store_keys={','.join(_keys(store))}")
    print("count_fields:")
    for line in file_counts:
        print(f"  vector_store_file.{line}")
    for line in store_counts:
        print(f"  vector_store.{line}")
    print("chunking_strategy_settings:")
    for line in _strategy_settings(vector_file):
        print(f"  {line}")
    chunk_counts = indexed_chunk_count_lines(file_counts + store_counts)
    if chunk_counts:
        print("indexed_chunk_count_field=" + ",".join(chunk_counts))
    else:
        print("indexed_chunk_count_field=absent")
    return 0 if vector_file.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
