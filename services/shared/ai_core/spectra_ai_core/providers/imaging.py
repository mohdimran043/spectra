"""Image helpers shared by the vision, OCR and multimodal-embedding providers."""

from __future__ import annotations

import base64
from typing import Any

MAGIC_MIME: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
)
WEBP_PREFIX = b"RIFF"
WEBP_TAG = b"WEBP"
FALLBACK_MIME = "application/octet-stream"
BRIGHTNESS_MAX = 255.0
DARK_THRESHOLD = 0.35
LIGHT_THRESHOLD = 0.70
DOMINANT_COLOUR_COUNT = 3
HISTOGRAM_SAMPLE_PX = 256


def sniff_mime(image_bytes: bytes) -> str:
    """Identify an image MIME type from its magic bytes; no external dependency."""
    for magic, mime in MAGIC_MIME:
        if image_bytes.startswith(magic):
            return mime
    if image_bytes[:4] == WEBP_PREFIX and image_bytes[8:12] == WEBP_TAG:
        return "image/webp"
    return FALLBACK_MIME


def data_uri(image_bytes: bytes) -> str:
    """``data:`` URI for OpenAI-shaped ``image_url`` content parts."""
    return f"data:{sniff_mime(image_bytes)};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def open_image(image_bytes: bytes) -> Any:
    """Decode to a PIL image.  Raises ``ValueError`` when the bytes are not an image."""
    import io

    from PIL import Image

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        return image
    except Exception as exc:
        raise ValueError(f"not a decodable image ({type(exc).__name__}: {exc})") from exc


def image_stats(image_bytes: bytes) -> dict[str, Any]:
    """Deterministic, model-free description of an image.

    Used by the deterministic vision tier, which must never invent content: every
    field here is measured from the pixels.
    """
    try:
        image = open_image(image_bytes)
    except ValueError as exc:
        return {"error": str(exc), "byte_size": len(image_bytes), "mime": sniff_mime(image_bytes)}
    width, height = image.size
    rgb = image.convert("RGB")
    thumbnail = rgb.resize((HISTOGRAM_SAMPLE_PX, HISTOGRAM_SAMPLE_PX)) if width * height else rgb
    pixels = list(thumbnail.getdata())
    brightness = sum(sum(pixel) / 3.0 for pixel in pixels) / (len(pixels) or 1) / BRIGHTNESS_MAX
    return {
        "mime": sniff_mime(image_bytes),
        "byte_size": len(image_bytes),
        "width": width,
        "height": height,
        "mode": image.mode,
        "aspect_ratio": round(width / height, 3) if height else 0.0,
        "mean_brightness": round(brightness, 4),
        "tone": _tone(brightness),
        "dominant_colours": _dominant_colours(pixels),
    }


def _tone(brightness: float) -> str:
    if brightness < DARK_THRESHOLD:
        return "dark"
    return "light" if brightness > LIGHT_THRESHOLD else "mid-tone"


def _dominant_colours(pixels: list[tuple[int, ...]]) -> list[str]:
    from collections import Counter

    quantised = Counter(tuple(channel // 32 * 32 for channel in pixel) for pixel in pixels)
    return [
        "#{:02x}{:02x}{:02x}".format(*colour[:3])
        for colour, _ in quantised.most_common(DOMINANT_COLOUR_COUNT)
    ]
