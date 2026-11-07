"""Isolated file-backed SQLite for concurrent browser requests; no business DB."""
import tempfile
import uuid
from pathlib import Path

from flamia.settings import *  # noqa: F403

DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": ":memory:",
    "TEST": {"NAME": str(Path(tempfile.gettempdir()) / f"flamia-test-{uuid.uuid4().hex}.sqlite3")},
    "OPTIONS": {"timeout": 20},
}}
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
