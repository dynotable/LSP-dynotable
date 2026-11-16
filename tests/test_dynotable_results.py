import unittest

from dynotable_results import (
    Run,
    RunEvent,
    csv_text,
    grid_text,
    is_result,
    js_json,
    js_number,
    json_text,
    markdown_text,
    pick_lens,
    run_start,
    run_step,
    sort_order,
    summary,
)


def result(**overrides):
    base = {
        "columns": [],
        "rows": [],
        "returnedRows": 0,
        "totalRows": None,
        "truncated": False,
        "approximateBytes": 0,
        "elapsedMs": 5,
        "executedStatement": 'SELECT * FROM "t"',
        "effectiveRowCap": 500,
    }
    base.update(overrides)
    return base


def csv_of(cell):
    return csv_text(result(columns=["v"], rows=[{"v": cell}]))


def lens(start, end, command="dynotable.runStatement", uri="file:///q.dtsql"):
    """A lens in the `contract/code-lens.json` shape: a zero-width anchor, the statement range in the argument."""
    anchor = {"line": start[0], "character": 0}
    return {
        "range": {"start": anchor, "end": anchor},
        "command": {
            "title": "Run",
            "command": command,
            "arguments": [
                {
                    "uri": uri,
                    "range": {
                        "start": {"line": start[0], "character": start[1]},
                        "end": {"line": end[0], "character": end[1]},
                    },
                }
            ],
        },
    }


class SummaryTest(unittest.TestCase):
    def test_known_total(self):
        self.assertEqual(
            summary(result(returnedRows=3, totalRows=3, itemsScanned=150, elapsedMs=194)),
            "3 of 3 rows · 150 items scanned · 194 ms",
        )

    def test_null_total_says_row_for_one(self):
        self.assertEqual(summary(result(returnedRows=1)), "1 row · 5 ms")

    def test_null_total_says_rows_for_many(self):
        self.assertEqual(summary(result(returnedRows=2)), "2 rows · 5 ms")

    def test_truncated_with_total_shows_the_servers_cap(self):
        self.assertEqual(
            summary(result(returnedRows=3, totalRows=120, truncated=True, effectiveRowCap=3)),
            "3 of 120 rows · limited to 3 rows · 5 ms",
        )

    def test_truncated_without_total_says_unknown(self):
        # A null total is unknown: the returned count must not stand in for it.
        self.assertEqual(
            summary(result(returnedRows=3, truncated=True, effectiveRowCap=3, itemsScanned=150, elapsedMs=207)),
            "3 rows · limited to 3 rows, total unknown · 150 items scanned · 207 ms",
        )

    def test_float_fields_print_as_javascript_numbers(self):
        # Python's json reads `194.0` as a float; VS Code shows `194`.
        self.assertEqual(summary(result(returnedRows=2.0, elapsedMs=194.0)), "2 rows · 194 ms")


class JsNumberTest(unittest.TestCase):
    def test_small_exponent(self):
        self.assertEqual(js_number(1e-7), "1e-7")

    def test_last_plain_small_number(self):
        self.assertEqual(js_number(1e-6), "0.000001")

    def test_large_number_is_written_out(self):
        self.assertEqual(js_number(1e16), "10000000000000000")

    def test_exponent_from_1e21(self):
        self.assertEqual(js_number(1e21), "1e+21")

    def test_large_int_reads_as_a_double(self):
        self.assertEqual(js_number(10**21), "1e+21")

    def test_shortest_fraction(self):
        self.assertEqual(js_number(0.1), "0.1")

    def test_whole_float(self):
        self.assertEqual(js_number(1.0), "1")

    def test_negative_zero(self):
        self.assertEqual(js_number(-0.0), "0")

    def test_fraction_with_a_whole_part(self):
        self.assertEqual(js_number(1.5), "1.5")

    def test_negative(self):
        self.assertEqual(js_number(-5), "-5")

    def test_small_exponent_with_a_fraction(self):
        self.assertEqual(js_number(1.5e-7), "1.5e-7")


class JsJsonTest(unittest.TestCase):
    def test_numbers_at_depth_and_no_spaces(self):
        self.assertEqual(js_json([1e-7, 0.1]), "[1e-7,0.1]")

    def test_non_ascii_is_kept(self):
        self.assertEqual(js_json({"name": "é"}), '{"name":"é"}')


class GridTextTest(unittest.TestCase):
    def test_cell_kinds_and_control_characters(self):
        grid = result(
            columns=["k", "v", "n\x1bm"],
            rows=[
                {"k": "null", "v": None, "n\x1bm": "é"},
                {"k": "missing", "n\x1bm": "a\x7fb\x9bc"},
                {"k": "bool", "v": True, "n\x1bm": "x"},
                {"k": "tagged", "v": {"N": "1.10"}, "n\x1bm": "y"},
            ],
            returnedRows=4,
        )
        self.assertEqual(
            grid_text(grid, [0, 1, 2, 3]),
            "┌─────────┬──────────────┬─────────────┐\n"
            "│ k       │ v            │ n\\x1bm      │\n"
            "├─────────┼──────────────┼─────────────┤\n"
            "│ null    │ null         │ é           │\n"
            "│ missing │              │ a\\x7fb\\x9bc │\n"
            "│ bool    │ true         │ x           │\n"
            '│ tagged  │ {"N":"1.10"} │ y           │\n'
            "└─────────┴──────────────┴─────────────┘\n"
            "4 rows · 5 ms\n",
        )

    def test_numeric_column_is_right_aligned(self):
        grid = result(columns=["id", "qty"], rows=[{"id": "a", "qty": 5}, {"id": "b", "qty": 120}, {"id": "c"}], returnedRows=3)
        self.assertEqual(
            grid_text(grid, [0, 1, 2]),
            "┌────┬─────┐\n"
            "│ id │ qty │\n"
            "├────┼─────┤\n"
            "│ a  │   5 │\n"
            "│ b  │ 120 │\n"
            "│ c  │     │\n"
            "└────┴─────┘\n"
            "3 rows · 5 ms\n",
        )

    def test_column_with_a_boolean_is_not_numeric(self):
        # A boolean is not a number: the column is text, left-aligned, and sorts as text.
        grid = result(columns=["x"], rows=[{"x": 2}, {"x": 10}, {"x": True}], returnedRows=3)
        self.assertEqual(
            grid_text(grid, sort_order(grid, 0, False)),
            "┌──────┐\n│ x    │\n├──────┤\n│ 10   │\n│ 2    │\n│ true │\n└──────┘\n3 rows · 5 ms\n",
        )

    def test_line_breaks_and_tab_become_visible(self):
        grid = result(columns=["v"], rows=[{"v": "a\nb\tc\rd"}], returnedRows=1)
        self.assertEqual(
            grid_text(grid, [0]),
            "┌─────────┐\n│ v       │\n├─────────┤\n│ a⏎b⇥c␍d │\n└─────────┘\n1 row · 5 ms\n",
        )

    def test_no_columns_prints_the_summary_only(self):
        self.assertEqual(grid_text(result(), []), "0 rows · 5 ms\n")


class SortOrderTest(unittest.TestCase):
    grid = result(columns=["n"], rows=[{"n": 9}, {}, {"n": 10}, {"n": None}, {"n": 1}])

    def test_ascending_numbers_with_empty_cells_last(self):
        self.assertEqual(sort_order(self.grid, 0, False), [4, 0, 2, 1, 3])

    def test_descending_keeps_empty_cells_last(self):
        self.assertEqual(sort_order(self.grid, 0, True), [2, 0, 4, 1, 3])

    def test_text_column_sorts_as_text(self):
        grid = result(columns=["s"], rows=[{"s": "b"}, {"s": None}, {"s": "a"}])
        self.assertEqual(sort_order(grid, 0, False), [2, 0, 1])
        self.assertEqual(sort_order(grid, 0, True), [0, 2, 1])


class CsvTest(unittest.TestCase):
    def test_formula_starts_are_guarded(self):
        cases = [
            ("=x", "'=x"),
            ("+x", "'+x"),
            ("-x", "'-x"),
            ("@x", "'@x"),
            ("\tx", "'\tx"),
            ("\rx", "\"'\rx\""),
            ("\nx", "\"'\nx\""),
        ]
        for cell, expected in cases:
            with self.subTest(cell=cell):
                self.assertEqual(csv_of(cell), "v\r\n" + expected)

    def test_bypass_forms_are_guarded(self):
        # Each passes a loose "looks numeric" check.
        cases = [
            ("-1+1", "'-1+1"),
            ("+1)", "'+1)"),
            ("-2+cmd|'/C calc'!A0", "'-2+cmd|'/C calc'!A0"),
            ("-1.5abc", "'-1.5abc"),
            ("+1\n", "\"'+1\n\""),
            # Python's `$` matches before a final newline; JavaScript's does not.
            ("-1\n", "\"'-1\n\""),
            # Python's `\d` matches Arabic-Indic digits unless the pattern is ASCII.
            ("-٣", "'-٣"),
        ]
        for cell, expected in cases:
            with self.subTest(cell=cell):
                self.assertEqual(csv_of(cell), "v\r\n" + expected)

    def test_number_literals_are_not_guarded(self):
        self.assertEqual(csv_of("-12345678901.5"), "v\r\n-12345678901.5")
        self.assertEqual(csv_of("-1e5"), "v\r\n-1e5")

    def test_header_is_guarded_and_the_guard_comes_before_quoting(self):
        guarded = result(columns=['=HYPERLINK("x")', "b"], rows=[{"b": "=1,2"}])
        self.assertEqual(csv_text(guarded), "\"'=HYPERLINK(\"\"x\"\")\",b\r\n,\"'=1,2\"")

    def test_json_cell_and_comma_are_quoted(self):
        mixed = result(columns=["a", "b"], rows=[{"a": "=1+1", "b": {"qty": 1}}, {"a": "x,y", "b": "p\tq"}])
        self.assertEqual(csv_text(mixed), "a,b\r\n'=1+1,\"{\"\"qty\"\":1}\"\r\n\"x,y\",p\tq")


class JsonTextTest(unittest.TestCase):
    def test_bytes_of_javascript_pretty_json(self):
        rows = [{"b": 1e-7, "a": "é"}, {"a": {"x": [1e-7, "é"]}}]
        self.assertEqual(
            json_text(result(columns=["a", "b"], rows=rows)),
            "[\n"
            "  {\n"
            '    "a": "é",\n'
            '    "b": 1e-7\n'
            "  },\n"
            "  {\n"
            '    "a": {\n'
            '      "x": [\n'
            "        1e-7,\n"
            '        "é"\n'
            "      ]\n"
            "    }\n"
            "  }\n"
            "]",
        )

    def test_no_rows(self):
        self.assertEqual(json_text(result(columns=["a"])), "[]")

    def test_row_with_every_key_missing(self):
        self.assertEqual(json_text(result(columns=["a"], rows=[{}])), "[\n  {}\n]")


class MarkdownTextTest(unittest.TestCase):
    def test_backslash_before_pipe_and_line_breaks(self):
        grid = result(columns=["a|b"], rows=[{"a|b": "c\\|d\r\ne\nf"}])
        self.assertEqual(markdown_text(grid), "| a\\|b |\n| --- |\n| c\\\\\\|d e f |")


class PickLensTest(unittest.TestCase):
    def test_second_line_of_a_multi_line_statement(self):
        first, second = lens((0, 0), (1, 12)), lens((2, 0), (2, 9))
        self.assertIs(pick_lens([first, second], 1), first)

    def test_end_at_character_zero_does_not_hold_its_line(self):
        self.assertIsNone(pick_lens([lens((0, 0), (2, 0))], 2))

    def test_two_statements_on_one_row_pick_the_first(self):
        first, second = lens((0, 0), (0, 10)), lens((0, 11), (0, 20))
        self.assertIs(pick_lens([first, second], 0), first)

    def test_row_without_a_statement(self):
        self.assertIsNone(pick_lens([lens((0, 0), (0, 10)), lens((2, 0), (2, 10))], 1))

    def test_open_in_app_only(self):
        self.assertIsNone(pick_lens([lens((0, 0), (0, 10), command="dynotable.openInApp")], 0))

    def test_lens_without_arguments_is_skipped(self):
        bare = {"range": {}, "command": {"title": "Run", "command": "dynotable.runStatement"}}
        self.assertIsNone(pick_lens([bare], 0))

    def test_lens_whose_argument_has_no_range_is_skipped(self):
        # With no range, the app runs the whole document: Run at the cursor must never do that.
        whole = lens((0, 0), (0, 10))
        del whole["command"]["arguments"][0]["range"]
        self.assertIsNone(pick_lens([whole], 0))

    def test_malformed_range_is_skipped_and_the_next_lens_is_picked(self):
        broken, good = lens((0, 0), (0, 10)), lens((0, 0), (0, 10))
        broken["command"]["arguments"][0]["range"]["end"] = None
        self.assertIs(pick_lens([broken, good], 0), good)


class RunStartTest(unittest.TestCase):
    uri = "file:///q.dtsql"
    selection = {"start": {"line": 1, "character": 0}, "end": {"line": 1, "character": 9}}

    def test_selection_runs_as_it_is(self):
        self.assertEqual(
            run_start(self.uri, self.selection, False, 4), ({"uri": "file:///q.dtsql", "range": self.selection}, None)
        )

    def test_opensearch_without_a_selection_runs_the_whole_document(self):
        self.assertEqual(run_start(self.uri, None, True, 4), ({"uri": "file:///q.dtsql"}, None))

    def test_no_selection_finds_the_statement_on_the_cursor_row(self):
        self.assertEqual(run_start(self.uri, None, False, 4), ({"uri": "file:///q.dtsql"}, 4))


class IsResultTest(unittest.TestCase):
    def test_run_result(self):
        self.assertTrue(is_result(result(columns=["a"], rows=[{"a": 1}], returnedRows=1, itemsScanned=3)))

    def test_malformed_answers(self):
        cases = [
            ("null", None),
            ("no rows", {key: value for key, value in result().items() if key != "rows"}),
            # Null is an unknown total, but the key is required: the summary reads it.
            ("no totalRows", {key: value for key, value in result().items() if key != "totalRows"}),
            ("a column that is not a string", result(columns=[1])),
            ("a row that is not an object", result(columns=["a"], rows=[["x"]])),
            ("a number field that is text", result(elapsedMs="5")),
        ]
        for name, answer in cases:
            with self.subTest(name):
                self.assertFalse(is_result(answer))


class RunStepTest(unittest.TestCase):
    def test_cancel_then_a_new_run_ignores_the_old_answer(self):
        a, b = object(), object()
        state, action = run_step(None, RunEvent("start-execute", a))
        self.assertEqual(action, "send-execute")
        state, _ = run_step(state, RunEvent("sent", a, request_id=7))
        # The app's answer ends the run, with its own cancel message, so the run stays.
        state, action = run_step(state, RunEvent("cancel"))
        self.assertEqual(action, "cancel-request")
        self.assertEqual(state, Run(a, "execute", request_id=7, cancel_sent=True))
        state, action = run_step(state, RunEvent("cancel"))
        self.assertEqual((state, action), (None, "cancelled"))
        state, action = run_step(state, RunEvent("start-execute", b))
        self.assertEqual(action, "send-execute")
        state, action = run_step(state, RunEvent("answer", a))
        self.assertEqual((state, action), (Run(b, "execute"), None))

    def test_second_run_is_refused(self):
        a, b = object(), object()
        state, _ = run_step(None, RunEvent("start-lens", a))
        self.assertEqual(run_step(state, RunEvent("start-execute", b)), (Run(a, "lens"), "refuse"))

    def test_lens_found_sends_execute(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-lens", a))
        self.assertEqual(run_step(state, RunEvent("lens-found", a)), (Run(a, "execute"), "send-execute"))

    def test_no_lens_releases_the_guard(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-lens", a))
        self.assertEqual(run_step(state, RunEvent("lens-none", a)), (None, "no-lens"))

    def test_lens_error_releases_the_guard(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-lens", a))
        self.assertEqual(run_step(state, RunEvent("lens-error", a)), (None, "fail"))

    def test_cancel_during_lens_clears_and_the_late_lens_answer_sends_nothing(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-lens", a))
        state, action = run_step(state, RunEvent("cancel"))
        self.assertEqual((state, action), (None, "cancelled"))
        self.assertEqual(run_step(state, RunEvent("lens-found", a)), (None, None))

    def test_session_end_releases_the_guard_and_asks_for_the_stopped_message(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-execute", a))
        self.assertEqual(run_step(state, RunEvent("session-end")), (None, "stopped"))

    def test_session_end_without_a_run_writes_nothing(self):
        self.assertEqual(run_step(None, RunEvent("session-end")), (None, None))

    def test_answer_releases_the_guard(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-execute", a))
        self.assertEqual(run_step(state, RunEvent("answer", a)), (None, "render"))

    def test_cancel_before_execute_was_sent_clears_and_sends_no_cancel_request(self):
        # There is no request id yet, so a `$/cancelRequest` would have no id.
        a = object()
        state, _ = run_step(None, RunEvent("start-execute", a))
        self.assertEqual(run_step(state, RunEvent("cancel")), (None, "cancelled"))

    def test_execute_error_releases_the_guard(self):
        a = object()
        state, _ = run_step(None, RunEvent("start-execute", a))
        self.assertEqual(run_step(state, RunEvent("error", a)), (None, "fail"))


if __name__ == "__main__":
    unittest.main()
