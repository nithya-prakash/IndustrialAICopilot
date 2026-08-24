"""Filename sanitization for user-supplied upload filenames.

Storage never depends on this — every uploaded file is written under a
UUID-based path (see app/services/document_service.py: `f"{version_id}.pdf"`),
so a malicious filename was never able to become a filesystem path. This
sanitizes the *displayed* original_filename (shown in the UI, included in
diagnostic reports, returned in API responses, written to logs) so it can't
carry path-traversal segments, control characters, or filesystem-reserved
characters into those contexts — while keeping the parts a technician
actually needs to recognize their file, including non-ASCII characters
(accented names, other scripts), which a strict ASCII allowlist would have
destroyed.
"""
import re
from pathlib import PurePosixPath, PureWindowsPath

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED_CHARS_RE = re.compile(r'[/\\<>:"|?*]')
_MAX_LENGTH = 255
DEFAULT_FILENAME = "upload.pdf"


def sanitize_display_filename(raw: str | None) -> str:
    """Strips any directory component (POSIX or Windows separators), control
    characters, and filesystem-reserved characters; truncates to a safe
    length. Falls back to DEFAULT_FILENAME if nothing usable remains."""
    if not raw:
        return DEFAULT_FILENAME

    # Strip a leading path regardless of separator style — .name discards
    # everything up to and including the final separator, so "../../etc/x"
    # and "..\\..\\windows\\x" both reduce to just "x".
    name = PureWindowsPath(PurePosixPath(raw).name).name

    name = _CONTROL_CHARS_RE.sub("", name)
    name = _RESERVED_CHARS_RE.sub("_", name)
    name = name.strip().lstrip(".")

    return name[:_MAX_LENGTH] or DEFAULT_FILENAME
