"""Android-compatible serialization for Flet SharedPreferences.

Flet SharedPreferences supports scalar values and lists of strings, not lists
of dictionaries.  Keep profile and history lists as a JSON *string*.
"""
from __future__ import annotations

import json


def encode_records(records: list[dict], limit: int) -> str:
    """Serialize up to ``limit`` dictionary records to a supported string."""
    if not isinstance(records, list):
        raise ValueError("Ожидался список записей")
    return json.dumps(
        [item for item in records[:limit] if isinstance(item, dict)],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def decode_records(value: object, limit: int) -> list[dict]:
    """Read JSON storage; also understand potential legacy in-memory lists."""
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    else:
        parsed = value
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed[:limit] if isinstance(item, dict)]
