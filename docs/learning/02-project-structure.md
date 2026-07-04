# Project Structure

Project structure is architecture. It decides where ideas live, what can depend on what, and how easy the repo is to understand after a few months away.

The goal is not to have many folders. The goal is to make each folder answer one question clearly: "what kind of thing belongs here?"

## Current Top-Level Shape

```text
codex_usage/
  src/codex_usage/          Python product core
  tests/                    Python test suite
  extensions/vscode/        VS Code extension wrapper package
  docs/                     Product, release, design, ADR, and learning docs
  scripts/                  Generic repo scripts
  output/                   Generated reports and VSIX packages, ignored
  build/ and dist/          Generated build artifacts, ignored
  .venv/                    Local virtual environment, ignored
  pyproject.toml            Python package metadata and build config
  uv.lock                   Python dependency lockfile
  README.md                 Public project overview
  PRIVACY.md                Public privacy statement
  SUPPORT.md                Public support instructions
  CHANGELOG.md              Root changelog
  LICENSE                   Project license
```

Future me: if a new file does not obviously fit one of these buckets, pause before creating it. That discomfort is often a design signal.

## Root Directory

The root should stay boring. It is for files that define the project as a package, repository, or public artifact:

- `pyproject.toml`
- `uv.lock`
- `README.md`
- `CHANGELOG.md`
- `LICENSE`
- `PRIVACY.md`
- `SUPPORT.md`
- `.gitignore`
- `.python-version`

Avoid putting experiments, generated reports, copied logs, screenshots, or one-off scripts at the root. Root clutter makes the repo feel smaller at first and harder to maintain later.

The old `main.py` exists as prototype residue. Long term, root prototypes should either be deleted, moved into docs as historical context, or replaced by real package entry points.

## Python Core: `src/codex_usage/`

The Python package owns product logic:

- session discovery;
- JSONL parsing;
- project identity;
- project transitions;
- caching;
- aggregation;
- pricing;
- report view models;
- HTML/SVG rendering;
- thread listing;
- sync engine;
- CLI.

This folder uses a `src/` layout so imports and packaging behave like an installed package. That prevents tests from accidentally importing loose files from the repository root.

Rule of thumb: if behavior must also work outside VS Code, it belongs in Python.

## Python Tests: `tests/`

The `tests/` folder should test behavior, not file names. It does not need to mirror `src/codex_usage/` one-to-one, but test names should make the protected contract obvious:

- `test_parser_aggregation.py`
- `test_pricing.py`
- `test_session_cache.py`
- `test_project_transitions.py`
- `test_sync.py`
- `test_reporting_html.py`

Tiny synthetic fixtures are preferred over copied real Codex logs. Raw session logs should not be committed.

## VS Code Extension: `extensions/vscode/`

The VS Code extension is its own Node package:

```text
extensions/vscode/
  src/core.ts              Pure testable helpers
  src/extension.ts         VS Code API side effects
  test/                    Node tests for wrapper logic
  media/                   Icon and extension media
  package.json             VS Code manifest and scripts
  package-lock.json        Node dependency lockfile
  README.md                Marketplace package README
  CHANGELOG.md             Marketplace changelog
  SUPPORT.md               Marketplace support doc
```

Generated extension output is ignored:

- `extensions/vscode/out/`
- `extensions/vscode/bin/`
- `extensions/vscode/node_modules/`

Bundled runtime executables are built before packaging, but they are not committed:

- `extensions/vscode/bin/win32-x64/`
- `extensions/vscode/bin/darwin-arm64/`

Rule of thumb: TypeScript owns VS Code behavior. It should not recalculate token usage, pricing, project identity, or sync decisions.

## Documentation: `docs/`

Documentation has multiple audiences, so it is split by purpose:

```text
docs/
  adr/                     Durable architecture decisions
  learning/                Private-style engineering notebook
  marketplace/             Public Marketplace assets
  design/                  Visual design tokens and theme notes
  release.md               Release checklist and operational notes
  superpowers/             Plans/specs produced during implementation
```

`docs/adr/` answers: "What decision did we make, and why?"

`docs/learning/` answers: "How should future me understand and learn from this project?"

`docs/superpowers/` is implementation history. It can be useful, but it is not the primary architecture documentation.

`docs/marketplace/` is for listing assets that are safe to publish.

## Scripts: `scripts/`

Scripts should be generic repo utilities, not one-off workflow dumps.

Current example:

- `scripts/build-windows-exe.ps1`

If a workflow grows multiple files, give it its own folder with a `README.md` rather than scattering helper files across the root.

## Generated And Local-Only Folders

These should stay ignored:

- `output/`
- `build/`
- `dist/`
- `.venv/`
- `.worktrees/`
- `extensions/vscode/out/`
- `extensions/vscode/bin/`
- `extensions/vscode/node_modules/`
- raw `*.jsonl` session files, except explicit redacted test fixtures.

Generated artifacts are useful for smoke tests and local packaging, but Git should store recipes and source, not local products.

## Adding New Things

Use this decision guide:

| New thing | Put it here |
| --- | --- |
| Parser, pricing, cache, sync, report logic | `src/codex_usage/` |
| Python behavior test | `tests/` |
| VS Code command, status bar, webview, QuickPick logic | `extensions/vscode/src/` |
| VS Code wrapper test | `extensions/vscode/test/` |
| Marketplace icon or screenshot | `extensions/vscode/media/` or `docs/marketplace/` |
| Durable architecture decision | `docs/adr/` |
| Learning note for future me | `docs/learning/` |
| Release checklist or operational note | `docs/release.md` |
| Reusable build helper | `scripts/` |
| Generated report or VSIX | `output/`, ignored |

## Smell Checks

A structure decision may be wrong if:

- a file needs to import both Python core internals and VS Code APIs;
- a root-level file is not part of package identity, release identity, or repository identity;
- a docs folder contains both private notes and Marketplace-facing material without separation;
- a generated artifact needs to be committed for normal development to work;
- a module name becomes vague, such as `utils.py`, because unrelated helpers are accumulating.

Future me: structure should reduce the number of questions a reader has to ask. If a new folder makes the project harder to explain, it has not earned its place.
