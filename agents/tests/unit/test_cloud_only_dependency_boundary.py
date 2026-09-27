"""Cloud 専用の配布物が、デスクトップ同梱コードへ漏れていないことを検査する。

`supabase` / `boto3` と `pantaray_cloud` は `pantaray-cloud` 配布物の持ち物で、
デスクトップに同梱するローカルランタイム（`pantaray-agents`）には入らない。
このスイートはこれらを入れない環境で走るので、実際に import されるモジュールなら
テストが落ちる。ただしどのテストからも import されないモジュールは素通りするため、
import 文の静的な参照をここで見る。取りこぼすと、同梱ランタイム
（`uv export --no-dev` で作る helper）だけが起動時に ModuleNotFoundError で落ちる。

逆向き（`pantaray_cloud` が `pantaray_agents` を import しない）は
`pantaray-cloud` 側の `tests/unit/test_cloud_import_boundary.py` が固定する。
"""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "pantaray_agents"

# `pantaray-cloud` が提供する配布物と、それが引き込むパッケージ。
_CLOUD_ONLY_DISTRIBUTIONS = (
    "boto3",
    "botocore",
    "gotrue",
    "pantaray_cloud",
    "postgrest",
    "realtime",
    "s3transfer",
    "storage3",
    "supabase",
    "supabase_auth",
    "supabase_functions",
    "supafunc",
)


def _imported_roots(tree: ast.AST) -> list[str]:
    roots: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.append(node.module.split(".")[0])
    return roots


def test_bundled_local_runtime_modules_do_not_import_cloud_only_distributions() -> None:
    offenders: dict[str, list[str]] = {}
    for path in sorted(_SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        found = sorted(
            {
                root
                for root in _imported_roots(tree)
                if root in _CLOUD_ONLY_DISTRIBUTIONS
            }
        )
        if found:
            offenders[path.relative_to(_SOURCE_ROOT).as_posix()] = found

    assert offenders == {}, (
        "これらは同梱ランタイムに入らない Cloud 専用の依存です。"
        f" pantaray-cloud 側へ移すか import をやめてください: {offenders}"
    )
