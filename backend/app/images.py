# =============================================================================
# images.py
# Purpose : Validates uploaded images and converts them to base64 data URLs,
#           the format the model API expects.
# Logic   : - Reject files that are too big.
#           - Detect the REAL type from the first bytes (magic numbers) instead
#             of trusting the browser's content-type, so non-images are refused.
#           - Nothing is written to disk: images live in memory only.
# =============================================================================
import base64

from fastapi import HTTPException, UploadFile

from .config import settings


def sniff_mime(data: bytes) -> str | None:
    """Return the image mime type from the file's first bytes, or None."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


async def read_images(files: list[UploadFile]) -> list[str]:
    """Read, validate and convert uploads to base64 data URLs."""
    urls: list[str] = []
    limit = settings.max_image_bytes
    for upload in files:
        data = await upload.read(limit + 1)  # read one byte extra to detect oversize
        if len(data) > limit:
            raise HTTPException(413, f"الصورة أكبر من {settings.max_image_mb} ميجا، صغّرها وجرب تاني.")
        mime = sniff_mime(data)
        if mime is None:
            raise HTTPException(415, "نوع الصورة مش مدعوم، ارفع JPG أو PNG أو WEBP.")
        encoded = base64.b64encode(data).decode("ascii")
        urls.append(f"data:{mime};base64,{encoded}")
    return urls
