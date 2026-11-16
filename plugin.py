from __future__ import annotations

from .dynotable_gate import app_running, gate, latches_refusal, pid_alive, port_file_path, recovery_step, start_command
from LSP.plugin import IsApplicableContext, LspPlugin, OnPreStartContext
from lsp_utils import NodeManager
from pathlib import Path
from sublime_lib import ResourcePath
from typing import TYPE_CHECKING
import os
import shutil
import sublime
import sublime_plugin

if TYPE_CHECKING:
    from LSP.plugin import Session
    from weakref import ref

try:
    # Not public API: only the view listener uses it. When a later LSP release moves it, recovery is off.
    from LSP.plugin.core.registry import windows
except ImportError:
    windows = None

# Milliseconds between checks while LSP starts another session in the window.
_RECOVERY_WAIT_MS = 1000


def plugin_loaded() -> None:
    LspDynotablePlugin.register()


def plugin_unloaded() -> None:
    LspDynotablePlugin.unregister()


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _app_running() -> bool:
    path = port_file_path(sublime.platform(), os.environ, os.path.expanduser("~"))
    return app_running(path, os.path.isfile, _read, pid_alive)


class LspDynotablePlugin(LspPlugin):
    # Class state, shared by every window. Assign through `cls.` or `type(self).`, never `self.`.
    first_start_pending = True
    # Ids of the windows whose session the app refused. A refusal can be about one project only (a bad
    # `.dynotable.json`), so it must not close the gate in other windows.
    refused_windows: set[int] = set()

    @classmethod
    def is_applicable_async(cls, context: IsApplicableContext) -> bool:
        # LSP also calls this on the crash restart. It runs twice per registration, so no side effects here.
        if not super().is_applicable_async(context):
            return False
        window = context.view.window()
        return gate(cls.first_start_pending, _app_running(), cls.refused_windows, window.id() if window else None)

    @classmethod
    def on_pre_start_async(cls, context: OnPreStartContext) -> None:
        first = cls.first_start_pending
        cls.first_start_pending = False
        binary = shutil.which("dynotable-lsp")
        if binary:
            context.configuration.command = start_command([binary], first)
            return
        NodeManager.on_pre_start_async(
            context,
            cls.plugin_storage_path,
            ResourcePath("Packages", cls.name, "server"),
            Path("node_modules", "dynotable-cli", "bin", "dynotable-lsp.mjs"),
            node_version_requirement=">=18",
        )
        context.configuration.command = start_command(context.configuration.command, first)

    def __init__(self, weaksession: ref[Session]) -> None:
        super().__init__(weaksession)
        # Per session: with two windows, a shared flag would let one session's answer mark the other.
        self.initialized = False
        session = weaksession()
        self.window_id = session.window.id() if session else None

    def on_initialized_async(self) -> None:
        self.initialized = True

    def on_session_end_async(self, exit_code: int | None, exception: Exception | None) -> None:
        # A refused `initialize` ends here with (None, None), so the exit code tells nothing.
        if self.window_id is not None and latches_refusal(self.initialized, _app_running()):
            type(self).refused_windows.add(self.window_id)


class DynotableRetryCommand(sublime_plugin.WindowCommand):
    """After a sign-in, after the Editor integration is switched on, or after a fix of `.dynotable.json`."""

    def run(self) -> None:
        LspDynotablePlugin.refused_windows.discard(self.window.id())
        if view := self.window.active_view():
            view.run_command("lsp_check_applicable", {"session_name": LspDynotablePlugin.name})


class DynotableViewListener(sublime_plugin.ViewEventListener):
    """
    Starts the server again when the app is back. LSP registers a view again only when it opens or when its own
    session ended; a view that never had a session needs this check.
    """

    def __init__(self, view: sublime.View) -> None:
        super().__init__(view)
        self.waiting = False

    def on_activated_async(self) -> None:
        syntax = self.view.syntax()
        selector = sublime.load_settings(f"{LspDynotablePlugin.name}.sublime-settings").get("selector")
        if not syntax or not isinstance(selector, str) or sublime.score_selector(syntax.scope, selector) <= 0:
            return
        if not self.waiting:
            self.recover_async()

    def recover_async(self) -> None:
        self.waiting = False
        view = self.view
        window = view.window()
        if windows is None or window is None or not view.is_valid() or window.active_view() != view:
            return
        try:
            manager = windows.lookup(window)
            listener = manager.listener_for_view(view) if manager else None
            if manager is None or listener is None:
                return
            attached = any(session.config.name == LspDynotablePlugin.name for session in listener.sessions_async())
            starting = manager.is_session_starting()
        except Exception:
            # Not public API (see the import): when it changes, recovery is off and the rest still works.
            return
        refused = window.id() in LspDynotablePlugin.refused_windows
        step = recovery_step(attached, refused, starting, _app_running())
        if step == "wait":
            self.waiting = True
            sublime.set_timeout_async(self.recover_async, _RECOVERY_WAIT_MS)
        elif step == "check":
            view.run_command("lsp_check_applicable", {"session_name": LspDynotablePlugin.name})
