from __future__ import annotations

from .dynotable_gate import app_running, gate, latches_refusal, pid_alive, port_file_path, start_command
from LSP.plugin import IsApplicableContext, LspPlugin, OnPreStartContext
from LSP.plugin.core.registry import windows
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
    refused = False

    @classmethod
    def is_applicable_async(cls, context: IsApplicableContext) -> bool:
        # LSP also calls this on the crash restart. It runs twice per registration, so no side effects here.
        if not super().is_applicable_async(context):
            return False
        return gate(cls.first_start_pending, _app_running(), cls.refused)

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

    def on_initialized_async(self) -> None:
        self.initialized = True

    def on_session_end_async(self, exit_code: int | None, exception: Exception | None) -> None:
        # A refused `initialize` ends here with (None, None), so the exit code tells nothing.
        if latches_refusal(self.initialized, _app_running()):
            type(self).refused = True


class DynotableRetryCommand(sublime_plugin.WindowCommand):
    """After a sign-in, or after the Editor integration is switched on."""

    def run(self) -> None:
        LspDynotablePlugin.refused = False
        if view := self.window.active_view():
            view.run_command("lsp_check_applicable", {"session_name": LspDynotablePlugin.name})


class DynotableViewListener(sublime_plugin.ViewEventListener):
    """
    Starts the server again when the app is back. LSP registers a view again only when it opens or when its own
    session ended; a view that never had a session needs this check.
    """

    def on_activated_async(self) -> None:
        syntax = self.view.syntax()
        selector = sublime.load_settings(f"{LspDynotablePlugin.name}.sublime-settings").get("selector")
        if not syntax or not isinstance(selector, str) or sublime.score_selector(syntax.scope, selector) <= 0:
            return
        if LspDynotablePlugin.refused:
            return
        listener = windows.listener_for_view(self.view)
        if listener is None:
            return
        if any(session.config.name == LspDynotablePlugin.name for session in listener.sessions_async()):
            return
        if _app_running():
            self.view.run_command("lsp_check_applicable", {"session_name": LspDynotablePlugin.name})
