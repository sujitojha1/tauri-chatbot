"""
Document parsing via liteparse.

Two consumers:

  * RAG ingestion (global / spec files) wants the *full* document as markdown
    text, which is then chunked and embedded.
  * Session review wants only the **first page** turned into markdown plus a
    rendered page image, fed straight to a vision model (no RAG).

liteparse exposes ``LiteParse(...).parse(path)`` (text/markdown extraction) and
``LiteParse(...).screenshot(path, page_numbers=[...])`` (rasterised pages).
"""
import base64
import logging
from pathlib import Path
from typing import Optional

from liteparse import LiteParse, ParseError

import config

log = logging.getLogger("parsing")

# File extensions liteparse can rasterise into a page screenshot. Raster images
# are already pictures, so we use their bytes directly instead of re-rendering.
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def parse_markdown(path: Path, max_pages: Optional[int] = None) -> str:
    """Extract document text as markdown.

    ``max_pages`` limits how many leading pages are read (used to keep session
    processing to the first page only).
    """
    kwargs = dict(output_format="markdown", quiet=True)
    if max_pages is not None:
        kwargs["max_pages"] = max_pages
        kwargs["target_pages"] = "1" if max_pages == 1 else f"1-{max_pages}"
    result = LiteParse(**kwargs).parse(str(path))
    return result.text or ""


def first_page_image_b64(path: Path) -> Optional[str]:
    """Return a base64-encoded PNG of the document's first page, or ``None``.

    For raster image uploads we return the file bytes unchanged; for everything
    else (PDF, office docs) liteparse renders page 1.
    """
    suffix = path.suffix.lower()
    if suffix in _IMAGE_EXTS:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    try:
        shots = LiteParse(quiet=True).screenshot(str(path), page_numbers=[1])
    except ParseError as e:
        log.warning("screenshot failed for %s: %s", path.name, e)
        return None
    if not shots:
        return None
    return base64.b64encode(shots[0].image_bytes).decode("ascii")


def process_session_file(path: Path) -> tuple[str, Optional[str]]:
    """First-page markdown + first-page image (base64 PNG) for a session file.

    Markdown extraction failures degrade gracefully to an empty string so the
    image alone can still drive the vision model.
    """
    try:
        markdown = parse_markdown(path, max_pages=config.SESSION_MAX_PAGES)
    except ParseError as e:
        log.warning("markdown parse failed for %s: %s", path.name, e)
        markdown = ""
    image_b64 = first_page_image_b64(path)
    return markdown, image_b64
