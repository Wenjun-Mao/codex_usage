# Day Mode Design

This document is the app-owned design contract for the current `mafinance` light theme.
The Coinbase reference in `temp/design-md/coinbase/DESIGN.md` remains useful inspiration, but
this file describes the product UI we actually maintain.

Day mode should feel like a calm portfolio workbench: bright, compact, low-drama, and built for
repeated scanning of accounts, holdings, transactions, and performance history.

## Role

Day mode is the default theme and the baseline for all future theme work.

It should:

- keep authenticated pages task-first
- make charts, tables, and forms readable in daylight
- reserve blue for primary action and active state
- use soft elevation instead of heavy shadows
- preserve enough contrast for dense financial numbers

It should not:

- become a marketing landing-page palette
- overuse Coinbase Blue as decoration
- make every repeated item feel like a separate floating card
- rely on large shadows to create hierarchy

## Core Tokens

The current implementation starts in `static/css/foundation.css`.

| Token | Day value | Use |
| --- | --- | --- |
| `--bg` | `#f7f8fa` | Page background behind the authenticated shell |
| `--bg-strong` | `#eef0f3` | Slightly stronger page or control backgrounds |
| `--surface` | `#ffffff` | Cards, panels, nav surfaces, tables, form controls |
| `--surface-strong` | `#ffffff` | Elevated or selected surfaces that stay white in day mode |
| `--surface-soft` | `#f4f6f8` | Empty states, subtle bands, inactive control fills |
| `--surface-muted` | `#eef1f5` | More visible muted fills and disabled-like surfaces |
| `--surface-dark` | `#0a0b0d` | Rare dark editorial or contrast surfaces |
| `--text` | `#0a0b0d` | Headings, primary values, strong labels |
| `--muted` | `#5b616e` | Secondary text, helper copy, axis labels |
| `--muted-soft` | `#7c828a` | Tertiary text and less important metadata |
| `--accent` | `#0052ff` | Primary action, active navigation/range chip, chart line |
| `--accent-strong` | `#003ecc` | Pressed/strong accent state |
| `--accent-soft` | `rgba(0, 82, 255, 0.08)` | Subtle selected fills and accent backgrounds |
| `--highlight` | `#f4b000` | Rare highlight color, not an action color |
| `--success` | `#05b169` | Positive financial movement, text-first |
| `--success-soft` | `rgba(5, 177, 105, 0.1)` | Positive badge or subtle fill |
| `--danger` | `#cf202f` | Negative financial movement, destructive risk |
| `--danger-soft` | `rgba(207, 32, 47, 0.1)` | Negative badge or subtle fill |
| `--border` | `#dee1e6` | Default hairline border |
| `--border-soft` | `#eef0f3` | Interior dividers and subtle chart/table rules |
| `--shadow` | `0 8px 24px rgba(10, 11, 13, 0.06)` | Larger contained surfaces |
| `--shadow-soft` | `0 1px 2px rgba(10, 11, 13, 0.06)` | Small controls and panels |
| `--radius` | `16px` | Primary surface radius |
| `--radius-sm` | `10px` | Smaller controls and compact cards |
| `--radius-xs` | `6px` | Tiny badges and low-emphasis elements |

Any new theme token should be added only when an existing token cannot describe the role.

## Component Rules

### Navigation

Authenticated navigation should sit quietly on a white surface with soft borders. The active route
uses accent blue sparingly, usually through a selected pill or text state. Utility actions like
`Admin` and `Log out` should stay visually secondary.

### Cards And Panels

Cards should be white with hairline borders and restrained shadow. Repeated data cards can use
`--radius`, but avoid making page sections look like nested cards. Empty panels should use
`--surface-soft` and muted text.

### Tables And Data Lists

Tables should favor scanability over decoration. Use tabular numbers, muted headers, soft row
dividers, and strong text only for primary values. Avoid zebra striping unless a table becomes
difficult to track at high row counts.

### Forms

Inputs and selects use white fill, border hairlines, and the shared control height. Focus should
be visibly blue without expanding layout. Helper text stays muted and close to the field it
explains.

### Buttons, Chips, And Badges

Use filled accent buttons only for the single most important local action. Secondary actions use
white or soft surfaces with borders. Range chips and status badges should maintain stable
dimensions so loading and selection do not shift nearby content.

### Messages And Empty States

Messages should be compact and close to the surface they affect. Empty states should explain the
next useful action in one sentence, not become separate marketing cards.

## Chart Rules

Day-mode charts use Coinbase Blue for the primary line and a light blue area fill. Axis labels are
muted, grid lines are soft, and summary numbers are strong but compact.

Chart tooltip behavior:

- translucent white surface with blur
- strong date/time label
- exact grouped financial values
- compact spacing
- no oversized callout shadow

Chart axis behavior:

- exact dates belong in tooltips and axis-pointer labels
- visible x-axis labels should be sparse and range-aware
- y-axis labels may use compact financial notation
- vertical grid lines should not create visual noise

## Review Checklist

Before shipping a day-mode UI change, check:

- Does it preserve the current light theme token vocabulary?
- Is blue reserved for primary action, active state, or the chart line?
- Are financial values easier to scan than the surrounding labels?
- Do charts and tables stay legible without visual clutter?
- Does the page still work cleanly at `390px` width?
- Would the same component be straightforward to theme for night mode?
