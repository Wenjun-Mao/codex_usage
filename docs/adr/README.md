# Architecture Decision Records

This folder records durable project decisions. Each ADR is short on purpose: enough context to remember why the decision exists, not a full project narrative.

Read the learning notebook in [../learning](../learning) for the story behind the system.

## Decisions

| ADR | Decision |
| --- | --- |
| [0001](0001-python-core-thin-vscode-wrapper.md) | Keep the Python core and use a thin VS Code TypeScript wrapper. |
| [0002](0002-native-html-svg-dashboard.md) | Render the dashboard with native HTML, CSS, and inline SVG. |
| [0003](0003-effective-dated-pricing.md) | Price usage with effective-dated checked-in rate schedules. |
| [0004](0004-local-cache-for-performance-and-retention.md) | Use a local SQLite cache for speed and historical retention. |
| [0005](0005-canonical-project-identity.md) | Group projects by canonical identity, not display label. |
| [0006](0006-bundled-windows-vsix-runtime.md) | Bundle a Windows x64 executable in the VSIX. |
| [0007](0007-byo-folder-selected-conversation-sync.md) | Sync selected conversations through a bring-your-own local folder. |
| [0008](0008-three-way-prefix-aware-sync.md) | Use three-way prefix-aware sync to avoid unsafe overwrites. |
| [0009](0009-public-private-documentation-boundary.md) | Separate public docs, ADRs, learning notes, and implementation history. |
| [0010](0010-macos-apple-silicon-vsix-runtime.md) | Bundle a macOS Apple Silicon executable in the VSIX. |
| [0011](0011-flat-single-process-sync.md) | Use flat conversation files and one plan-driven sync process. |
| [0012](0012-exact-task-sync-selection.md) | Select exact Codex tasks from one project-grouped local and remote inventory. |
| [0013](0013-manual-directional-cross-platform-sync.md) | Use explicit Pull and Push commands and rebind imported tasks to canonical local projects. |
| [0014](0014-manual-task-transfer.md) | Present the feature as optional Task Transfer with three deliberate operations: Import Tasks, Export Tasks, and Review Transfer Status. |
| [0015](0015-explicit-token-category-accounting.md) | Preserve explicit upstream token categories without reconstructing missing evidence. |
| [0016](0016-register-imported-tasks-through-codex.md) | Register imported tasks through Codex's supported app-server read-repair path. |
| [0017](0017-one-project-per-transfer-operation.md) | Constrain each Import and Export to one Codex project while keeping the transfer folder multi-project. |
