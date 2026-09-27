# Contributing to Pantaray

Thanks for your interest in Pantaray. Bug reports are welcome in
[GitHub Issues](https://github.com/Wakakusa-Inc/pantaray/issues). We are not accepting pull requests
at this time. The rest of this guide covers building and running Pantaray from source.

## Reporting bugs

Please include:

- The Pantaray version (**Pantaray → About Pantaray** in the menu bar), and your macOS version
- Which connection you were using — a Pantaray account, your own API key, or a ChatGPT sign-in
- What you expected, what happened, and the steps to reproduce

**Privacy note:** Pantaray works on your own activity, so logs, screenshots, and conversations
contain your personal data. Redact before pasting into a public issue, and never paste an API key,
an access token, or the contents of your local database.

Security and privacy vulnerabilities go through [SECURITY.md](SECURITY.md), not public issues.

## Repository layout

| Directory | Contents |
| --- | --- |
| `frontend/electron/` | The Electron main and preload processes |
| `frontend/src/` | The renderer: React, and the message catalogs under `src/i18n/` |
| `frontend/scripts/` | Build and packaging helpers, including the bundled Python runtime |
| `agents/src/pantaray_agents/` | The local Python runtime and the agents |
| `agents/packages/pantaray-llm/` | The shared provider contracts and adapters |
| `scripts/` | CI helpers |

Requests from the renderer always go through Electron main; the renderer never talks to the Python
runtime directly. The runtime listens on loopback on a port chosen at startup and authenticates
every request with a token it generates per run, which main holds and the renderer never sees.

## Development setup

You need a Mac with Apple silicon. The packaging scripts refuse to run on anything else, and the
app is macOS arm64 only.

| Tool | Version | Pinned by |
| --- | --- | --- |
| Node.js | 24 | `.node-version` |
| pnpm | 11.20.0 | `frontend/package.json` (`packageManager`) |
| Python | 3.12 | `agents/.python-version`, `agents/pyproject.toml` |
| uv | 0.12.0 or newer | `agents/pyproject.toml` (`[tool.uv] required-version`) |

### 1. Environment files

Both runtimes are fail-closed: a missing required variable stops startup with an explicit error
rather than falling back to a default. Create both files and fill in every key.

```bash
cp frontend/.env.example frontend/.env.local
cp agents/.env.local.backend.example agents/.env.local.backend.local
```

`frontend/.env.local` needs, among the keys documented in the example:

- `BACKEND_URL` and `VITE_API_HOST` — the loopback origin the renderer may reach. They must match,
  and `VITE_API_HOST` is what the packaged app's content security policy allows.
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VITE_WEB_APP_URL` — the Pantaray account
  sign-in. These are public client values, not secrets.

`agents/.env.local.backend.local` needs every key in the example, **plus three that the example
does not list**:

```dotenv
LOCAL_DB_PATH=<absolute path to a SQLite file>
LOCAL_ARTIFACT_ROOT=<absolute path to a directory>
LOCAL_DB_BUSY_TIMEOUT_MS=<milliseconds>
```

It also requires `LLM_PROXY_URL` and `WEB_TOOLS_PROXY_URL`. They are full URLs, used as given with
no path completion, and they are only contacted while signed in to a Pantaray account — signed out,
inference and web search go straight to the provider you configured in the app.

**Never put a provider secret in these files.** `OPENAI_API_KEY`, `TAVILY_API_KEY` and friends do
not belong there; the app takes provider credentials through its own settings screen, encrypts
them, and keeps them out of the runtime's configuration entirely.

### 2. Run the app

```bash
cd frontend
pnpm install
pnpm run electron:dev
```

The development UI uses port 3001 by default. To change it, set `FRONTEND_PORT=3002`
in `frontend/.env.local` (or choose another available port). An explicit shell environment
variable takes precedence. Vite and Electron use the same port; an invalid value or an
occupied port stops startup with an error. Packaged desktop builds load bundled HTML
and do not use this setting.

That one command starts Vite, Electron main, and the local Python runtime. The runtime is launched
by Electron on a loopback port chosen at startup, so you do not need to start it yourself, and you
do not need Docker.

To work on the Python side alone:

```bash
cd agents
uv sync --python 3.12 --extra dev --frozen
PYTHONPATH=src uv run python -m pantaray_agents --host 127.0.0.1 --port 8005 --reload
```

The OpenAPI browser is then at `http://127.0.0.1:8005/docs`.

### 3. Mock mode

`scripts/dev-mock.sh` starts the runtime with `USE_MOCKS=true`, so the interfaces and the UI can be
exercised without calling a real provider:

```bash
bash scripts/dev-mock.sh          # RELOAD=true for hot reload
```

`USE_MOCKS` is read when `pantaray_agents.config` is imported, so set it before the import rather
than inside a test body.

## Running the checks

`scripts/ci/run_local_ci.py` runs the same commands the CI workflows run, and only for the targets
your change touches. The default `--mode staged` looks at staged changes; use `--mode worktree`
while you are still working, and `--mode all` to run everything. It stops at the first failure.

```bash
python3 scripts/ci/run_local_ci.py --mode worktree
```

The repository ships a pre-push hook that runs it in `staged` mode. Enable it once:

```bash
git config core.hooksPath .githooks
```

The individual commands, if you prefer to run them directly:

```bash
# Renderer and web
cd frontend && node scripts/check-icon-policy.js
cd frontend && pnpm run lint && pnpm run test:vitest && pnpm run build:web

# Electron main and packaging scripts
cd frontend && pnpm run test:node

# Python runtime
cd agents && uv run ruff check . && uv run ruff format --check .
cd agents && uv run mypy
cd agents && uv run pytest -q -n auto --dist loadfile tests/unit
```

Icons come from `lucide-react` only; `check-icon-policy.js` enforces that.

## Writing tests

`agents/tests/TESTING_GUIDELINES.md` is the reference. The points that catch people out:

- **Verify that fail-closed paths actually fail.** A missing required variable, a tool that is not
  allowed, or malformed model output must raise, not get quietly filled in.
- **Keep tests hermetic.** No real network, no real account.
- **Share fixtures through a `fixtures.py`**, not by importing one `conftest.py` from another.
- `MockRepository` keeps a shared store — call `clear_data()` so tests stay independent.

**Tests must not call a real provider.** Anything that spends money or depends on someone's account
— a real OpenAI, Anthropic, Fireworks, ChatGPT, or Tavily request — stays out of CI and out of the
unit suites. Cover the provider adapters with fixed responses.

## Never commit secrets

API keys, access tokens, `.env` files, and database contents do not belong in the repository. The
environment files above are all git-ignored; keep it that way. If you believe a secret has been
committed, treat it as a security report and follow [SECURITY.md](SECURITY.md).
