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
