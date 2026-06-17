# Product UX Lessons

This project improved when the UI stopped exposing implementation details and started matching the user's mental model.

## Settings Are Expensive

Several early settings felt useful to the implementer and confusing to the user:

- project aliases;
- project keys;
- sessions directory;
- subscription USD.

They were removed because the product could solve those needs automatically or through UI state.

Lesson: a setting is a product liability. Add one when the user has a real decision to make, not when the implementation has an unresolved question.

## Project-First Beats Thread-First

Codex conversations are the sync identity, but projects are the user's planning unit. A list of conversation IDs and titles is technically precise and emotionally noisy.

Better flow:

1. choose a sync folder;
2. choose projects;
3. choose all conversations in those projects or selected conversations.

Lesson: let internal IDs do the work in the background. Let users choose in the vocabulary they already use.

## Status Bar Beats Popups For Background State

Sync is a background behavior. Normal states such as idle, waiting, pulling, pushing, and recent success belong in the status bar and output channel.

Popups should be reserved for:

- manual sync results;
- conflicts;
- missing setup;
- failures that require action.

Lesson: visibility is not the same as interruption.

## First-Run Feedback Matters

The first cache build can take a few seconds. Without feedback, that feels broken. With a plain message such as "Initializing Codex usage cache. This can take a few seconds the first time," the same delay feels understandable.

Lesson: latency needs a narrative. A short truthful message can turn waiting into trust.

## Dashboard Controls Need Hierarchy

The action strip became crowded as features accumulated. Range, project, theme, sync, refresh, settings, and transitions do not have equal frequency.

Better pattern:

- keep frequent actions visible;
- put rare actions behind a menu;
- make sync a single menu control rather than several separate buttons;
- keep version visible but visually quiet.

Lesson: every visible control spends attention. Spend it on the actions users repeat.

## Script-Free Does Not Mean Static-Feeling

The dashboard uses HTML/CSS/SVG without webview scripts. That constraint still allows useful polish:

- CSS hover tooltips;
- responsive SVG;
- theme variables;
- compact bars;
- accessible labels.

Lesson: constraints can improve portability, but they raise the bar for careful markup and CSS.

## Visual Design Is Product Trust

The first dashboard worked, but polish changed how it felt:

- day/night mode;
- restrained blue workbench palette;
- cleaner heatmap colors;
- better icon;
- less crowded action strip;
- Marketplace screenshot.

Lesson: users infer reliability from visual care, especially for a tool that estimates cost and usage.

## Public Copy Should Be Conservative

The extension estimates API-equivalent USD and Codex credits from checked-in rates. It should not imply official billing accuracy, live pricing, or subscription conversion.

Lesson: analytics tools need trust language. Say what is measured, what is estimated, and what is unknown.

## Advanced Features Need Escape Hatches

Sync is powerful but experimental. It needs:

- pause/resume;
- manual-only mode;
- change folder;
- change projects;
- change conversations;
- clear setup without deleting files;
- status inspection.

Lesson: when a feature touches user state, the UI must make stopping and undoing configuration easy.

## Marketplace First Impression Matters

Once published, the extension competes visually with other listings. The icon, screenshot, description, category, and preview badge all affect whether users trust it enough to install.

Lesson: release polish is product work, not clerical work.

