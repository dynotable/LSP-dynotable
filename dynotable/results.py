"""Results text and run state for the DynoTable panel. No `sublime` import, so the unit tests run outside Sublime Text."""

from __future__ import annotations

from typing import Any, Dict, Mapping, NamedTuple
import json
import re

Row = Dict[str, Any]
Result = Dict[str, Any]
CommandArgs = Dict[str, Any]

RUN_COMMAND = "dynotable.runStatement"

_NAMED = {"\n": "⏎", "\t": "⇥", "\r": "␍"}
_CONTROL = re.compile("[\x00-\x1f\x7f-\x9f]")
_NUMBER = re.compile(r"-?\d+(\.\d+)?([eE][+-]?\d+)?", re.ASCII)
_FORMULA_START = "=+-@\t\r\n"
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def visible(text: str) -> str:
    """`text` with every C0 and C1 control character and DEL made visible, so data cannot break the grid."""
    return _CONTROL.sub(lambda m: _NAMED.get(m.group(), f"\\x{ord(m.group()):02x}"), text)


def js_number(value: float) -> str:
    """
    JavaScript's `String(n)`. JSON gives VS Code a double, so an int is read as one too.

    The app writes its answer with `JSON.stringify`, so no value is NaN, Infinity or out of the double range.
    """
    x = float(value)
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    # `repr` gives the shortest digits that read back as the same double, as JavaScript does; only the layout differs.
    mantissa, _, exponent = repr(abs(x)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    all_digits = whole + fraction
    digits = all_digits.lstrip("0")
    # The value is 0.<digits> times 10 to the power `point`.
    point = len(whole) + int(exponent or 0) - (len(all_digits) - len(digits))
    digits = digits.rstrip("0")
    k = len(digits)
    if k <= point <= 21:
        return sign + digits + "0" * (point - k)
    if 0 < point <= 21:
        return sign + digits[:point] + "." + digits[point:]
    if -6 < point <= 0:
        return sign + "0." + "0" * -point + digits
    e = point - 1
    exp = "e" + ("+" if e >= 0 else "-") + str(abs(e))
    return sign + (digits if k == 1 else digits[0] + "." + digits[1:]) + exp


def _string(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def js_json(value: Any) -> str:
    """
    JavaScript's `JSON.stringify(value)`. The keys keep their order: the app's `JSON.stringify` already put them in
    the order of a JavaScript object.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return js_number(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, list):
        return "[" + ",".join(js_json(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(_string(key) + ":" + js_json(value[key]) for key in value) + "}"
    raise TypeError(f"Not a JSON value: {value!r}")


def _js_pretty(value: Any, indent: str) -> str:
    """JavaScript's `JSON.stringify(value, null, 2)`, with `indent` before every line after the first."""
    inner = indent + "  "
    if isinstance(value, list) and value:
        items = ",\n".join(inner + _js_pretty(item, inner) for item in value)
        return "[\n" + items + "\n" + indent + "]"
    if isinstance(value, dict) and value:
        members = ",\n".join(
            inner + _string(key) + ": " + _js_pretty(value[key], inner) for key in value
        )
        return "{\n" + members + "\n" + indent + "}"
    return js_json(value)


def _cell(row: Row, column: str) -> tuple[str, str]:
    """`cellKind` of VS Code's grid: the text and the kind ("missing", "null", "number", "string" or "json")."""
    if column not in row:
        return "", "missing"
    value = row[column]
    if value is None:
        return "null", "null"
    # Before the number check: `isinstance(True, int)` is true.
    if isinstance(value, bool):
        return ("true" if value else "false"), "string"
    if isinstance(value, (int, float)):
        return js_number(value), "number"
    if isinstance(value, str):
        return value, "string"
    return js_json(value), "json"


def cell_text(row: Row, column: str) -> str:
    return _cell(row, column)[0]


def _is_empty(kind: str) -> bool:
    return kind in ("missing", "null")


def _is_numeric(kinds: list[str]) -> bool:
    return all(_is_empty(kind) or kind == "number" for kind in kinds)


def summary(result: Result) -> str:
    """`totalRows` null means unknown: the returned count never stands in for it."""
    returned = result["returnedRows"]
    total = result["totalRows"]
    if total is None:
        parts = [f"{js_number(returned)} {'row' if returned == 1 else 'rows'}"]
    else:
        parts = [f"{js_number(returned)} of {js_number(total)} rows"]
    if result["truncated"]:
        cap = js_number(result["effectiveRowCap"])
        parts.append(f"limited to {cap} rows" + (", total unknown" if total is None else ""))
    if result.get("itemsScanned") is not None:
        parts.append(f"{js_number(result['itemsScanned'])} items scanned")
    parts.append(f"{js_number(result['elapsedMs'])} ms")
    return " · ".join(parts)


def grid_text(result: Result, order: list[int]) -> str:
    """
    The panel text: a box table with the header and one line per row in `order` (row indices), then the summary.

    Every table line starts with a box character and the summary never does, so the syntax can find the header and
    the summary whatever the data holds. Cells are never cut: the panel does not wrap and scrolls sideways.
    Numeric columns are right-aligned.
    """
    columns = result["columns"]
    if not columns:
        return summary(result) + "\n"
    names = [visible(column) for column in columns]
    cells = [[_cell(row, column) for row in result["rows"]] for column in columns]
    numeric = [_is_numeric([kind for _, kind in column]) for column in cells]
    texts = [[visible(text) for text, _ in column] for column in cells]
    widths = [max([len(name)] + [len(text) for text in column]) for name, column in zip(names, texts)]

    def border(left: str, middle: str, right: str) -> str:
        return left + middle.join("─" * (width + 2) for width in widths) + right

    def line(values: list[str], right: list[bool]) -> str:
        fitted = [v.rjust(w) if r else v.ljust(w) for v, w, r in zip(values, widths, right)]
        return "│ " + " │ ".join(fitted) + " │"

    lines = [border("┌", "┬", "┐"), line(names, [False] * len(columns)), border("├", "┼", "┤")]
    lines += [line([column[index] for column in texts], numeric) for index in order]
    lines += [border("└", "┴", "┘"), summary(result)]
    return "\n".join(lines) + "\n"


def sort_order(result: Result, column: int, descending: bool) -> list[int]:
    """Row indices sorted by one column, as VS Code's grid sorts: stable, empty cells last in both directions."""
    name = result["columns"][column]
    cells = [_cell(row, name) for row in result["rows"]]
    numeric = _is_numeric([kind for _, kind in cells])
    filled = [index for index, (_, kind) in enumerate(cells) if not _is_empty(kind)]
    empty = [index for index, (_, kind) in enumerate(cells) if _is_empty(kind)]

    def key(index: int) -> Any:
        text = cells[index][0]
        return float(text) if numeric else text

    return sorted(filled, key=key, reverse=descending) + empty


def _csv_field(text: str) -> str:
    # A spreadsheet runs a cell that starts with a formula character, unless it is a plain number. The guard comes
    # before the quoting. `fullmatch` and ASCII digits: JavaScript's `$` never matches before a final newline, and
    # its `\d` is ASCII only.
    if text and text[0] in _FORMULA_START and not _NUMBER.fullmatch(text):
        text = "'" + text
    if "," in text or '"' in text or "\r" in text or "\n" in text:
        return '"' + text.replace('"', '""') + '"'
    return text


def csv_text(result: Result) -> str:
    """Every row in query order, with the header. Lines end with CRLF; there is no final line break."""
    columns = result["columns"]
    lines = [columns] + [[cell_text(row, column) for column in columns] for row in result["rows"]]
    return "\r\n".join(",".join(_csv_field(text) for text in line) for line in lines)


def json_text(result: Result) -> str:
    """
    The bytes of `JSON.stringify(rows, null, 2)` for every row in query order: the columns in order, a missing key
    left out.
    """
    rows = result["rows"]
    if not rows:
        return "[]"
    objects = []
    for row in rows:
        members = [
            "    " + _string(column) + ": " + _js_pretty(row[column], "    ")
            for column in result["columns"]
            if column in row
        ]
        objects.append("  {\n" + ",\n".join(members) + "\n  }" if members else "  {}")
    return "[\n" + ",\n".join(objects) + "\n]"


def _markdown_cell(text: str) -> str:
    return _LINE_BREAK.sub(" ", text.replace("\\", "\\\\").replace("|", "\\|"))


def _markdown_line(texts: list[str]) -> str:
    return "| " + " | ".join(_markdown_cell(text) for text in texts) + " |"


def markdown_text(result: Result) -> str:
    columns = result["columns"]
    lines = [_markdown_line(columns), "| " + " | ".join("---" for _ in columns) + " |"]
    lines += [_markdown_line([cell_text(row, column) for column in columns]) for row in result["rows"]]
    return "\n".join(lines)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _statement_lines(lens: Any) -> tuple[int, int] | None:
    """The first and last line of a Run lens's statement, or `None` for another lens or a malformed one."""
    try:
        command = lens["command"]
        if command["command"] != RUN_COMMAND:
            return None
        statement = command["arguments"][0]["range"]
        start, end, character = statement["start"]["line"], statement["end"]["line"], statement["end"]["character"]
    except (KeyError, IndexError, TypeError):
        return None
    if not all(_is_int(value) for value in (start, end, character)):
        return None
    # An end at character 0 of a later line does not hold that line.
    return start, (end - 1 if character == 0 and end > start else end)


def pick_lens(lenses: list[Any], line: int) -> dict[str, Any] | None:
    """
    The first Run lens whose statement holds `line` (0-based). The statement range is in the lens's argument; the
    lens's own range is only an anchor.
    """
    for lens in lenses:
        lines = _statement_lines(lens)
        if lines is not None and lines[0] <= line <= lines[1]:
            return lens
    return None


def run_start(
    uri: str, selection: Mapping[str, Any] | None, opensearch: bool, row: int
) -> tuple[CommandArgs, int | None]:
    """
    What "DynoTable: Run Statement" runs: the `executeCommand` argument, and the cursor row (0-based) when the
    statement must first be found with `codeLens`, else `None`. `selection` is the selected range, or `None`.
    """
    if selection is not None:
        return {"uri": uri, "range": selection}, None
    if opensearch:
        return {"uri": uri}, None
    return {"uri": uri}, row


def is_result(answer: Any) -> bool:
    """Whether the `executeCommand` answer has the fields that the panel, Sort and Copy read."""
    if not isinstance(answer, dict):
        return False
    columns, rows = answer.get("columns"), answer.get("rows")
    return (
        isinstance(columns, list)
        and all(isinstance(column, str) for column in columns)
        and isinstance(rows, list)
        and all(isinstance(row, dict) for row in rows)
        and all(_is_number(answer.get(key)) for key in ("returnedRows", "elapsedMs", "effectiveRowCap"))
        and "totalRows" in answer
        and (answer["totalRows"] is None or _is_number(answer["totalRows"]))
        and (answer.get("itemsScanned") is None or _is_number(answer.get("itemsScanned")))
        and isinstance(answer.get("truncated"), bool)
    )


class Run(NamedTuple):
    """The active run of a window. `token` is a new object per run; `request_id` is the `executeCommand` id."""

    token: Any
    phase: str  # "lens": `codeLens` in flight. "execute": `executeCommand` in flight.
    request_id: int | None = None
    cancel_sent: bool = False


class RunEvent(NamedTuple):
    """
    What happened. `kind` is one of:

    - "start-lens" (the palette at the cursor: `codeLens` first), "start-execute" (a lens click, a selection, a
      whole `.opensearch` document): a new run with a new `token`;
    - "lens-found", "lens-none", "lens-error": the `codeLens` answer of `token`;
    - "sent": `executeCommand` of `token` went out with `request_id`;
    - "answer", "error": the `executeCommand` answer of `token`;
    - "cancel", "session-end": no token, they act on the active run.
    """

    kind: str
    token: object = None
    request_id: int | None = None


def run_step(state: Run | None, event: RunEvent) -> tuple[Run | None, str | None]:
    """
    The next run state and what the plugin must do, or `None` for nothing.

    Actions: "send-lens", "send-execute", "refuse" (a run is active), "no-lens", "render", "fail", "cancel-request"
    (send a raw `$/cancelRequest` for `state.request_id`, keep the run: the app's answer ends it), "cancelled",
    "stopped". An event of a run that is no longer the active one does nothing.
    """
    kind = event.kind
    if kind in ("start-lens", "start-execute"):
        if state is not None:
            return state, "refuse"
        if kind == "start-lens":
            return Run(event.token, "lens"), "send-lens"
        return Run(event.token, "execute"), "send-execute"
    if kind == "cancel":
        if state is None:
            return None, None
        if state.phase == "execute" and state.request_id is not None and not state.cancel_sent:
            return state._replace(cancel_sent=True), "cancel-request"
        return None, "cancelled"
    if kind == "session-end":
        return None, ("stopped" if state is not None else None)
    if state is None or event.token is not state.token:
        return state, None
    if kind == "lens-found" and state.phase == "lens":
        return Run(state.token, "execute"), "send-execute"
    if kind == "lens-none" and state.phase == "lens":
        return None, "no-lens"
    if kind == "lens-error" and state.phase == "lens":
        return None, "fail"
    if kind == "sent" and state.phase == "execute":
        return state._replace(request_id=event.request_id), None
    if kind == "answer" and state.phase == "execute":
        return None, "render"
    if kind == "error" and state.phase == "execute":
        return None, "fail"
    return state, None
