# Pantaray Agents

Pantaray's Python runtimes.

| Distribution | Path | Contents |
|---|---|---|
| `pantaray-agents` | `agents/` (uv workspace root) | Local runtime, agents, and tools; ships inside the desktop app |
| `pantaray-llm` | `agents/packages/pantaray-llm` | Provider-neutral LLM contracts, error contract, and inference purposes |

`pantaray-agents` depends on `pantaray-llm`. The reverse direction is forbidden.

The local runtime processes desktop activity, maintains memory artifacts, and
executes user-approved actions.

Each distribution owns its tests; `agents/tests` holds the local runtime's and
the shared contracts'. CI installs only these two distributions, so neither can
quietly grow a dependency on anything the desktop app does not ship.

## Development

```sh
uv sync --all-extras --dev
uv run pytest -q tests/unit
uv run mypy
uv run ruff check .
uv build
```

Runtime configuration is explicit. Use the checked-in `.env.*.example` files as
the contract for each deployment role; required variables do not have silent
defaults.
