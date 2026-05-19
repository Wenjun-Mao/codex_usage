# Night Mode Design

This document defines the planned low-glare night theme for `mafinance`.
It is a design contract for future implementation, not a CSS implementation yet.

Night mode should feel like the same portfolio workbench with the lights turned down. It should
reduce eye strain for evening use while keeping charts, tables, forms, and financial semantics
clear.

## Role

Night mode is for authenticated portfolio work first: dashboard, performance, ledger, accounts,
holdings, imports, and scenarios.

It should:

- reduce page luminance without becoming pure black everywhere
- keep dense financial data readable
- preserve the same information hierarchy as day mode
- avoid glowing charts and neon controls
- use the same token names so implementation can be a variable override

It should not:

- invert day mode mechanically
- make surfaces indistinguishable from the page background
- use blue as ambient decoration
- weaken semantic up/down colors until they become ambiguous
- introduce a separate component system

## Core Tokens

Night mode should override the same tokens documented in `day-mode.md`.

| Token | Night value | Use |
| --- | --- | --- |
| `--bg` | `#0d0f12` | Main page background |
| `--bg-strong` | `#14171c` | Stronger page bands and shell contrast |
| `--surface` | `#161a20` | Cards, panels, nav surfaces, tables, form controls |
| `--surface-strong` | `#1d222a` | Elevated or selected surfaces |
| `--surface-soft` | `#202631` | Empty states, inactive fills, subtle bands |
| `--surface-muted` | `#2a313b` | More visible muted fills and disabled-like surfaces |
| `--surface-dark` | `#0a0b0d` | Deep contrast surfaces when needed |
| `--text` | `#eef2f6` | Headings, primary values, strong labels |
| `--muted` | `#a7b0bc` | Secondary text, helper copy, axis labels |
| `--muted-soft` | `#7f8996` | Tertiary text and less important metadata |
| `--accent` | `#4f83ff` | Primary action, active navigation/range chip, chart line |
| `--accent-strong` | `#7da3ff` | Strong accent state on dark surfaces |
| `--accent-soft` | `rgba(79, 131, 255, 0.16)` | Selected fills and subtle accent backgrounds |
| `--highlight` | `#d8a72f` | Rare highlight color, toned down for dark backgrounds |
| `--success` | `#31c98a` | Positive financial movement, text-first |
| `--success-soft` | `rgba(49, 201, 138, 0.16)` | Positive badge or subtle fill |
| `--danger` | `#ff6b78` | Negative financial movement, destructive risk |
| `--danger-soft` | `rgba(255, 107, 120, 0.16)` | Negative badge or subtle fill |
| `--border` | `#303844` | Default hairline border |
| `--border-soft` | `#252c35` | Interior dividers and subtle chart/table rules |
| `--shadow` | `0 10px 28px rgba(0, 0, 0, 0.28)` | Larger contained surfaces |
| `--shadow-soft` | `0 1px 2px rgba(0, 0, 0, 0.22)` | Small controls and panels |

Night mode should also set `color-scheme: dark` so native controls, scrollbars, and form widgets
match the theme where the browser supports it.

## Component Rules

### Navigation

Navigation should use `--surface` with a clear but quiet bottom border. The active route should
remain obvious through accent fill or selected state, but avoid a glowing blue treatment. Utility
actions stay muted.

### Cards And Panels

Cards need visible separation from the page background. Use `--surface` for normal cards,
`--surface-strong` for raised/active panels, and `--border` for structure. Shadows should be
darker but still subtle.

### Tables And Data Lists

Tables should prioritize contrast and row tracking. Header labels use `--muted`; primary values
use `--text`; row dividers use `--border-soft`. Avoid high-contrast white grid lines.

### Forms

Inputs and selects should use `--surface-strong` or `--surface`, with clear borders and readable
placeholder text. Focus rings use accent blue but should stay controlled and non-glowing.

### Buttons, Chips, And Badges

Primary buttons use `--accent` with readable light text. Secondary buttons use dark surfaces and
borders. Chips and badges should preserve day-mode geometry so theme changes do not shift layout.

### Messages And Empty States

Messages should be darker versions of the day-mode roles, not bright banners. Empty states should
use `--surface-soft` and muted text, with links or actions still easy to find.

## Chart Rules

Charts need special care because they dominate night-mode luminance.

Chart line and fill:

- primary line uses `--accent`
- area fill should be lower opacity than day mode
- latest-value marker should remain readable but not bloom

Axes and grid:

- y-axis and x-axis labels use `--muted`
- horizontal grid lines use low-alpha border color
- vertical grid lines should be sparse or very faint
- exact dates remain in tooltip and axis-pointer labels

Tooltip:

- use an opaque or nearly opaque dark surface
- avoid bright glass blur that creates a halo
- use `--text` for values and `--muted` for labels
- preserve compact card dimensions

Semantic colors:

- positive and negative values keep green/red meaning
- use semantic colors mainly for text and small badges
- avoid large red/green filled regions

## Implementation Guidance

The first implementation should prefer a CSS-token override before changing component markup.

Recommended behavior:

- support system preference via `prefers-color-scheme`
- add a manual theme toggle after the token override is stable
- persist manual choice locally
- keep screenshots for dashboard, performance, ledger, and Yahoo import

Implementation should not change data behavior, routing, forms, or chart payloads.

## Review Checklist

Before shipping night mode, check:

- Is the page comfortable in a dim room without becoming muddy?
- Are chart axes, grid lines, and tooltips readable?
- Are primary actions still obvious?
- Are tables and forms scannable without harsh contrast?
- Are semantic up/down colors distinguishable and not overused?
- Does browser smoke cover desktop and `390px` mobile widths?
