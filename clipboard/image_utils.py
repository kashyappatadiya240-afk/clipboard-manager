import hashlib
import io
import logging
from typing import Optional, Tuple, Union

from PIL import Image

logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB safety limit
MAX_IMAGE_WIDTH = 8192              # Max supported pixel width (8K)
MAX_IMAGE_HEIGHT = 8192             # Max supported pixel height (8K)


def compute_image_pixel_hash(image_input: Union[bytes, Image.Image]) -> Optional[str]:
    """Computes a deterministic SHA-256 hash based on uncompressed RGBA pixel data and dimensions.

    This ensures identical images produce the exact same hash regardless of PNG compression
    levels, chunk order, or encoding source (e.g. GDK texture vs GNOME screenshot on disk).
    """
    try:
        if isinstance(image_input, bytes):
            with Image.open(io.BytesIO(image_input)) as img:
                return _hash_pil_image(img)
        elif isinstance(image_input, Image.Image):
            return _hash_pil_image(image_input)
    except Exception as e:
        logger.debug("Failed to compute image pixel hash: %s", e)
    return None


def _hash_pil_image(img: Image.Image) -> str:
    rgba = img.convert("RGBA")
    prefix = f"{rgba.width}x{rgba.height}:".encode("utf-8")
    return hashlib.sha256(prefix + rgba.tobytes()).hexdigest()


def process_image_data(
    raw_bytes: bytes,
) -> Optional[Tuple[bytes, str, int, int]]:
    """Validates, normalizes to lossless PNG, and returns (png_bytes, pixel_hash, width, height)."""
    if not raw_bytes or len(raw_bytes) > MAX_IMAGE_BYTES:
        return None

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            width, height = img.size
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                logger.warning("Image dimensions (%dx%d) exceed limits (%dx%d)", width, height, MAX_IMAGE_WIDTH, MAX_IMAGE_HEIGHT)
                return None

            pixel_hash = _hash_pil_image(img)

            buf = io.BytesIO()
            img.save(buf, format="PNG")
            png_bytes = buf.getvalue()

            return png_bytes, pixel_hash, width, height
    except Exception as e:
        logger.debug("Image processing failed: %s", e)
        return None
