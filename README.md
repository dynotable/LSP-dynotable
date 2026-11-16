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

## What does not work

There is no results grid. Run your queries in the DynoTable app or in the DynoTable extension for
VS Code.

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
when the `.dynotable.json` of the project is not correct. The language server then stays stopped
in that window. Other windows keep their language server.

Fix the cause, then run "DynoTable: Retry Connection" from the Command Palette in that window.

## Development

```sh
python3 -m unittest discover -s tests
```

The syntax tests run in CI (`.github/workflows/syntax.yml`). To run them locally, put this package
at `Data/Packages/LSP-dynotable` of the Linux `st_syntax_tests` build 4215, next to the
`sublimehq/Packages` tag `v4215`, and run `syntax_tests` in a `linux/amd64` container.

## License

MIT.
