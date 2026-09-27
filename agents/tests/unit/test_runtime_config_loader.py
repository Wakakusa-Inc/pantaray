import json
from pathlib import Path

import pytest

from pantaray_agents import runtime_config


def test_load_runtime_environment_reads_development_local_runtime_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runtime_config, "AGENTS_ROOT", tmp_path)
    monkeypatch.delenv("PANTARAY_PACKAGED", raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)

    (tmp_path / ".env.local-runtime.dev").write_text(
        "NODE_ENV=development\nLOG_LEVEL=DEBUG\n",
        encoding="utf-8",
    )

    runtime_config.load_runtime_environment()

    assert runtime_config.os.getenv("NODE_ENV") == "development"
    assert runtime_config.os.getenv("LOG_LEVEL") == "DEBUG"


@pytest.mark.parametrize("raw_node_env", ["dproduction", "prod", "", "Production"])
def test_load_runtime_environment_rejects_invalid_node_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw_node_env: str
) -> None:
    monkeypatch.setattr(runtime_config, "AGENTS_ROOT", tmp_path)
    monkeypatch.delenv("PANTARAY_PACKAGED", raising=False)
    monkeypatch.delenv(runtime_config.RUNTIME_CONFIG_PATH_ENV, raising=False)
    monkeypatch.setenv("NODE_ENV", raw_node_env)

    with pytest.raises(RuntimeError, match="NODE_ENV must be one of"):
        runtime_config.load_runtime_environment()


def test_load_runtime_environment_rejects_missing_node_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runtime_config, "AGENTS_ROOT", tmp_path)
    monkeypatch.delenv("PANTARAY_PACKAGED", raising=False)
    monkeypatch.delenv(runtime_config.RUNTIME_CONFIG_PATH_ENV, raising=False)
    monkeypatch.delenv("NODE_ENV", raising=False)

    with pytest.raises(RuntimeError, match="NODE_ENV must be one of"):
        runtime_config.load_runtime_environment()


def test_load_runtime_environment_reads_packaged_runtime_config_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_path = tmp_path / runtime_config.PACKAGED_RUNTIME_CONFIG_FILENAME
    config_path.write_text(
        json.dumps(
            {
                "NODE_ENV": "production",
                "LOG_LEVEL": "INFO",
                "LOCAL_LOOPBACK_BIND_PORT": 8005,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("PANTARAY_PACKAGED", "1")
    monkeypatch.setenv(runtime_config.RUNTIME_CONFIG_PATH_ENV, str(config_path))
    monkeypatch.delenv("NODE_ENV", raising=False)
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOCAL_LOOPBACK_BIND_PORT", raising=False)

    runtime_config.load_runtime_environment()

    assert runtime_config.os.getenv("NODE_ENV") == "production"
    assert runtime_config.os.getenv("LOG_LEVEL") == "INFO"
    assert runtime_config.os.getenv("LOCAL_LOOPBACK_BIND_PORT") == "8005"


def test_load_runtime_environment_fails_closed_when_packaged_runtime_config_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PANTARAY_PACKAGED", "1")
    monkeypatch.setenv(
        runtime_config.RUNTIME_CONFIG_PATH_ENV, str(tmp_path / "missing.json")
    )

    with pytest.raises(RuntimeError, match="Missing env.local.backend.json"):
        runtime_config.load_runtime_environment()


def test_load_runtime_environment_fails_closed_when_packaged_runtime_config_path_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PANTARAY_PACKAGED", "1")
    monkeypatch.delenv(runtime_config.RUNTIME_CONFIG_PATH_ENV, raising=False)

    with pytest.raises(
        RuntimeError,
        match=f"Missing {runtime_config.RUNTIME_CONFIG_PATH_ENV} for packaged runtime",
    ):
        runtime_config.load_runtime_environment()
