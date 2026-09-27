import logging
from typing import Final

from pantaray_agents.config_shared import (
    AppConfig,
    optional_env,
    parse_env_bool,
    require_mock_mode_allowed,
    required_env,
    split_csv_env,
)
from pantaray_agents.config_shared import (
    AppConfig as _AppConfig,
)
from pantaray_agents.config_tunables import load_local_runtime_tunables
from pantaray_agents.utils.url_validation import parse_network_url

logger = logging.getLogger(__name__)

USE_MOCKS: Final[bool] = parse_env_bool("USE_MOCKS")
ENVIRONMENT: Final[str] = required_env("NODE_ENV")
LOG_LEVEL: Final[str] = required_env("LOG_LEVEL").upper()
LOG_FILE_PATH: Final[str] = required_env("LOG_FILE_PATH")
ALLOWED_ORIGINS: Final[list[str]] = split_csv_env("ALLOWED_ORIGINS")
ALLOWED_HOSTS: Final[list[str]] = split_csv_env("ALLOWED_HOSTS")

require_mock_mode_allowed(use_mocks=USE_MOCKS, environment=ENVIRONMENT)


def validate_env_vars() -> tuple[list[str], list[str]]:
    required_env_vars = [
        "NODE_ENV",
        "LOG_LEVEL",
        "LOG_FILE_PATH",
        "USE_MOCKS",
        "ALLOWED_ORIGINS",
        "ALLOWED_HOSTS",
        "LOCAL_DB_PATH",
        "LOCAL_DB_BUSY_TIMEOUT_MS",
        "LOCAL_ARTIFACT_ROOT",
        "LLM_PROXY_URL",
        "WEB_TOOLS_PROXY_URL",
    ]
    missing = [name for name in required_env_vars if not optional_env(name)]
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}"
        )
    parse_network_url(
        required_env("LLM_PROXY_URL"),
        env_name="LLM_PROXY_URL",
        allow_path=True,
    )
    parse_network_url(
        required_env("WEB_TOOLS_PROXY_URL"),
        env_name="WEB_TOOLS_PROXY_URL",
        allow_path=True,
    )
    return ALLOWED_ORIGINS, ALLOWED_HOSTS


def require_valid_startup_config_or_exit() -> None:
    """起動時に env と checked-in tunables の両方を検証し、不正なら起動を止める。"""

    try:
        validate_env_vars()
        load_local_runtime_tunables()
    except (ValueError, RuntimeError) as exc:
        logger.critical("Configuration error: %s", exc)
        raise SystemExit(f"Configuration error: {exc}") from exc


def get_app_config() -> _AppConfig:
    return {
        "mode": "local_runtime",
        "allowed_origins": ALLOWED_ORIGINS,
        "allowed_hosts": ALLOWED_HOSTS,
        "environment": ENVIRONMENT,
        "log_level": LOG_LEVEL,
        "use_mocks": USE_MOCKS,
        "aws_region": None,
        "desktop_updates_bucket": None,
        "desktop_updates_prefix": None,
    }


settings: Final[AppConfig] = get_app_config()
