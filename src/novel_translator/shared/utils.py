"""Pure helpers for hashing, redaction and JSON conversion."""

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, cast

SECRET_KEY_PATTERN = re.compile(
    r"(token(?![_-]?(count|estimate|estimates|usage|usages)\b)|secret|password|api[_-]?key|authorization)",
    re.IGNORECASE,
)


def sha256_text(value: str) -> str:
    """Return the SHA-256 hash of UTF-8 text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def redact(value: object) -> object:
    """Return a copy with secret-looking mapping values replaced."""
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {
            str(key): "***" if SECRET_KEY_PATTERN.search(str(key)) else redact(item) for key, item in mapping.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in cast(list[object], value)]
    return value


def json_default(value: Any) -> Any:
    """Convert common immutable application values to JSON primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(cast(Any, value))
    raise TypeError(f"Cannot serialize {type(value)!r}")


def json_dumps(value: Any) -> str:
    """Serialize a value deterministically without leaking secrets."""
    return json.dumps(
        redact(value),
        default=json_default,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
