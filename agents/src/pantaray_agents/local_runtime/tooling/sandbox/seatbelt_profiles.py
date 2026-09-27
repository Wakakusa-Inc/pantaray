from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .command_sandbox_protocol import BrokerToSandboxCommandRequest

PROFILE_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "seatbelt_profile_templates"
    / "seatbelt_command.sbpl"
)
MACOS_SYSTEM_RUNTIME_READ_ROOTS: tuple[str, ...] = (
    "/System",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/private/var/select",
    "/private/etc/ssl/openssl.cnf",
    "/private/etc/ssl/cert.pem",
    "/usr/lib",
    "/usr/share",
    "/private/var/db/dyld",
)
PLACEHOLDER_START = "{{"
PLACEHOLDER_END = "}}"


def render_seatbelt_profile(
    request: BrokerToSandboxCommandRequest,
) -> str:
    template = PROFILE_TEMPLATE_PATH.read_text(encoding="utf-8")
    network_clause = _render_network_clause(request)
    replacements = {
        "{{NETWORK_CLAUSE}}": network_clause,
        "{{PATH_ANCESTOR_CLAUSES}}": _render_clause_block(
            f'    (path-ancestors "{_escape_seatbelt_string(path)}")'
            for path in (
                *MACOS_SYSTEM_RUNTIME_READ_ROOTS,
                *request.real_read_roots,
                *request.runtime_read_roots,
                request.app_runtime_root,
            )
            # sandbox-exec rejects the profile when "/" has no ancestors to list.
            if path != "/"
        ),
        "{{SYSTEM_RUNTIME_READ_ROOTS}}": _render_system_runtime_read_roots(),
        "{{RUNTIME_READ_ROOT_CLAUSES}}": (
            _render_runtime_read_root_clauses(request.runtime_read_roots)
        ),
        "{{FILE_READ_ROOT_CLAUSES}}": _render_file_read_root_clauses(request),
        "{{FILE_WRITE_ROOT_CLAUSES}}": _render_file_write_root_clauses(request),
        "{{ACTION_PLAN_READ_DENY}}": _render_action_plan_deny(request, "file-read*"),
        "{{ACTION_PLAN_WRITE_DENY}}": _render_action_plan_deny(request, "file-write*"),
        "{{PRIVATE_STORAGE_DENY_RULES}}": _render_private_storage_deny_rules(request),
        "{{LOGIN_ENVIRONMENT_CLAUSE}}": _render_login_environment_clause(request),
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    if PLACEHOLDER_START in rendered or PLACEHOLDER_END in rendered:
        raise RuntimeError("seatbelt profile contains an unresolved placeholder")
    return rendered


def _render_system_runtime_read_roots() -> str:
    return "\n".join(
        _render_subpath_clause(root) for root in MACOS_SYSTEM_RUNTIME_READ_ROOTS
    )


def _render_runtime_read_root_clauses(paths: list[str]) -> str:
    return _render_clause_block(_render_subpath_clause(path) for path in paths)


def _render_file_read_root_clauses(request: BrokerToSandboxCommandRequest) -> str:
    roots = (
        *request.real_read_roots,
        request.app_runtime_root,
    )
    return _render_clause_block(_render_subpath_clause(path) for path in roots)


def _render_file_write_root_clauses(request: BrokerToSandboxCommandRequest) -> str:
    return _render_clause_block(
        _render_subpath_clause(path) for path in request.real_write_roots
    )


def _render_action_plan_deny(
    request: BrokerToSandboxCommandRequest, operation: str
) -> str:
    # An empty filter list would deny the operation everywhere, so a request
    # without an Action plan renders no statement at all.
    if request.action_storage is None:
        return ""
    plan_path = request.action_storage.plan_path
    clauses = _render_clause_block(
        (_render_literal_clause(plan_path), _render_subpath_clause(plan_path))
    )
    return f"(deny {operation}\n{clauses}\n)"


def _render_private_storage_deny_rules(request: BrokerToSandboxCommandRequest) -> str:
    private_roots = _render_clause_block(
        _render_subpath_clause(path) for path in request.private_storage_roots
    )
    storage = request.action_storage
    if storage is None:
        return (
            f"(deny file-read* (require-any\n{private_roots}\n))\n"
            f"(deny file-write* (require-any\n{private_roots}\n))"
        )
    workspace = _render_subpath_clause(storage.workspace_root)
    results = _render_subpath_clause(storage.published_results_root)
    # Exceptions remove this deny only; the ordinary read/write roots still apply.
    return (
        f"(deny file-read* (require-all (require-any\n{private_roots}\n) "
        f"(require-not (require-any\n{workspace}\n{results}\n))))\n"
        f"(deny file-write* (require-all (require-any\n{private_roots}\n) "
        f"(require-not\n{workspace}\n)))"
    )


def _render_login_environment_clause(request: BrokerToSandboxCommandRequest) -> str:
    if not request.use_login_environment:
        return ""
    # CLIs read their stored sign-ins through the Keychain service.
    clauses = ['(allow mach-lookup (global-name "com.apple.SecurityServer"))']
    ssh_agent_socket = request.env.get("SSH_AUTH_SOCK")
    if ssh_agent_socket is not None:
        # Rendered after the network clause so an offline command can still sign.
        socket_path = _escape_seatbelt_string(str(Path(ssh_agent_socket).resolve()))
        clauses.append(f'(allow network-outbound (literal "{socket_path}"))')
    return "\n".join(clauses)


def _render_literal_clause(path: str) -> str:
    return f'    (literal "{_escape_seatbelt_string(path)}")'


def _render_subpath_clause(path: str) -> str:
    return f'    (subpath "{_escape_seatbelt_string(path)}")'


def _render_clause_block(clauses: Iterable[str]) -> str:
    return "\n".join(dict.fromkeys(str(clause) for clause in clauses))


def _escape_seatbelt_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _render_network_clause(request: BrokerToSandboxCommandRequest) -> str:
    if request.network_policy == "deny":
        return "(deny network*)"
    protected = _escape_seatbelt_string(request.protected_backend_address)
    return (
        "(deny network*)\n"
        "(system-network)\n"
        '(allow network-outbound (literal "/private/var/run/mDNSResponder"))\n'
        '(allow network-outbound (remote tcp "*:*") (remote udp "*:*"))\n'
        '(allow network-bind (local ip "localhost:*"))\n'
        '(allow network-inbound (local tcp "localhost:*") (local udp "localhost:*"))\n'
        f'(deny network-outbound (remote tcp "{protected}"))'
    )
