"""Pantaray Agents パッケージ。

このパッケージのトップレベル import（`import pantaray_agents`）は軽量に保つ。

理由:
    - import 時に重い依存（エージェント実装・リポジトリ等）を巻き込むと、
      実行時の副作用・起動遅延・循環参照の温床になる。
    - mypy の段階導入（対象を絞る）においても、トップレベルが重いと
      “対象外の実装コードまで” 型チェックに巻き込まれてしまう。
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
