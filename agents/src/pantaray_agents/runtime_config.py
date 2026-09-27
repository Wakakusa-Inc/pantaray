import json
import os
import re
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

ENV_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Z][A-Z0-9_]*$")
TRUTHY_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "y", "on"})
AGENTS_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PACKAGED_RUNTIME_CONFIG_FILENAME: Final[str] = "env.local.backend.json"
RUNTIME_CONFIG_PATH_ENV: Final[str] = "PANTARAY_AGENTS_RUNTIME_CONFIG_PATH"
NODE_ENV_KEY: Final[str] = "NODE_ENV"
VALID_NODE_ENV_VALUES: Final[frozenset[str]] = frozenset(
    {"development", "production", "test"}
)


def is_packaged_runtime() -> bool:
    """packaged desktop build かどうか。`main.ts:66` が app.isPackaged から設定する。"""

    raw = os.getenv("PANTARAY_PACKAGED", "")
    return raw.strip().lower() in TRUTHY_VALUES


def _has_runtime_config_path() -> bool:
    return bool(os.getenv(RUNTIME_CONFIG_PATH_ENV, "").strip())


def _normalize_runtime_value(key: str, value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            raise RuntimeError(f"runtime_config.json has empty value for {key}")
        return normalized
    raise RuntimeError(
        f"runtime_config.json value for {key} must be string/number/bool"
    )


def _runtime_config_path() -> Path:
    raw = os.getenv(RUNTIME_CONFIG_PATH_ENV, "").strip()
    if not raw:
        raise RuntimeError(f"Missing {RUNTIME_CONFIG_PATH_ENV} for packaged runtime")
    return Path(raw).expanduser().resolve()


def _load_packaged_runtime_config() -> None:
    config_path = _runtime_config_path()
    if not config_path.exists():
        raise RuntimeError(f"Missing {PACKAGED_RUNTIME_CONFIG_FILENAME}: {config_path}")

    try:
        parsed = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Invalid {PACKAGED_RUNTIME_CONFIG_FILENAME}: {config_path}"
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(f"{PACKAGED_RUNTIME_CONFIG_FILENAME} root must be an object")

    for key, value in parsed.items():
        if not isinstance(key, str) or not ENV_KEY_PATTERN.fullmatch(key):
            raise RuntimeError(
                f"Invalid {PACKAGED_RUNTIME_CONFIG_FILENAME} key: {key!r}"
            )
        os.environ[key] = _normalize_runtime_value(key, value)


def _load_development_env_files() -> None:
    candidates = (
        AGENTS_ROOT / ".env.local.backend.local",
        AGENTS_ROOT / ".env.local-runtime.dev",
        AGENTS_ROOT / ".env.local-runtime",
    )
    for path in candidates:
        if path.exists():
            load_dotenv(dotenv_path=path, override=False)


def _require_valid_node_env() -> None:
    """NODE_ENV を検証する。既定値へ落とさず、不正なら起動を止める。

    packaged 経路の値は Electron 側 (`local_backend_runtime_bundle.js`) が
    bundle 生成時に検証・強制済みなので、ここで弾かれるのは手書きの dev env だけ。
    """

    raw = os.getenv(NODE_ENV_KEY)
    value = "" if raw is None else raw.strip()
    if value not in VALID_NODE_ENV_VALUES:
        raise RuntimeError(
            f"{NODE_ENV_KEY} must be one of "
            f"{', '.join(sorted(VALID_NODE_ENV_VALUES))}; got {raw!r}"
        )
    os.environ[NODE_ENV_KEY] = value


def load_runtime_environment() -> None:
    if _has_runtime_config_path() or is_packaged_runtime():
        _load_packaged_runtime_config()
    else:
        _load_development_env_files()
    _require_valid_node_env()
