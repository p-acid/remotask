"""macOS launchd integration: plist rendering + launchctl wrappers."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from importlib import resources
from pathlib import Path

from jinja2 import Environment

DEFAULT_LABEL = "kr.mission-driven.remote-task"
_LABEL_RE = re.compile(r"^[a-zA-Z0-9._\-]+$")
_TEMPLATE_PKG = "remote_task"  # bundled via hatch.force-include


def validate_label(label: str) -> None:
    if not label or not _LABEL_RE.fullmatch(label):
        raise ValueError(
            f"invalid Label: {label!r}; expected reverse-domain "
            "(letters, digits, dot, dash, underscore)"
        )


def detect_environment() -> dict[str, str]:
    """Capture environment variables for the plist."""
    home = os.environ.get("HOME", str(Path.home()))
    env = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"),
        "HOME": home,
        "LANG": os.environ.get("LANG", "en_US.UTF-8"),
        "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME", str(Path(home) / ".config")),
        "XDG_DATA_HOME": os.environ.get(
            "XDG_DATA_HOME", str(Path(home) / ".local" / "share")
        ),
        "XDG_CACHE_HOME": os.environ.get("XDG_CACHE_HOME", str(Path(home) / ".cache")),
    }
    # Ensure `claude` directory is in PATH if installed locally.
    claude = shutil.which("claude")
    if claude:
        claude_dir = str(Path(claude).parent)
        if claude_dir not in env["PATH"].split(":"):
            env["PATH"] = claude_dir + ":" + env["PATH"]
    return env


def _load_template_text() -> str:
    pkg = resources.files("remote_task.templates")  # type: ignore[arg-type]
    return (pkg / "launchd.plist.j2").read_text(encoding="utf-8")


def render_plist(*, label: str, remote_task_path: str, env: dict[str, str]) -> str:
    validate_label(label)
    home = env.get("HOME", str(Path.home()))
    data_dir = env.get("XDG_DATA_HOME", str(Path(home) / ".local" / "share")) + "/remote-task"
    template_text = _load_template_text()
    j_env = Environment(autoescape=False)  # plist values escaped manually if needed
    template = j_env.from_string(template_text)
    return template.render(
        label=label,
        remote_task_path=remote_task_path,
        home=home,
        data_dir=data_dir,
        env=env,
    )


def launch_agents_dir() -> Path:
    """Resolve the LaunchAgents directory.

    Honors ``REMOTE_TASK_LAUNCH_AGENTS_DIR`` for testing; otherwise the
    standard user-level path is used.
    """
    override = os.environ.get("REMOTE_TASK_LAUNCH_AGENTS_DIR")
    if override:
        return Path(override)
    return Path.home() / "Library" / "LaunchAgents"


def plist_path(label: str = DEFAULT_LABEL) -> Path:
    return launch_agents_dir() / f"{label}.plist"


def _stub_log(op: str, plist: Path) -> bool:
    """If REMOTE_TASK_STUB_LAUNCHCTL_LOG is set, append a call entry and skip exec."""
    target = os.environ.get("REMOTE_TASK_STUB_LAUNCHCTL_LOG")
    if not target:
        return False
    with Path(target).open("a", encoding="utf-8") as f:
        f.write(f"{op} {plist}\n")
    return True


def launchctl_load(plist: Path) -> None:
    if _stub_log("load", plist):
        return
    subprocess.run(  # noqa: S603
        ["/bin/launchctl", "load", "-w", str(plist)],
        check=True,
    )


def launchctl_unload(plist: Path) -> None:
    if _stub_log("unload", plist):
        return
    subprocess.run(  # noqa: S603
        ["/bin/launchctl", "unload", "-w", str(plist)],
        check=False,  # idempotent
    )
