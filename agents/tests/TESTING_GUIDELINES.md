# Pantaray Agents テストガイド

## 1. 目的

このドキュメントは、`pantaray-agents` 配布物（`agents/tests`）の現行テスト構成を素早く把握し、変更に対して適切なテストを追加・実行するための実務ガイドです。

特に次の判断を迷わず行えることを目的とします。

- どのコードパスを、どのテスト群が担保しているか
- そのテスト群がどの CI ジョブで回るか
- 新しいテストをどこへ追加すべきか
- Action Agent まわりの共通フィクスチャをどう再利用するか
- エントリポイントや Orchestration 系で起きやすい import 順・環境変数依存の落とし穴をどう避けるか

旧来の大きな単一ファイル構成は解消されています。たとえば、旧 `tests/unit/agents/test_suggestion_agent.py` を前提にせず、現在の分割済みディレクトリ構成を正として扱ってください。

## 2. 現在のテスト方針

### 2.1 テストの原則

- **fail-closed を検証する**: 必須 env 未設定、許可外ツール、曖昧参照、不正な LLM 出力は黙って補完せず、明示的に失敗することを確認します。
- **hermetic に実行する**: 外部 Supabase や実ネットワークに依存しないよう、モックと dependency override を使います。
- **責務ごとに分割する**: Action Agent 本体、tool 実装、Suggestion Agent、Orchestration/WS を別スイートに分けて保守します。
- **共通化は `fixtures.py` に寄せる**: `conftest.py` の相互 import ではなく、明示的なモジュールを介して共有します。

### 2.2 実行前提

- 実行ディレクトリは `agents` です。
- `pytest.ini` では `testpaths = tests`、`pythonpath = src packages/pantaray-llm/src .`、
  `asyncio_mode = auto`、`addopts = --import-mode=importlib` を設定しています。
- `tests/conftest.py` が pytest プロセスごとに `/tmp/pnt-*` の runtime ルートを作り、
  `LOCAL_DB_PATH` などの隔離パスと test 用 env baseline を先に与えます。実 provider
  secret（`GEMINI_API_KEY` など）は明示的に環境から取り除かれます。
- Python 依存はプロジェクト標準どおり `uv` で管理します。`uv sync --all-extras --dev`
  が入れるのは `pantaray-agents` と `pantaray-llm` だけで、`pantaray_cloud` /
  `supabase` / `boto3` は入りません。ここで import できてしまう変更は、デスクトップ
  同梱ランタイムの依存が増えたということです。

## 3. ディレクトリ構成

テストの置き場は 3 つあります。`tests/unit` と `tests/ws` と
`tests/integration` です。

| パス | 主な対象 | 補足 |
|---|---|---|
| `tests/unit/agents/test_action_agent_*.py` | Action Agent 本体 | Supervisor フロー、予算、キャンセル、出力形式 |
| `tests/unit/agents/action_agent/tools/*.py` | Action Agent 内部ツール | `fetch`、`memory_search`、`act_step` など |
| `tests/unit/agents/action_agent/conftest.py` | Action Agent 最小フィクスチャ | `MockActionAgentRepository` と `MockLLMClient` を束ねる |
| `tests/unit/agents/action_agent/fixtures.py` | Action Agent 共通ヘルパー | `create_state`、`base_state` など |
| `tests/unit/agents/suggestion_agent/*.py` | Suggestion Agent | `test_core.py`、`test_context.py`、`test_llm.py` に分割済み |
| `tests/unit/agents/test_*.py` | Agents 共通・個別機能 | Base/Insight/Fact Structuring、step counter、schema、tool runtime など |
| `tests/unit/local_runtime/*.py` | ローカルランタイム部品 | worker、control socket、scheduler、broker、tooling |
| `tests/unit/orchestration/*.py` | Orchestration / queue | heartbeat、process store、batching、停止連携 |
| `tests/unit/test_dependencies.py` | dependency injection | ローカル設定モジュールの読み込み |
| `tests/ws/handshake_resume/*.py` | WS handshake / resume | ローカル API トークンと owner 束縛の handshake 契約 |
| `tests/integration/test_main_api.py` | HTTP 統合 | internal-first API の疎通、mock mode 前提の検証 |
| `tests/integration/test_ws_orchestration_basic.py` | WebSocket 統合 | セッション開始、イベント配送、停止の基本シナリオ |
| `tests/integration/test_action_conversation_v2.py` | Action 会話の投影 | run/entry の並び、public 履歴、停止と再開 |
| `tests/integration/test_local_runtime_*.py` | ローカルランタイム配線 | ジョブ pipeline、artifact 契約、WS への中継 |
| `tests/integration/local_runtime/*.py` | command sandbox | 実プロセス・実 toolchain・macOS seatbelt を使う |

`tests/ws/handshake_resume/shared.py` は app ハーネスを
`tests/integration/ws_orchestration_test_helpers.py` から import します。WS の app
ハーネスはこの 1 つだけです。2 つ目のコピーを作らないでください。

### 3.1 どの CI ジョブが回すか

| スイート | 回る場所 |
|---|---|
| `tests/unit`、`tests/ws`、`tests/integration`（`local_runtime` を除く） | CI (backend) の `unit` ジョブ（ubuntu、`pantaray-cloud` を入れない環境）。`scripts/ci/run_local_ci.py` の `backend` も同じ行を回す |
| `tests/integration/local_runtime` | E2E (desktop) の macOS ジョブ。`/usr/bin/sandbox-exec` と実 toolchain が要るため ubuntu では回せない |

CI で回らないテストは壊れても気づけません。新しいスイートを増やすときは、上の
どれで回るかを決めてから置き場を選んでください。

## 4. 主要コードパスと対応テスト

### 4.1 Action Agent 本体

主なコードパス:

- `src/pantaray_agents/agents/action_agent/`
- `src/pantaray_agents/agents/action_agent/runtime/handlers/nodes/executing.py`
- `src/pantaray_agents/agents/action_agent/runtime/graph.py`

代表テスト:

- `tests/unit/agents/test_action_agent.py`
- `tests/unit/agents/test_action_agent_parent_tool_surface.py`
- `tests/unit/agents/test_action_agent_step_budget_fail_closed.py`
- `tests/unit/agents/test_action_agent_cancellation_guard.py`

確認していること:

- init ノードが planning phase を経由せず `phase=executing` の ReAct loop を直接開始すること
- checkpoint が `planning / executing / finalizing` だけを受理し、旧 node 名を phase として受理しないこと
- `planning` は退役済み orchestration の legacy checkpoint 互換としてのみ残り、その checkpoint の resume は typed に拒否されること
- ステップ予算、トークン予算、キャンセルが fail-closed で処理されること

### 4.2 Action Agent 内部ツール

主なコードパス:

- `src/pantaray_agents/agents/action_agent/runtime/handlers/tools.py`
- `src/pantaray_agents/agents/action_agent/tools/`

代表テスト:

- `tests/unit/agents/action_agent/tools/test_fetch.py`
- `tests/unit/agents/action_agent/tools/test_memory_search.py`
- `tests/unit/agents/action_agent/tools/test_act_step.py`
- `tests/unit/agents/action_agent/tools/test_brokered_tool_input_schema.py`

確認していること:

- `history_fetch` が UUID ではなく短縮 ID の `refs` 配列を受け付けること
- `ToolValidationError` が LLM 自己修復に使える形で返ること

### 4.3 Suggestion / Insight / Memory

主なコードパス:

- `src/pantaray_agents/agents/suggestion_agent/`
- `src/pantaray_agents/agents/insight_agent/`
- `src/pantaray_agents/agents/memory_agent/`

代表テスト:

- `tests/unit/agents/suggestion_agent/test_core.py`
- `tests/unit/agents/suggestion_agent/test_context.py`
- `tests/unit/agents/suggestion_agent/test_llm.py`
- `tests/unit/tasks/test_memory_update_job_run.py`

### 4.4 起動・依存注入・Orchestration

主なコードパス:

- `src/pantaray_agents/entrypoints/main_local.py`
- `src/pantaray_agents/app/local_app.py`
- `src/pantaray_agents/dependencies.py`
- `src/pantaray_agents/orchestration/`

代表テスト:

- `tests/unit/test_dependencies.py`
- `tests/unit/orchestration/*.py`
- `tests/ws/handshake_resume/*.py`
- `tests/integration/test_main_api.py`
- `tests/integration/test_ws_orchestration_basic.py`

確認していること:

- mock mode での起動配線
- router 依存解決と internal API 認証
- WS のイベント配送、heartbeat、停止処理
- 外部依存を使わない最小統合シナリオ

### 4.5 command sandbox

主なコードパス:

- `src/pantaray_agents/local_runtime/tooling/sandbox/`
- `src/pantaray_agents/local_runtime/tooling/brokering/`

代表テスト:

- `tests/integration/local_runtime/test_command_sandbox_*.py`
- `tests/integration/local_runtime/test_action_workspace_tools.py`

確認していること:

- workspace の外へ出る読み書き、exec、ネットワークが seatbelt で遮断されること
- timeout・出力量・一時領域の上限が terminal outcome と audit に落ちること
- Stop が実プロセスを確実に reap すること

このスイートは実プロセスを起動し、`/usr/bin/sandbox-exec` と `/usr/bin/cc` を使います。
どちらも無い環境では各ファイルの `pytestmark` が skip します。ネットワークは
loopback だけで、外部へは出ません。

## 5. 共有フィクスチャの使い分け

### 5.1 Action Agent 系

`tests/unit/agents/action_agent/fixtures.py` を共通入口として使います。

主なヘルパー:

- `create_state()`: Action Agent runtime テスト用の `ActionAgentState` を生成
- `make_goal()`: Goal 状態を簡潔に組み立てる
- `make_req()`: Requirement 状態を簡潔に組み立てる
- `base_state()`: tool テスト用の最小 state を生成
- `seed_action_header()`: DB 相当の action header を準備

この分離により、`conftest.py` を `from conftest import ...` で横断参照して `sys.modules` 衝突を起こす問題を避けています。

### 5.2 Suggestion Agent 系

`tests/unit/agents/suggestion_agent/conftest.py` が次をまとめて提供します。

- 必須 env のパッチ
- `MockRepository.clear_data()` によるテスト間独立性の確保
- `MockSuggestionAgentRepository`
- `MockLLMClient`
- 最小プロンプトを差し込んだ `suggestion_agent`

### 5.3 エントリポイント / WS 統合系

`tests/integration/test_main_api.py` は `pantaray_agents.entrypoints.main_local` を
fixture の中で遅延 import し、その前に `USE_MOCKS` を固定します。`USE_MOCKS` や
`LOG_LEVEL` は `pantaray_agents.config_local_runtime` の module レベルで確定するため、
import 後に env を書き換えても遅いです。この順序を崩さないでください。

WS 系（`tests/integration/test_ws_orchestration_basic.py`、
`tests/integration/test_local_runtime_ws_e2e.py`、`tests/ws/handshake_resume/*.py`）は
app ハーネス側で env・mock・ローカル API トークン・logged-out owner をまとめて用意します。
テスト側で組み直さず、ハーネスを使ってください。

### 5.4 ローカルストアの所有者

ローカル runtime の起動は `register_logged_out_owner()` でストアの所有者を
プロセスに登録します。ジョブ経路の identity 解決（`runtime.route_identity`）は
サインイン中でもこの所有者を読むため、登録が無いテストは
`LocalOwnerUnavailableError` で落ちます。

`tests/integration/local_artifact_test_support.py` の `insert_user()` が起動と同じ
手順で登録し、同モジュールの `reset_local_store_owner` fixture が前後で解除します。
このプロセスグローバルをテスト間に持ち越さないでください。

### 5.5 時刻に依存する fixture

Activity Summary の window は period end から 24 時間で期限切れになります
（`runtime.activity_summary_execution.is_activity_summary_window_expired`）。固定の
カレンダー日付を書くと、その日付が 1 日古くなった時点でテストは黙って
「期限切れで canceled」経路の確認に変わります。`live_summary_window()` を使い、
Summary が `success` で終わったことまで表明してください。

## 6. 推奨コマンド

`agents` ディレクトリで実行します。

```bash
cd agents
uv sync --all-extras --dev
```

CI (backend) と同じ実行:

```bash
uv run pytest -q -n auto --dist loadfile \
  tests/unit tests/ws tests/integration \
  --ignore=tests/integration/local_runtime
```

command sandbox（macOS のみ。E2E (desktop) の macOS ジョブと同じ実行）:

```bash
uv run pytest -q tests/integration/local_runtime
```

Action Agent 本体だけ確認:

```bash
uv run pytest tests/unit/agents/test_action_agent.py -q
uv run pytest tests/unit/agents/test_action_agent_parent_executing_contract.py -q
```

内部ツールだけ確認:

```bash
uv run pytest tests/unit/agents/action_agent/tools/test_fetch.py -q
uv run pytest tests/unit/agents/action_agent/tools/test_act_step.py -q
```

HTTP / WS 統合確認:

```bash
uv run pytest tests/integration/test_main_api.py -q
uv run pytest tests/integration/test_ws_orchestration_basic.py -q
uv run pytest tests/ws -q
```

カバレッジ確認:

```bash
uv run pytest --cov=src/pantaray_agents --cov-report=term-missing
uv run pytest --cov=src/pantaray_agents --cov-report=html
```

Python ファイルを変更した場合の整形:

```bash
uv run ruff format .
```

## 7. 新しいテストを追加する指針

### 7.1 まず既存スイートへ寄せる

新規ファイルを増やす前に、同じ責務を扱う既存スイートがないか確認してください。

- Action Agent のメタ推論なら `tests/unit/agents/test_action_agent_*.py`
- tool の schema / validation / execution なら `tests/unit/agents/action_agent/tools/`
- Suggestion Agent は `test_core.py` / `test_context.py` / `test_llm.py` のどれか

### 7.2 追加時の観点

- 公開仕様が変わるなら正常系だけでなく fail-closed の異常系も足す
- LLM 出力を扱う箇所は repair loop の収束条件まで確認する
- エントリポイント / `dependencies.py` では import 順と env 固定を崩さない
- 3.1 のどちらの CI ジョブが回すかを決めてから置き場を選ぶ

### 7.3 変更に応じて更新すべき関連ドキュメント

次のような変更では、このガイド以外のドキュメント更新も検討してください。

- mock mode 起動手順の変更: 内部ドキュメントの `development/MOCK_MODE_SETUP.md`（repo 外）

## 8. よくある落とし穴

### 8.1 `USE_MOCKS` を import 後に設定してしまう

`USE_MOCKS` / `LOG_LEVEL` / `ALLOWED_ORIGINS` は `pantaray_agents.config_local_runtime`
（`pantaray_agents.config` が再 export する）の module レベルで確定します。
エントリポイントや router を import した後で env を書き換えても遅いです。
統合テストでは必ず import 前に env を固定してください。

### 8.2 `conftest.py` から直接ヘルパーを持ってくる

Action Agent 系の共有 helper は `tests/unit/agents/action_agent/fixtures.py` にあります。`conftest.py` 同士をまたいだ import は避けてください。

### 8.3 fetch 系ツールに `step_id` を渡してしまう

現行仕様では `history_fetch` は短縮 ID の `refs` 配列を使います。UUID や単一 `step_id` を受け付ける互換パスは前提にしません。

### 8.4 モックデータやプロセスグローバルがテスト間で残る

`MockRepository` 系は共有データストアを持つため、既存の `autouse` フィクスチャを活用し、必要に応じて明示的に `MockRepository.clear_data()` を使ってください。
desktop session / connection store / logged-out owner / ローカル API トークンも
プロセスグローバルです。登録した側が必ず解除してください。

### 8.5 CI が回さない場所にテストを置いてしまう

3.1 の表に無い場所へ置いたテストは CI で回りません。既存のどちらかのスイートへ
寄せてください。

## 9. 変更時チェックリスト

- 変更したコードパスに対応する既存テスト群を特定した
- 正常系と fail-closed の異常系を両方確認した
- Action Agent 系なら共有 helper を `fixtures.py` に寄せた
- エントリポイント / Orchestration 系なら env と import 順を確認した
- 追加したテストが 3.1 のどちらかの CI ジョブで回ることを確認した
- 仕様変更があれば関連アーキテクチャ文書も更新した
