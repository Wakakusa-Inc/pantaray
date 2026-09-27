"""Brokered workspace bash tool definition."""

from __future__ import annotations

from pantaray_agents.local_runtime.tooling.brokering.broker_protocol import BashToolArgs

from .base import (
    ToolDefinition,
    ToolGuideSpec,
    ToolSpec,
    tool_execution_policy,
)
from .broker_tool_input_schema import (
    BrokerToolFieldPresentation,
    broker_tool_input_spec_from_model,
)

BASH_TOOL_FIELD_PRESENTATION = (
    BrokerToolFieldPresentation(
        name="command",
        prompt_type="string",
        description=(
            "Non-interactive shell command or script. "
            "Pipes, redirections, heredocs, environment assignments, "
            "and multiple commands are supported."
        ),
        llm_order=10,
    ),
    BrokerToolFieldPresentation(
        name="cwd",
        prompt_type="string",
        description=(
            "Set cwd to a workspace path.\n"
            "- Use the current workspace marker, an absolute local path "
            "under Workspace Roots in Workspace Path Rules, or a "
            "subdirectory under a registered workspace.\n"
            "- A cwd outside registered workspaces waits for the user to "
            "approve that one call; use one only when the user asked for "
            "that location.\n"
            "- Command path arguments are relative to cwd."
        ),
        llm_order=20,
    ),
    BrokerToolFieldPresentation(
        name="use_login_environment",
        prompt_type="boolean",
        description=(
            "Default false. Set true to run with the user's login environment "
            "(real HOME, Keychain, ssh-agent) so CLIs the user signed in to in "
            "their terminal work.\n"
            "- Use it when the command needs the user's sign-in or personal "
            "settings (for example gh, git commit/push or cloning a private "
            "repository, cloud CLIs), or when a normal run failed with an "
            "authentication error.\n"
            "- Writes stay limited to workspace folders and an approved cwd; "
            "keep clone and output paths there."
        ),
        llm_order=30,
    ),
)

BASH_TOOL = ToolDefinition.from_spec(
    ToolSpec(
        tool_id="bash",
        name="Bash",
        description=(
            "Run a non-interactive shell command or script in a workspace. "
            "Set cwd to the working directory; path arguments are relative to cwd."
        ),
        guide=ToolGuideSpec(
            what=(
                "Run workspace scripts, virtual-environment tools, tests, builds, "
                "and package commands with the installed shell and toolchains. "
                "Pipes, redirections, heredocs, and multiple commands are supported."
            ),
            when=(
                "Direct file content edits should normally go through apply_patch; "
                "commands that write files as their normal side effect are still "
                "command execution. Use list, glob, grep, or read for file discovery "
                "and inspection. For short waits, use sleep 10 or sleep 0.5, then "
                "check status in a separate call."
            ),
            pitfalls=(
                "Set cwd to a directory under Workspace Roots, or outside them only "
                "when the user asked for that location; '.' uses the current "
                "execution workspace and path arguments are relative to cwd. "
                "Use $TMPDIR for temporary files. TMPDIR, and HOME unless "
                "use_login_environment is set, are temporary and removed after "
                "this call. Commands and descendants follow the "
                "user's command network setting and workspace file permissions. "
                "This call waits for completion and has a finite execution timeout. "
                "Do not use interactive prompts, sudo, or background processes "
                "intended to survive this call. Shell startup files are not loaded."
            ),
        ),
        execution_policy=tool_execution_policy(
            intent_class="process_exec_local",
            required_capabilities=("process_exec_local",),
            default_timeout_ms=60_000,
        ),
        input_spec=broker_tool_input_spec_from_model(
            model=BashToolArgs,
            fields=BASH_TOOL_FIELD_PRESENTATION,
            description="Run a non-interactive workspace shell command or script.",
        ),
        output_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "exit_code": {"type": "integer"},
                "stdout": {"type": "string"},
                "stderr": {"type": "string"},
            },
            "required": ["status", "exit_code", "stdout", "stderr"],
            "additionalProperties": False,
        },
    )
)
