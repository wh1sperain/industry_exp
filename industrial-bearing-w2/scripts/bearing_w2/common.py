"""Small shared types; no experiment initialization or network side effects."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath


class W2Error(ValueError):
    def __init__(self, code, message, field=None):
        super().__init__(message)
        self.code, self.field = code, field

    def as_dict(self):
        return {"code": self.code, "message": str(self), "field": self.field}


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def safe_relative(key):
    """Treat either separator as syntax, including on Windows."""
    win = PureWindowsPath(key)
    posix = PurePosixPath(key.replace("\\", "/"))
    if win.drive or win.root or posix.is_absolute() or any(
            p in ("..", ".") or ":" in p for p in posix.parts):
        raise W2Error("E_SOURCE", "unsafe embedded path", key)
    if not posix.parts:
        raise W2Error("E_SOURCE", "empty embedded path", key)
    return Path(*posix.parts)


def spans(question):
    result, offset = [], 0
    question_hash = hashlib.sha256(question.encode("utf-8")).hexdigest()
    for number, line in enumerate(question.splitlines(keepends=True), 1):
        result.append({"span_id": f"s{number:04d}", "start": offset,
                       "end": offset + len(line), "text": line,
                       "question_sha256": question_hash})
        offset += len(line)
    return result


def finite(value, name="value", minimum=None, strict=False):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise W2Error("E_RANGE", "finite number required", name)
    if minimum is not None and (value < minimum or strict and value == minimum):
        raise W2Error("E_RANGE", "outside relation domain", name)
    return float(value)


def quantity(value, unit, quantity_type, **metadata):
    if isinstance(value, (float, int)):
        finite(value)
    return {"value": value, "unit": unit, "quantity_type": quantity_type, **metadata}
