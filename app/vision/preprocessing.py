"""Image validation and preprocessing before it's sent to a VLM.

Trusting a client-supplied Content-Type header is not validation — a
malicious or malformed file could claim to be a JPEG and be something else
entirely. This decodes the file with PIL (rejecting anything that isn't a
real, fully-decodable image), then re-encodes it, which has the side effect
of stripping EXIF metadata (which can carry GPS/location data — a
meaningful privacy leak for a technician's phone photo) and downscaling it
to a bounded size.
"""
import io

from PIL import Image, UnidentifiedImageError

from app.config import get_settings


class InvalidImageError(Exception):
    pass


def validate_and_preprocess(content: bytes) -> tuple[bytes, str]:
    """Returns (processed_jpeg_bytes, media_type)."""
    settings = get_settings()

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise InvalidImageError("File is not a valid, decodable image") from exc

    image = image.convert("RGB")

    max_dim = settings.image_max_dimension_px
    if max(image.size) > max_dim:
        image.thumbnail((max_dim, max_dim), Image.LANCZOS)

    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)  # re-encode: drops EXIF
    return output.getvalue(), "image/jpeg"
