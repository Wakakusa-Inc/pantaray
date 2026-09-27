from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from pantaray_agents.config_local_runtime import (
    ALLOWED_HOSTS,
    ALLOWED_ORIGINS,
    LOG_FILE_PATH,
    LOG_LEVEL,
    require_valid_startup_config_or_exit,
    settings,
)
from pantaray_agents.local_runtime import (
    start_local_runtime_if_enabled,
    stop_local_runtime_if_enabled,
)
from pantaray_agents.local_runtime.runtime.local_api_auth import (
    authenticate_local_api_request,
)
from pantaray_agents.local_runtime.runtime.main_process_monitor import (
    monitor_main_process_lifecycle,
)
from pantaray_agents.routers.local.registry import register_local_routers
from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    clear_active_settings_module,
    register_active_settings_module,
)

from .shared import (
    configure_logging,
    create_base_app,
    finalize_app,
    install_common_middleware,
)


@asynccontextmanager
async def _local_app_lifespan(app: FastAPI):
    try:
        register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)
        require_valid_startup_config_or_exit()
        app.state.authenticate_request = authenticate_local_api_request
        try:
            start_local_runtime_if_enabled()
            async with monitor_main_process_lifecycle():
                yield
        finally:
            stop_local_runtime_if_enabled()
    finally:
        clear_active_settings_module()


def create_local_app():
    logger = configure_logging(
        log_level=LOG_LEVEL,
        log_file_path=LOG_FILE_PATH,
        enable_console=False,
    )
    logger.info("Starting local backend with log level: %s", LOG_LEVEL)
    logger.info("Allowed Origins: %s", ALLOWED_ORIGINS)
    logger.info("Allowed Hosts: %s", ALLOWED_HOSTS)
    logger.info("Mock Mode: %s", settings["use_mocks"])

    app = create_base_app(
        title="Pantaray Local Backend",
        description="Local backend runtime for Pantaray desktop",
        lifespan=_local_app_lifespan,
    )

    install_common_middleware(app, allowed_origins=ALLOWED_ORIGINS)
    register_local_routers(app)
    finalize_app(app)
    return app
