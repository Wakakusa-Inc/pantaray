"""Read-only installation roots; user data still requires workspace authority."""

from __future__ import annotations

import os
from pathlib import Path


def app_python_runtime_root(executable: Path) -> Path:
    executable = executable.resolve()
    for parent in executable.parents:
        if parent.suffix == ".framework":
            return parent
    # The bundled standalone Python owns bin/ and lib/ under the same prefix.
    return (
        executable.parent.parent
        if executable.parent.name == "bin"
        else executable.parent
    )


def toolchain_read_roots() -> list[str]:
    home = Path.home()
    rustup = Path(os.environ.get("RUSTUP_HOME", str(home / ".rustup")))
    roots = [
        Path("/Library/Developer/CommandLineTools"),
        Path("/Applications/Xcode.app"),
        Path("/Library/Preferences/com.apple.dt.Xcode.plist"),
        Path("/Library/Preferences/com.apple.dt.CommandLineTools.plist"),
        Path("/private/var/db/xcode_select_link"),
        home / ".nvm/versions/node",
        home / ".cargo/bin",
        rustup,
        # actions/setup-node installs Node and npm here on macOS runners.
        # The runtime (including npm's JS files) must be readable in Seatbelt.
        Path("/Users/runner/hostedtoolcache/node"),
    ]
    # Homebrew's etc/ and user package credentials are not runtime installation data.
    for prefix in (Path("/opt/homebrew"), Path("/usr/local")):
        roots.extend(
            prefix / name
            for name in (
                "Cellar",
                "opt",
                "bin",
                "sbin",
                "lib",
                "share",
                "include",
                "Frameworks",
            )
        )
    return list(dict.fromkeys(str(path.resolve()) for path in roots if path.exists()))
