import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.core.filenames import DEFAULT_FILENAME, sanitize_display_filename

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>"
)


# --- unit tests: app.core.filenames.sanitize_display_filename ---


def test_none_or_empty_falls_back_to_default() -> None:
    assert sanitize_display_filename(None) == DEFAULT_FILENAME
    assert sanitize_display_filename("") == DEFAULT_FILENAME


def test_posix_path_traversal_is_stripped_to_basename() -> None:
    assert sanitize_display_filename("../../etc/passwd") == "passwd"
    assert sanitize_display_filename("../../../manual.pdf") == "manual.pdf"


def test_windows_path_traversal_is_stripped_to_basename() -> None:
    assert (
        sanitize_display_filename("..\\..\\windows\\system32\\config.pdf") == "config.pdf"
    )


def test_reserved_filesystem_characters_are_replaced() -> None:
    result = sanitize_display_filename('evil<script>.pdf')
    assert "<" not in result
    assert ">" not in result
    assert result == "evil_script_.pdf"


def test_control_characters_and_null_bytes_are_stripped() -> None:
    result = sanitize_display_filename("manual\x00\x1f.pdf")
    assert "\x00" not in result
    assert "\x1f" not in result
    assert result == "manual.pdf"


def test_legitimate_filename_with_spaces_and_parens_is_preserved() -> None:
    assert sanitize_display_filename("Motor Manual (v2).pdf") == "Motor Manual (v2).pdf"


def test_legitimate_unicode_filename_is_preserved_not_destroyed() -> None:
    """A strict ASCII allowlist would have mangled this — accented/non-Latin
    filenames are legitimate and should survive sanitization intact."""
    assert sanitize_display_filename("café_manual_日本語.pdf") == "café_manual_日本語.pdf"


def test_very_long_filename_is_truncated() -> None:
    long_name = ("a" * 300) + ".pdf"
    result = sanitize_display_filename(long_name)
    assert len(result) == 255


def test_all_dots_falls_back_to_default() -> None:
    assert sanitize_display_filename("...") == DEFAULT_FILENAME


def test_hidden_file_style_leading_dot_is_stripped() -> None:
    assert sanitize_display_filename(".hidden.pdf") == "hidden.pdf"


def test_normal_filename_is_unchanged() -> None:
    assert sanitize_display_filename("electric_motor_manual_v3.pdf") == (
        "electric_motor_manual_v3.pdf"
    )


# --- HTTP-level: a malicious filename cannot cause filesystem traversal,
# and a legitimate filename still displays correctly ---


@pytest.fixture(autouse=True)
def isolated_storage(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def no_celery_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.document_service.process_document_version_task.delay",
        lambda *args, **kwargs: None,
    )


async def _register(client: AsyncClient, username: str, tenant_id: str = "acme") -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
            "tenant_id": tenant_id,
        },
    )
    assert response.status_code == 201
    return response.json()["access_token"]


async def test_malicious_filename_is_sanitized_not_used_as_a_path(
    client: AsyncClient, tmp_path
) -> None:
    token = await _register(client, "tech_filename")
    response = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("../../../etc/passwd.pdf", MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()

    assert body["original_filename"] == "passwd.pdf"
    assert ".." not in body["original_filename"]
    assert "/" not in body["original_filename"]

    # nothing was written outside the isolated storage directory
    manuals_dir = tmp_path / "manuals"
    assert manuals_dir.exists()
    for f in manuals_dir.iterdir():
        assert f.parent == manuals_dir  # UUID-named file, no path escape


async def test_legitimate_filename_still_displays_correctly(client: AsyncClient) -> None:
    token = await _register(client, "tech_filename_ok")
    response = await client.post(
        "/api/v1/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("electric_motor_manual_v3.pdf", MINIMAL_PDF, "application/pdf")},
    )
    assert response.status_code == 201
    assert response.json()["original_filename"] == "electric_motor_manual_v3.pdf"
