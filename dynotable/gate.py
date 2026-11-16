"""Start rules for the DynoTable language server. No `sublime` import, so the unit tests run outside Sublime Text."""

from __future__ import annotations

from typing import AbstractSet, Callable, Mapping
import json
import os


def port_file_path(platform: str, env: Mapping[str, str], home: str) -> str:
    """The app's port file. `platform` is a `sublime.platform()` value: "osx", "windows" or "linux"."""
    # `dynotable-cli` reads the port file from this directory when it is set, so the gate must read the same file.
    custom = env.get("DYNOTABLE_USER_DATA_DIR")
    if custom:
        return os.path.join(custom, "lsp-port.json")
    if platform == "osx":
        return os.path.join(home, "Library", "Application Support", "DynoTable", "lsp-port.json")
    if platform == "windows":
        appdata = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        return os.path.join(appdata, "DynoTable", "lsp-port.json")
    config = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return os.path.join(config, "DynoTable", "lsp-port.json")


def app_running(
    path: str,
    exists: Callable[[str], bool],
    read: Callable[[str], str],
    pid_alive: Callable[[int], bool],
) -> bool:
    """True when the port file says the app serves. A file left behind by a killed app reads as not running."""
    if not exists(path):
        return False
    try:
        data = json.loads(read(path))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    port, token = data.get("port"), data.get("token")
    if not _is_int(port) or not isinstance(token, str) or not token:
        return False
    pid = data.get("pid")
    if pid is None:
        return True
    return _is_int(pid) and pid > 0 and pid_alive(pid)


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except OSError:
        # ESRCH and also EPERM (another user's process): PROTOCOL.md counts both as a stale file.
        return False
    return True


def _pid_alive_windows(pid: int) -> bool:
    # On Windows, os.kill(pid, 0) terminates the process. Never use it here.
    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def gate(
    first_start_pending: bool, app_running: bool, refused_windows: AbstractSet[int], window_id: int | None
) -> bool:
    """
    May a server start now in this window? Only the first start may launch a closed app.

    A refusal closes the gate only in its own window: a bad `.dynotable.json` in one project must not stop the
    healthy session of another window from taking new files.
    """
    return first_start_pending or (app_running and window_id not in refused_windows)


def recovery_step(attached: bool, refused: bool, starting: bool, app_running: bool) -> str:
    """
    What the view listener does when a DynoTable view gets focus: "skip", "wait" (check again later) or "check".

    While LSP starts a session in the window, a check would start a second one, and the first one would never be
    used or stopped. So it waits until that start ends.
    """
    if attached or refused:
        return "skip"
    if starting:
        return "wait"
    return "check" if app_running else "skip"


def start_command(base: list[str], first_start: bool) -> list[str]:
    """Only the first start may launch the app. A later start that the gate lets through by mistake still cannot."""
    return list(base) if first_start else [*base, "--no-launch"]


def latches_refusal(initialized: bool, app_running: bool) -> bool:
    """
    Does a session end mean the app refused us (signed out, for example)?

    A session that never initialized while the app still serves was refused. One that never initialized because
    the app went away was not: it must start again by itself when the app comes back.
    """
    return not initialized and app_running


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
