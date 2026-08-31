"""项目级 .env 加载器；不覆盖进程环境，也不记录密钥。"""

from __future__ import annotations

import os
from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class EnvFileError(ValueError):
    pass


def load_project_env(path: Path | None = None) -> set[str]:
    """从 .env 补充尚未设置的变量，返回本次加载的变量名。"""

    env_path = path or DEFAULT_ENV_FILE
    if not env_path.exists():
        return set()
    loaded: set[str] = set()
    for line_number, raw_line in enumerate(env_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise EnvFileError(f"invalid .env entry at line {line_number}")
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not _KEY_PATTERN.fullmatch(key):
            raise EnvFileError(f"invalid .env key at line {line_number}")
        value = _parse_value(raw_value.strip(), line_number)
        if not value or key in os.environ:
            continue
        os.environ[key] = value
        loaded.add(key)
    return loaded


def _parse_value(raw_value: str, line_number: int) -> str:
    if not raw_value:
        return ""
    if raw_value[0] in {"'", '"'}:
        quote = raw_value[0]
        if len(raw_value) < 2 or raw_value[-1] != quote:
            raise EnvFileError(f"unterminated quoted value at line {line_number}")
        return raw_value[1:-1]
    value, _, _comment = raw_value.partition(" #")
    return value.rstrip()
