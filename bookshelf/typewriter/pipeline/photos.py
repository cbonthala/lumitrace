"""Resized JPEG copies of uploaded photos (originals stay in the owner's photo library).

HEIC/HEIF (the iPhone default) is read through pillow-heif. The copy is rotated upright from the
EXIF orientation, fitted inside ``BOOKSHELF_PHOTO_MAX_DIMENSION`` and saved as JPEG at
``BOOKSHELF_PHOTO_JPEG_QUALITY`` without EXIF metadata (no GPS or device details in the copy).
"""

from __future__ import annotations

import io
import logging

from PIL import Image, ImageOps

log = logging.getLogger(__name__)

_heif_registered = False


def _register_heif() -> None:
    global _heif_registered
    if _heif_registered:
        return
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:  # pragma: no cover - pillow-heif is a dependency
        log.warning("pillow-heif is not installed; HEIC photos cannot be read")
    _heif_registered = True


def resize_photo(data: bytes, max_dimension: int, quality: int) -> bytes:
    """JPEG bytes no larger than ``max_dimension`` on the longest side.

    Raises ``PIL.UnidentifiedImageError`` (a ``OSError``) for data that is not an image.
    """
    _register_heif()
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        upright = ImageOps.exif_transpose(img) or img
        if upright.mode not in ("RGB", "L"):
            background = Image.new("RGB", upright.size, (255, 255, 255))
            rgba = upright.convert("RGBA")
            background.paste(rgba, mask=rgba.getchannel("A"))
            upright = background
        upright.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        upright.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
        return out.getvalue()
