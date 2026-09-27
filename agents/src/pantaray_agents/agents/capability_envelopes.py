from __future__ import annotations

ACTION_AGENT_CAPABILITY_ENVELOPE = "\n".join(
    (
        "- Analyze relevant user context, prior work, and available evidence.",
        "- Read and search files within authorized workspace scopes.",
        "- Research and extract information from the web.",
        "- Create or modify files and durable workspace artifacts within authorized scopes.",
        "- Run local commands and Python for implementation, data processing, tests, and verification.",
        "- Complete coherent multi-stage work before returning the final handoff.",
    )
)


__all__ = ["ACTION_AGENT_CAPABILITY_ENVELOPE"]
