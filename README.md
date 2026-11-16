# LSP-dynotable

This package connects Sublime Text to [DynoTable](https://dynotable.com), the DynamoDB client.
DynoTable gives the language features for your DynoTable SQL, PartiQL and OpenSearch files.

## Install

1. Install [Package Control](https://packagecontrol.io/installation).
2. Run "Package Control: Install Package" and pick `LSP`.
3. Run "Package Control: Install Package" again and pick `LSP-dynotable`.

## What works

- Completion, diagnostics, hover and formatting.
- Rename of table aliases.
- Inlay hints, when you switch them on: set `"show_inlay_hints": true` in the LSP settings, or run
  "LSP: Toggle Inlay Hints".
- DynoTable SQL files: `.dtsql` and `.dynotable.sql`.
- PartiQL files: `.partiql`.
- OpenSearch files: `.opensearch`. The first line names the index:

  ```
  // dynotable: index=orders
  {"match": {"status": "shipped"}}
  ```

The package does not attach to plain `.sql` or `.json` files.

## Run a statement

Click the **Run** lens above a statement. The rows show in the "DynoTable Results" panel at the
bottom of the window, with a summary line under the table. SQL and PartiQL statements can also get
an **Open in DynoTable** lens. It opens the statement's table in the app. OpenSearch files get no
lenses: use "DynoTable: Run Statement".

You can also use the Command Palette:

- "DynoTable: Run Statement" runs the selection. With no selection, it runs the statement at the
  cursor. In an OpenSearch file, it runs the whole file. Use it when the lens is cut off at the end
  of a long line.
- "DynoTable: Sort Results" sorts the rows in the panel by a column you pick, ascending or
  descending. Text sorts by code point, so a few rare characters can sort in another order than in
  VS Code.
- "DynoTable: Copy Results as CSV", "… as JSON" and "… as Markdown" copy all rows in query order,
  also after a sort.
- "DynoTable: Cancel Run" stops the run. The panel says that the run was cancelled.

One statement runs at a time in a window. "DynoTable: Run Statement" runs unsaved edits as you see
them. A lens that you click right after an edit can run the wrong text: use the command then. A
file with a syntax error has no runnable statements. A PartiQL write does not run from the editor:
make writes in DynoTable.

The package has no key binding for Run, because Cmd+Enter and Ctrl+Enter are core keys. To add one,
run "Preferences: Key Bindings" and add:

```json
{
	"keys": ["super+enter"],
	"command": "dynotable_run",
	"context": [
		{"key": "selector", "operand": "source.sql.dynotable | source.partiql | source.opensearch"}
	]
}
```

Use `ctrl+enter` on Linux and Windows. The `context` keeps the core key in all other files.

## Requirements

- Sublime Text build 4200 or later.
- macOS on Apple silicon, Linux x64 or Windows x64. `dynotable-lsp` has no binary for other
  platforms yet.
- DynoTable 1.20.0 or later, with the Editor integration switched on.
- `dynotable-lsp` on your `PATH`, or nothing: when `dynotable-lsp` is not on your `PATH`, the
  package installs the `dynotable-cli` version that it pins. It runs it with Node.js from your
  `PATH`, or with a Node.js that it downloads.

When DynoTable is not running, the first start of the language server starts DynoTable with no
window.

## Pick a profile

Put a `.dynotable.json` file in the root of your project:

```json
{"profile": "dev"}
```

The value is a profile id or slug. With no `.dynotable.json`, DynoTable uses your profile when you
have exactly one.

## After you quit DynoTable

The language server stops and stays stopped. The package does not start DynoTable again. To get
the features back:

1. Start DynoTable.
2. Switch to a DynoTable file, or open one.

## When DynoTable refuses the connection

DynoTable refuses the connection when you are signed out, when the Editor integration is off, or
when the `.dynotable.json` of the project is not correct. The status bar then says "DynoTable
refused the connection", and the console (View → Show Console) gives the reason. The language
server stays stopped in that window. Other windows keep their language server.

Fix the cause, then run "DynoTable: Retry Connection" from the Command Palette in that window.

## Development

```sh
uv run -p 3.8 python -m unittest discover -s tests
npx --yes pyright@1.1.414
```

Python 3.8 is the floor (`.python-version`). CI runs the unit tests on Python 3.8 and 3.14, and
the type check (`.github/workflows/tests.yml`).

The syntax tests run in CI (`.github/workflows/syntax.yml`). To run them locally, put this package
at `Data/Packages/LSP-dynotable` of the Linux `st_syntax_tests` build 4215, next to the
`sublimehq/Packages` tag `v4215`, and run `syntax_tests` in a `linux/amd64` container.

## License

MIT.
