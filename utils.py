"""Helpers shared by the routes."""

import re

# The three Drive URL shapes an administrator is likely to paste.
_DRIVE_PATTERNS = (
    re.compile(r"/file/d/([A-Za-z0-9_-]{10,})"),        # /file/d/<id>/view
    re.compile(r"[?&]id=([A-Za-z0-9_-]{10,})"),          # open?id=<id>
    re.compile(r"/document/d/([A-Za-z0-9_-]{10,})"),     # Docs-style links
)

# A bare file id pasted on its own.
_BARE_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")


def extract_drive_file_id(value: str) -> str | None:
    """Pull the Drive file id out of a pasted link.

    Returns None when nothing that looks like a file id can be found, so the
    caller can report the problem instead of storing a broken link.
    """
    if not value:
        return None
    value = value.strip()
    for pattern in _DRIVE_PATTERNS:
        match = pattern.search(value)
        if match:
            return match.group(1)
    if _BARE_ID.match(value):
        return value
    return None


def drive_preview_url(file_id: str) -> str:
    """Embeddable viewer. Cheaper against Drive's quota than a download."""
    return f"https://drive.google.com/file/d/{file_id}/preview"


def drive_view_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def drive_download_url(file_id: str) -> str:
    return f"https://drive.google.com/uc?export=download&id={file_id}"


def as_int(value, minimum: int | None = None, maximum: int | None = None):
    """Coerce a query-string value to int, or None when blank or invalid.

    Blank is meaningful here: an empty filter means 'do not filter', so an
    unparseable value is treated the same way rather than raising.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = int(text)
    except ValueError:
        return None
    if minimum is not None and number < minimum:
        return None
    if maximum is not None and number > maximum:
        return None
    return number


def clean_text(value, limit: int = 200) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text[:limit] or None
