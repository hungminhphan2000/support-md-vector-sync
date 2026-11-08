"""OpenAI Files + Vector Stores helpers for article Markdown uploads."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

API_BASE = "https://api.openai.com/v1"
REQUEST_TIMEOUT = 60
POLL_SECONDS = 180
DEFAULT_ARTICLES_DIR = Path("data/articles")

_SECRET_RE = re.compile(r"(sk-[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9_\-\.]+)")
_FILENAME_RE = re.compile(r"^(?P<article_id>\d+)-(?P<digest>[0-9a-f]{16})\.md$")


class VectorStoreError(Exception):
    """Raised when a vector-store request fails or returns an invalid payload."""


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    filename: str
    article_id: int
    digest: str
    status: str


@dataclass(frozen=True)
class LocalArticle:
    article_id: int
    path: Path
    content: bytes
    digest: str

    @property
    def filename(self) -> str:
        return store_filename(self.article_id, self.digest)


@dataclass(frozen=True)
class UploadPlan:
    to_upload: tuple[LocalArticle, ...]
    to_poll: tuple[tuple[LocalArticle, str], ...]
    skipped: tuple[LocalArticle, ...]


class DeltaKind(str, Enum):
    NEW = "new"
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    IN_PROGRESS = "in_progress"
    FAILED = "failed"


@dataclass(frozen=True)
class DeltaDecision:
    """Pure classification of one local article against stored vector-store files."""

    article: LocalArticle
    kind: DeltaKind
    current_file_id: str | None = None
    old_file_ids: tuple[str, ...] = ()


def redact(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text)


def load_dotenv(path: Path = Path(".env")) -> None:
    """Load KEY=VALUE lines into os.environ when the key is not already set."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and key not in os.environ:
            os.environ[key] = value


def api_key() -> str:
    key = os.environ.get("API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key or not key.strip():
        raise VectorStoreError(
            "API_KEY is not set. Export API_KEY or OPENAI_API_KEY, or put it in .env."
        )
    return key.strip()


def require_vector_store_id() -> str:
    store_id = (os.environ.get("VECTOR_STORE_ID") or "").strip()
    if not store_id.startswith("vs_"):
        raise VectorStoreError(
            "VECTOR_STORE_ID is required and must start with 'vs_'."
        )
    return store_id


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


def store_filename(article_id: int, digest: str) -> str:
    return f"{article_id}-{digest}.md"


def parse_store_filename(filename: str) -> tuple[int, str] | None:
    match = _FILENAME_RE.match(filename)
    if not match:
        return None
    return int(match.group("article_id")), match.group("digest")


def request_json(
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
        raise VectorStoreError(
            f"HTTP {exc.code} {method} {path}: {redact(detail[:500])}"
        ) from exc
    except urllib.error.URLError as exc:
        raise VectorStoreError(f"Request failed {method} {path}: {exc.reason}") from exc
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise VectorStoreError(f"Response from {method} {path} was not JSON.") from exc


def multipart_file(filename: str, content: bytes) -> tuple[bytes, str]:
    boundary = "----optibotupload"
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


def load_local_articles(articles_dir: Path = DEFAULT_ARTICLES_DIR) -> list[LocalArticle]:
    if not articles_dir.is_dir():
        raise VectorStoreError(f"Missing articles directory: {articles_dir}")
    articles: list[LocalArticle] = []
    for path in sorted(articles_dir.glob("*.md")):
        try:
            article_id = int(path.stem)
        except ValueError as exc:
            raise VectorStoreError(
                f"Article filename must be <id>.md; got {path.name!r}."
            ) from exc
        content = path.read_bytes()
        articles.append(
            LocalArticle(
                article_id=article_id,
                path=path,
                content=content,
                digest=content_digest(content),
            )
        )
    return articles


def _files_for_article(
    stored: list[StoredFile],
    article_id: int,
) -> list[StoredFile]:
    return [item for item in stored if item.article_id == article_id]


def decide_delta(article: LocalArticle, stored: list[StoredFile]) -> DeltaDecision:
    """
    Classify one local article against stored files for the same article id.

    - new: no stored files for this id
    - unchanged: completed file with the current digest
    - in_progress: in_progress file with the current digest (poll; do not re-upload)
    - failed: failed/cancelled file with the current digest (retry upload)
    - changed: other digests exist for this id, but not a usable current-digest file
    """
    related = _files_for_article(stored, article.article_id)
    old_file_ids = tuple(
        item.file_id
        for item in related
        if item.digest != article.digest and item.status == "completed"
    )
    current = [item for item in related if item.digest == article.digest]

    completed = next((item for item in current if item.status == "completed"), None)
    if completed is not None:
        return DeltaDecision(
            article=article,
            kind=DeltaKind.UNCHANGED,
            current_file_id=completed.file_id,
            old_file_ids=old_file_ids,
        )

    in_progress = next((item for item in current if item.status == "in_progress"), None)
    if in_progress is not None:
        return DeltaDecision(
            article=article,
            kind=DeltaKind.IN_PROGRESS,
            current_file_id=in_progress.file_id,
            old_file_ids=old_file_ids,
        )

    failed = next(
        (item for item in current if item.status in {"failed", "cancelled"}),
        None,
    )
    if failed is not None:
        return DeltaDecision(
            article=article,
            kind=DeltaKind.FAILED,
            current_file_id=failed.file_id,
            old_file_ids=old_file_ids,
        )

    if related:
        return DeltaDecision(
            article=article,
            kind=DeltaKind.CHANGED,
            old_file_ids=old_file_ids,
        )

    return DeltaDecision(article=article, kind=DeltaKind.NEW)


def decide_deltas(
    locals_: list[LocalArticle],
    stored: list[StoredFile],
) -> list[DeltaDecision]:
    """Classify every local article. Pure: no network I/O."""
    return [decide_delta(article, stored) for article in locals_]


def plan_uploads(
    locals_: list[LocalArticle],
    stored: list[StoredFile],
) -> UploadPlan:
    """
    Map delta decisions onto upload / poll / skip actions.

    - unchanged → skip
    - in_progress → poll existing file id
    - new / changed / failed → upload (failed is a retry)
    """
    to_upload: list[LocalArticle] = []
    to_poll: list[tuple[LocalArticle, str]] = []
    skipped: list[LocalArticle] = []

    for decision in decide_deltas(locals_, stored):
        if decision.kind is DeltaKind.UNCHANGED:
            skipped.append(decision.article)
        elif decision.kind is DeltaKind.IN_PROGRESS:
            if decision.current_file_id is None:
                raise VectorStoreError(
                    f"in_progress decision for article {decision.article.article_id} "
                    "is missing a file id."
                )
            to_poll.append((decision.article, decision.current_file_id))
        else:
            to_upload.append(decision.article)

    return UploadPlan(
        to_upload=tuple(to_upload),
        to_poll=tuple(to_poll),
        skipped=tuple(skipped),
    )


def list_stored_files(
    key: str,
    store_id: str,
    *,
    request: Callable[..., Any] = request_json,
) -> list[StoredFile]:
    stored: list[StoredFile] = []
    after: str | None = None
    while True:
        path = f"/vector_stores/{store_id}/files?limit=100"
        if after:
            path += f"&after={after}"
        payload = request("GET", path, key)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise VectorStoreError(
                f"Invalid vector store file list from {path!r}."
            )
        batch = payload["data"]
        if not batch:
            break
        for item in batch:
            if not isinstance(item, dict):
                raise VectorStoreError("Vector store file list contained a non-object.")
            file_id = str(item.get("id", ""))
            status = str(item.get("status", ""))
            if not file_id:
                raise VectorStoreError("Vector store file was missing an id.")
            file_obj = request("GET", f"/files/{file_id}", key)
            if not isinstance(file_obj, dict):
                raise VectorStoreError(f"File {file_id} response was not an object.")
            filename = str(file_obj.get("filename", ""))
            parsed = parse_store_filename(filename)
            if parsed is None:
                continue
            article_id, digest = parsed
            stored.append(
                StoredFile(
                    file_id=file_id,
                    filename=filename,
                    article_id=article_id,
                    digest=digest,
                    status=status,
                )
            )
        if not payload.get("has_more"):
            break
        after = str(batch[-1].get("id", "")) or None
        if not after:
            break
    return stored


def upload_and_attach(
    key: str,
    store_id: str,
    article: LocalArticle,
    *,
    request: Callable[..., Any] = request_json,
) -> str:
    body, content_type = multipart_file(article.filename, article.content)
    uploaded = request(
        "POST",
        "/files",
        key,
        body=body,
        content_type=content_type,
    )
    if not isinstance(uploaded, dict) or not uploaded.get("id"):
        raise VectorStoreError(f"Upload failed for {article.filename}.")
    file_id = str(uploaded["id"])
    request(
        "POST",
        f"/vector_stores/{store_id}/files",
        key,
        payload={
            "file_id": file_id,
            "attributes": {
                "article_id": str(article.article_id),
                "content_hash": article.digest,
            },
        },
    )
    return file_id


def poll_file(
    key: str,
    store_id: str,
    file_id: str,
    *,
    timeout: float = POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    request: Callable[..., Any] = request_json,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        retrieved = request(
            "GET",
            f"/vector_stores/{store_id}/files/{file_id}",
            key,
        )
        if not isinstance(retrieved, dict):
            raise VectorStoreError(
                f"Vector store file {file_id} response was not an object."
            )
        status = retrieved.get("status")
        if status in {"completed", "failed", "cancelled"}:
            return retrieved
        if time.monotonic() >= deadline:
            return retrieved
        sleep(2)


def delete_store_file(
    key: str,
    store_id: str,
    file_id: str,
    *,
    request: Callable[..., Any] = request_json,
) -> None:
    """Remove a file from the vector store. Does not delete the underlying Files object."""
    request("DELETE", f"/vector_stores/{store_id}/files/{file_id}", key)


def get_store(key: str, store_id: str, *, request: Callable[..., Any] = request_json) -> dict[str, Any]:
    store = request("GET", f"/vector_stores/{store_id}", key)
    if not isinstance(store, dict):
        raise VectorStoreError("Vector store response was not an object.")
    return store
