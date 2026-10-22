"""Talking to the small root helper through polkit.

The GUI never runs ``ip`` or ``resolvectl`` as root directly. It writes a tiny
JSON request, then calls ``pkexec /usr/libexec/devnet/devnet-helper <action>
<file>``. The helper validates every argument and supports only route and DNS
operations. Once "Enable Passwordless Mode" has been used, a polkit rule for
the current user makes those calls instant.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

from .shell import run, which

log = logging.getLogger(__name__)

HELPER = Path("/usr/libexec/devnet/devnet-helper")
POLKIT_RULE = Path("/etc/polkit-1/rules.d/50-devnet.rules")
MAX_REQUEST = 4_000_000


class PrivilegeError(RuntimeError):
    pass


def helper_path() -> Path:
    override = os.environ.get("DEVNET_HELPER")
    return Path(override) if override else HELPER


def helper_installed() -> bool:
    path = helper_path()
    return path.is_file() and os.access(path, os.X_OK)


def passwordless() -> bool:
    """True when the installed polkit rule grants *this* user the helper."""
    try:
        text = POLKIT_RULE.read_text(encoding="utf-8")
    except OSError:
        return False
    user = os.environ.get("USER") or ""
    if "org.freedesktop.policykit.exec" not in text or str(HELPER) not in text:
        return False
    if "org.devnet.helper" not in text and "DevNet" not in text:
        return False
    if not user:
        return True
    quoted = json.dumps(user)
    return f"subject.user !== {quoted}" in text or f"subject.user === {quoted}" in text


def helper_status() -> dict:
    """Ask the helper for backend information (works without root)."""
    path = helper_path()
    if not helper_installed():
        return {}
    result = run([str(path), "status"], timeout=5)
    if result.returncode != 0:
        return {}
    try:
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def _error_for(result) -> str:
    if result.returncode == 0:
        return ""
    if result.returncode == 126:
        return "Authentication was dismissed."
    if result.returncode == 127:
        return "Not authorized. Open DevNet and click “Enable Passwordless Mode”."
    if result.returncode == 125:
        return "Authorization failed."
    message = (result.stderr or result.stdout or "").strip().splitlines()
    if message:
        return message[-1][:500]
    return f"Privileged command failed (exit {result.returncode})."


def run_helper(action: str, payload: Optional[dict] = None, timeout: float = 240) -> str:
    """Run one helper action. Returns ``""`` on success, an error message otherwise."""
    path = helper_path()
    if not helper_installed():
        return (
            "DevNet's privileged helper is not installed. Install the package, or run "
            "“sudo ./linux/install.sh” from the source tree."
        )

    request_path: Optional[str] = None
    try:
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False)
            if len(data.encode("utf-8")) > MAX_REQUEST:
                return "Too many routes for one operation."
            descriptor, request_path = tempfile.mkstemp(prefix="devnet-request-", suffix=".json")
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(data)
            except Exception:
                os.close(descriptor)
                raise

        if os.geteuid() == 0:
            command = [str(path), action]
        else:
            pkexec = which("pkexec")
            if not pkexec:
                return "pkexec is missing. Install polkit (Debian: policykit-1, Fedora: polkit)."
            command = [pkexec, str(path), action]
        if request_path:
            command.append(request_path)

        result = run(command, timeout=timeout)
        error = _error_for(result)
        if error:
            log.warning("helper %s failed: %s", action, error)
        return error
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("helper call failed")
        return str(exc)
    finally:
        if request_path:
            try:
                os.unlink(request_path)
            except OSError:
                pass


def routes_apply(operations: list[dict]) -> str:
    if not operations:
        return ""
    return run_helper("routes-apply", {"ops": operations})


def dns_set(servers: list[str]) -> str:
    if servers:
        return run_helper("dns-set", {"servers": servers})
    return run_helper("dns-reset", {})


def dns_flush() -> str:
    return run_helper("dns-flush", {})


def enable_passwordless() -> str:
    import getpass

    user = getpass.getuser()
    if not user or user == "root":
        return "Run DevNet as your normal desktop user, not as root."
    return run_helper("enable-passwordless", {"user": user})


def disable_passwordless() -> str:
    return run_helper("remove-passwordless", {})
