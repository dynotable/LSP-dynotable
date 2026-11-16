# Changelog

## 1.0.2 — 2026-11-16

- The helper modules moved into the `dynotable` subpackage, so Sublime Text does not load them as separate plugins.

## 1.0.1 — 2026-11-16

- The server is `dynotable-cli` 0.1.2, which adds Intel Macs.

## 1.0.0 — 2026-11-16

- First release. DynoTable SQL (`.dtsql`, `.dynotable.sql`), PartiQL (`.partiql`) and OpenSearch
  (`.opensearch`) files get completion, diagnostics, hover, formatting, rename of table aliases and
  inlay hints from the DynoTable app. The server is `dynotable-cli` 0.1.1.
- Run a statement from the Run lens or the Command Palette. The rows show in the "DynoTable
  Results" panel. Sort them, copy them as CSV, JSON or Markdown, or cancel a run.
- SQL and PartiQL statements get the Run lens, and can get the Open in DynoTable lens. OpenSearch
  files get no lenses.
