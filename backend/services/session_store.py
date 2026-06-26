"""
On-disk store for the artifacts derived from a *session* file.

Session documents are not embedded into Qdrant. Instead we keep the first-page
markdown and a base64 page image around so the query layer can hand them
straight to a vision model. Keyed by file_id under ``config.ASSET_DIR``.
"""
from __future__ import annotations

from config import ASSET_DIR


def _md_path(file_id: str):
    return ASSET_DIR / f"{file_id}.md"


def _img_path(file_id: str):
    return ASSET_DIR / f"{file_id}.b64"


def save(file_id: str, markdown: str, image_b64: str | None) -> None:
    _md_path(file_id).write_text(markdown or "", encoding="utf-8")
    if image_b64:
        _img_path(file_id).write_text(image_b64, encoding="ascii")


def load(file_id: str) -> tuple[str, str | None]:
    """Return (markdown, image_b64). Missing artifacts come back empty/None."""
    md_path, img_path = _md_path(file_id), _img_path(file_id)
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    image_b64 = img_path.read_text(encoding="ascii") if img_path.exists() else None
    return markdown, image_b64


def delete(file_id: str) -> None:
    _md_path(file_id).unlink(missing_ok=True)
    _img_path(file_id).unlink(missing_ok=True)
