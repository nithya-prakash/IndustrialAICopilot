import io

import pytest
from PIL import Image

from app.vision.preprocessing import InvalidImageError, validate_and_preprocess


def _make_png(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 40, 40))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_valid_image_is_accepted_and_reencoded_as_jpeg() -> None:
    content = _make_png(200, 150)
    processed, media_type = validate_and_preprocess(content)

    assert media_type == "image/jpeg"
    result_image = Image.open(io.BytesIO(processed))
    assert result_image.format == "JPEG"
    assert result_image.size == (200, 150)


def test_corrupt_bytes_are_rejected() -> None:
    with pytest.raises(InvalidImageError):
        validate_and_preprocess(b"this is not an image, just text pretending to be one")


def test_truncated_image_is_rejected() -> None:
    content = _make_png(200, 150)
    with pytest.raises(InvalidImageError):
        validate_and_preprocess(content[: len(content) // 2])


def test_oversized_image_is_downscaled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "image_max_dimension_px", 100)

    content = _make_png(400, 200)
    processed, _media_type = validate_and_preprocess(content)

    result_image = Image.open(io.BytesIO(processed))
    assert max(result_image.size) <= 100


def test_image_within_bounds_is_not_upscaled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "image_max_dimension_px", 1000)

    content = _make_png(200, 150)
    processed, _media_type = validate_and_preprocess(content)

    result_image = Image.open(io.BytesIO(processed))
    assert result_image.size == (200, 150)


def test_exif_is_stripped_by_reencoding() -> None:
    image = Image.new("RGB", (50, 50), color=(0, 0, 0))
    buf = io.BytesIO()
    exif = Image.Exif()
    exif[0x9286] = "sensitive comment"  # UserComment tag
    image.save(buf, format="JPEG", exif=exif)
    content = buf.getvalue()

    original = Image.open(io.BytesIO(content))
    assert original.getexif().get(0x9286) == "sensitive comment"

    processed, _media_type = validate_and_preprocess(content)
    result_image = Image.open(io.BytesIO(processed))
    assert not result_image.getexif()
