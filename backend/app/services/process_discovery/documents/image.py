"""Images (PNG, JPEG): header checks before decoding, then a clean re-encode for the model (spec 17 §3.19 items 2-3).

Why: a screenshot of a planning tool or a photo of a printed form can tell the interview a lot,
but an image is the riskiest upload: a small file can claim billions of pixels (a decompression
bomb), and a photo carries location and device data in its metadata. So the pixel count is read
from the header before anything is decoded, and only a re-encoded copy (EXIF orientation applied,
RGB, scaled down, every metadata block dropped) ever reaches the model.
What: `check_image` (size of the picture from the header, the pixel limit, opens and loads) and
`prepare_image` (the re-encoded bytes the model sees, with the size as uploaded). Limits come
from `DocumentsConfig` (`max_image_pixels`, `image_send_side`).
Must not: store, log or return the uploaded bytes; scale an image up; keep any metadata; read the
clock or reach the network. AC-17.54, AC-17.55.
"""

from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import DocumentsConfig

from .intake import DocumentRejected

JPEG_QUALITY = 85
OPEN_FAILED = "I couldn't open this image."


@dataclass(frozen=True)
class PreparedImage:
    """The bytes sent to the model (re-encoded, no metadata) and the picture's size as uploaded."""

    kind: Literal["png", "jpeg"]
    data: bytes
    width: int
    height: int


def _too_many_pixels(config: DocumentsConfig) -> DocumentRejected:
    megapixels = config.max_image_pixels / 1_000_000
    return DocumentRejected("document_too_large", f"This image is too large: at most {megapixels:g} megapixels.")


def check_image(data: bytes, config: DocumentsConfig) -> tuple[int, int]:
    """`(width, height)` from the header; the pixel limit before any decode; then a full load must succeed."""
    Image.MAX_IMAGE_PIXELS = config.max_image_pixels
    try:
        with warnings.catch_warnings():  # the limit is checked here, so Pillow's own warning adds nothing
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
        with image:
            width, height = image.size
            if width * height > config.max_image_pixels:
                raise _too_many_pixels(config)
            image.load()
    except DocumentRejected:
        raise
    except Image.DecompressionBombError:
        raise _too_many_pixels(config) from None
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        raise DocumentRejected("document_unreadable", OPEN_FAILED) from None
    return width, height


def prepare_image(data: bytes, kind: str, config: DocumentsConfig) -> PreparedImage:
    """Decode, apply the EXIF orientation, RGB, scale down to `image_send_side`, re-encode without metadata."""
    width, height = check_image(data, config)
    with Image.open(io.BytesIO(data)) as source:
        source.seek(0)  # an animated PNG: the first frame only
        image = ImageOps.exif_transpose(source.copy()).convert("RGB")
    image.thumbnail((config.image_send_side, config.image_send_side))  # never scales up
    out = io.BytesIO()
    if kind == "png":
        image.save(out, "PNG")
        return PreparedImage("png", out.getvalue(), width, height)
    image.save(out, "JPEG", quality=JPEG_QUALITY)
    return PreparedImage("jpeg", out.getvalue(), width, height)
