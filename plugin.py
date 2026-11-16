from __future__ import annotations

from .dynotable_gate import app_running, gate, latches_refusal, pid_alive, port_file_path, recovery_step, start_command
from .dynotable_results import RUN_COMMAND, Run, RunEvent, csv_text, grid_text, is_result, json_text, markdown_text
from .dynotable_results import pick_lens, run_start, run_step, sort_order, visible
from LSP.plugin import Error, IsApplicableContext, LspPlugin, LspTextCommand, Notification, OnPreStartContext, Promise
from LSP.plugin import Request, command_handler, region_to_range, text_document_identifier
from lsp_utils import NodeManager
from pathlib import Path
from sublime_lib import ResourcePath
from typing import TYPE_CHECKING, Any, cast
import os
import shutil
import sublime
import sublime_plugin
import weakref

if TYPE_CHECKING:
    from LSP.plugin import Session
    from weakref import ref

try:
    # Not public API: only the view listener uses it. When a later LSP release moves it, recovery is off.
    from LSP.plugin.core.registry import windows
except ImportError:
    windows = None
    print("LSP-dynotable: LSP.plugin.core.registry.windows is gone; reopen a DynoTable file after starting the app")

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
        self.window = session.window if session else None
        self.window_id = self.window.id() if self.window else None

    def on_initialized_async(self) -> None:
        self.initialized = True

    @command_handler(RUN_COMMAND)
    def on_run_statement(self, arguments: list[Any] | None) -> Promise[None]:
        """The Run lens. It resolves `None` in every case: an `Error` makes LSP show "command failed" over the panel."""
        session = self.weaksession()
        if session is None or not arguments or not isinstance(arguments[0], dict):
            return Promise.resolve(None)
        if not isinstance(arguments[0].get("uri"), str):
            return Promise.resolve(None)
        return _start_async(_Token(session), arguments[0], None, None)

    def on_session_end_async(self, exit_code: int | None, exception: Exception | None) -> None:
        # LSP drops the handlers of the requests in flight without calling them, so the run ends here.
        if self.window_id is not None and _step(self.window_id, RunEvent("session-end")) == "stopped" and self.window:
            _write(self.window, "Run failed: the language server stopped.\n")
        # A refused `initialize` ends here with (None, None): the reason goes only to LSP's crash line in the console.
        if self.window and self.window_id is not None and latches_refusal(self.initialized, _app_running()):
            type(self).refused_windows.add(self.window_id)
            self.window.status_message(
                "DynoTable refused the connection. See the console, fix the cause, then run DynoTable: Retry Connection."
            )


_PANEL = "DynoTable Results"
_RUNNING = "A statement is running. Wait for it, or run DynoTable: Cancel Run."
_NO_LENS = "No statement at the cursor. A file with a syntax error has no runnable statements."
_NO_RESULT = "There are no results. Run a statement first."
_BAD_ANSWER = "DynoTable sent an answer that LSP-dynotable cannot read. Update LSP-dynotable and DynoTable."
_COPY = {"csv": ("CSV", csv_text), "json": ("JSON", json_text), "markdown": ("Markdown", markdown_text)}

# Per window id: the active run, and the last result, which Sort and Copy use.
_runs: dict[int, Run] = {}
_results: dict[int, dict[str, Any]] = {}


class _Token:
    """One run. A new object per run, so the answer of an older run can see that it is not the active run."""

    def __init__(self, session: Session) -> None:
        self.session = weakref.ref(session)
        self.window = session.window


def _step(window_id: int, event: RunEvent) -> str | None:
    """Applies `run_step` to the run of the window. Call it on the async thread only, so that no two steps overlap."""
    state, action = run_step(_runs.get(window_id), event)
    if state is None:
        _runs.pop(window_id, None)
    else:
        _runs[window_id] = state
    return action


def _write(window: sublime.Window, text: str) -> None:
    if not window.is_valid():
        return
    panel = window.create_output_panel(_PANEL)
    settings = panel.settings()
    settings.set("word_wrap", False)
    settings.set("gutter", False)
    panel.assign_syntax(f"Packages/{LspDynotablePlugin.name}/DynoTable Results.sublime-syntax")
    panel.run_command("dynotable_replace_panel", {"characters": text})
    window.run_command("show_panel", {"panel": f"output.{_PANEL}"})


class DynotableReplacePanelCommand(sublime_plugin.TextCommand):
    """Replaces the whole text of the read-only results panel, so a second run or a sort does not add to it."""

    def run(self, edit: sublime.Edit, characters: str = "") -> None:
        self.view.set_read_only(False)
        self.view.replace(edit, sublime.Region(0, self.view.size()), characters)
        self.view.set_read_only(True)


def _failure(message: str) -> str:
    return f"Run failed: {visible(message)}\n"


def _error_message(error: Error) -> str:
    # Not `str(error)`: it adds the error code.
    return str(error.args[0]) if error.args else ""


def _purge_async(session: Session, uri: str, view: sublime.View) -> None:
    """Sends the edits that LSP holds back (it debounces `didChange`), so that the run sees the text on screen."""
    try:
        buffer = session.get_session_buffer_for_uri_async(uri)
        # Not on `SessionBufferProtocol`: a later LSP release can remove it. Then a run can miss the last edit.
        purge = getattr(buffer, "purge_changes_async", None)
        if buffer and purge:
            purge(view)
        elif buffer:
            print("LSP-dynotable: SessionBuffer.purge_changes_async is gone; a run can miss the last edit")
    except Exception as ex:
        print(f"LSP-dynotable: a run can miss the last edit: {ex!r}")


def _start_async(token: _Token, args: dict[str, Any], line: int | None, view: sublime.View | None) -> Promise[None]:
    """
    Starts a run: `executeCommand` with `args`, or, when `line` (0-based) is given, first `codeLens` to find the
    statement on it. `view` is `None` for a lens click. The promise resolves `None` when the run ends.
    """
    session = token.session()
    window = token.window
    # A session that ends drops its requests without an answer, so a run on it would hold the guard until Cancel.
    if session is None or session.exiting:
        return Promise.resolve(None)
    if _step(window.id(), RunEvent("start-execute" if line is None else "start-lens", token)) == "refuse":
        window.status_message(_RUNNING)
        return Promise.resolve(None)
    _results.pop(window.id(), None)
    # Not for a lens click: its range is for the text that the server has, and a purge first can shift the text
    # under that range.
    if view is not None:
        _purge_async(session, args["uri"], view)
    if line is not None:
        return _send_lens_async(session, token, args["uri"], line)
    return _send_execute_async(session, token, args)


def _send_lens_async(session: Session, token: _Token, uri: str, line: int) -> Promise[None]:
    promise = session.send_request_task(Request("textDocument/codeLens", {"textDocument": {"uri": uri}}))
    return promise.then(lambda answer: _on_lenses_async(session, token, line, answer))


def _on_lenses_async(session: Session, token: _Token, line: int, answer: Any) -> Promise[None] | None:
    window_id = token.window.id()
    if isinstance(answer, Error):
        if _step(window_id, RunEvent("lens-error", token)) == "fail":
            _write(token.window, _failure(_error_message(answer)))
        return None
    lens = pick_lens(answer if isinstance(answer, list) else [], line)
    if lens is None:
        if _step(window_id, RunEvent("lens-none", token)) == "no-lens":
            token.window.status_message(_NO_LENS)
        return None
    if _step(window_id, RunEvent("lens-found", token)) != "send-execute":
        return None
    return _send_execute_async(session, token, lens["command"]["arguments"][0])


def _send_execute_async(session: Session, token: _Token, args: dict[str, Any]) -> Promise[None]:
    request = Request("workspace/executeCommand", {"command": RUN_COMMAND, "arguments": [args]})
    promise, request_id = session.send_request_task_2(request)
    _step(token.window.id(), RunEvent("sent", token, request_id))
    return promise.then(lambda answer: _on_answer_async(token, answer))


def _on_answer_async(token: _Token, answer: Any) -> None:
    window_id = token.window.id()
    if isinstance(answer, Error):
        if _step(window_id, RunEvent("error", token)) == "fail":
            _write(token.window, _failure(_error_message(answer)))
        return
    if _step(window_id, RunEvent("answer", token)) != "render":
        return
    if not is_result(answer):
        _write(token.window, _failure(_BAD_ANSWER))
        return
    _results[window_id] = answer
    _write(token.window, grid_text(answer, list(range(len(answer["rows"])))))


def _cancel_async(window: sublime.Window) -> None:
    window_id = window.id()
    state = _runs.get(window_id)
    action = _step(window_id, RunEvent("cancel"))
    if action == "cancel-request" and state is not None:
        # Not `cancel_request_async`: it ends the request here and drops the answer of the app, which says why.
        session = cast(_Token, state.token).session()
        if session:
            session.send_notification(Notification("$/cancelRequest", {"id": state.request_id}))
    elif action == "cancelled":
        _write(window, "Run cancelled.\n")
    elif action is None:
        window.status_message("There is no run to cancel.")


def _attach_async(view: sublime.View) -> None:
    # Not `lsp_check_applicable`: when that command has to start the session, LSP 2.16 attaches the view before
    # `initialize` returns, and the view never gets `didOpen`. LSP's listener queue attaches it after `initialize`.
    window = view.window()
    if window is None or not view.is_valid() or view.is_loading():
        return
    try:
        manager = windows.lookup(window) if windows else None
        listener = manager.listener_for_view(view) if manager else None
    except Exception as ex:
        print(f"LSP-dynotable: view recovery is off: {ex!r}")
        manager = listener = None
    if manager and listener:
        manager.register_listener_async(listener)
    else:
        print("LSP-dynotable: reopen the DynoTable file if it shows no diagnostics")
        view.run_command("lsp_check_applicable", {"session_name": LspDynotablePlugin.name})


class DynotableRetryCommand(sublime_plugin.WindowCommand):
    """After a sign-in, after the Editor integration is switched on, or after a fix of `.dynotable.json`."""

    def run(self) -> None:
        LspDynotablePlugin.refused_windows.discard(self.window.id())
        if view := self.window.active_view():
            sublime.set_timeout_async(lambda: _attach_async(view))


class DynotableRunCommand(LspTextCommand):
    """The selection, else the statement at the cursor. An OpenSearch file runs as a whole."""

    def run(self, edit: sublime.Edit, event: dict | None = None) -> None:
        session = self.session_by_name()
        if session is None:
            return
        view = self.view
        region = view.sel()[0] if len(view.sel()) else sublime.Region(0)
        syntax = view.syntax()
        args, line = run_start(
            text_document_identifier(view)["uri"],
            None if region.empty() else region_to_range(view, region),
            bool(syntax and syntax.scope == "source.opensearch"),
            view.rowcol(region.b)[0],
        )
        token = _Token(session)
        sublime.set_timeout_async(lambda: _start_async(token, args, line, view))


class DynotableSortResultsCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        result = _results.get(self.window.id())
        if not result or not result["columns"]:
            self.window.status_message(_NO_RESULT)
            return
        names = [visible(column) for column in result["columns"]]
        self.window.show_quick_panel(names, lambda column: self.on_column(result, column))

    def on_column(self, result: dict[str, Any], column: int) -> None:
        if column < 0:
            return
        # A quick panel opened from the callback of another one does not show; open it after this callback.
        sublime.set_timeout(
            lambda: self.window.show_quick_panel(
                ["Ascending", "Descending"], lambda choice: self.on_direction(result, column, choice)
            )
        )

    def on_direction(self, result: dict[str, Any], column: int, choice: int) -> None:
        # A run that ended while the quick panels were open replaced the result in the panel.
        if choice < 0 or _results.get(self.window.id()) is not result:
            return
        _write(self.window, grid_text(result, sort_order(result, column, choice == 1)))


class DynotableCopyResultsCommand(sublime_plugin.WindowCommand):
    """All rows in query order, also after a sort, with the bytes of the VS Code extension's copy."""

    def run(self, format: str = "csv") -> None:
        result = _results.get(self.window.id())
        if not result:
            self.window.status_message(_NO_RESULT)
            return
        name, text = _COPY[format]
        sublime.set_clipboard(text(result))
        self.window.status_message(f"Copied the results as {name}.")


class DynotableCancelRunCommand(sublime_plugin.WindowCommand):
    def run(self) -> None:
        window = self.window
        sublime.set_timeout_async(lambda: _cancel_async(window))


def _forget_async(window_id: int) -> None:
    _runs.pop(window_id, None)
    _results.pop(window_id, None)


class DynotableWindowListener(sublime_plugin.EventListener):
    def on_pre_close_window(self, window: sublime.Window) -> None:
        # `_runs` changes on the async thread only (see `_step`).
        window_id = window.id()
        sublime.set_timeout_async(lambda: _forget_async(window_id))


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
        except Exception as ex:
            # Not public API (see the import): when it changes, recovery is off and the rest still works.
            print(f"LSP-dynotable: view recovery is off: {ex!r}")
            return
        refused = window.id() in LspDynotablePlugin.refused_windows
        step = recovery_step(attached, refused, starting, _app_running())
        if step == "wait":
            self.waiting = True
            sublime.set_timeout_async(self.recover_async, _RECOVERY_WAIT_MS)
        elif step == "check":
            _attach_async(view)
