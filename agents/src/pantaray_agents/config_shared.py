import logging
import os
from typing import Final

from pantaray_agents.runtime_config import (
    is_packaged_runtime,
    load_runtime_environment,
)

logger = logging.getLogger(__name__)

load_runtime_environment()

type ConfigScalar = str | int | float | bool | None
type ConfigValue = ConfigScalar | list["ConfigValue"] | dict[str, "ConfigValue"]
type AppConfig = dict[str, ConfigValue]

TRUTHY_VALUES: Final[frozenset[str]] = frozenset({"1", "true", "yes", "y", "on"})


def required_env(name: str) -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        raise ValueError(f"Missing required environment variable: {name}")
    return raw


def optional_env(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw


def parse_env_bool(name: str) -> bool:
    return required_env(name).strip().lower() in TRUTHY_VALUES


def split_csv_env(name: str) -> list[str]:
    values = [part.strip() for part in required_env(name).split(",") if part.strip()]
    if not values:
        raise ValueError(f"{name} must contain at least one valid value")
    return values


def require_mock_mode_allowed(*, use_mocks: bool, environment: str) -> None:
    """production と packaged desktop build では mock モードを禁止する。

    mock モードは token を検証せず固定の利用者として通すため、配布物で有効になると
    認証が完全に無効化される。packaged bundle は USE_MOCKS を自由に指定できるので、
    設定境界で閉じる。
    """

    if not use_mocks:
        return
    if environment == "production":
        raise ValueError("USE_MOCKS must be false when NODE_ENV=production")
    if is_packaged_runtime():
        raise ValueError("USE_MOCKS must be false in a packaged desktop build")


def is_local_runtime_mode() -> bool:
    return True
