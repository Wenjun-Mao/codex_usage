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

## Stable model identities

All model charts use `model_presentation.model_color_slot()` (or `model_color()`
for CSS values). Slots are persistent design identities, independent of visible
models, ordering, range, project filters, or release. The baseline is the 2.13.5
speed and project/model comparison design; usage time bars and project stacks
adopt it. Bar legends retain bar swatches. Point series, compact overviews, and
point legends use the slot's geometry from `report_speed_marks.MARKERS`.

| Model | Slot | Day | Night | Point shape |
| --- | --- | --- | --- | --- |
| GPT-6 Astra | 0 | `#087f8c` | `#45c5d6` | Square |
| GPT-5.6 Sol | 1 | `#c47f00` | `#f2b84b` | Circle |
| GPT-5.6 Terra | 2 | `#2e8b57` | `#5fc98a` | Diamond |
| GPT-5.6 Luna | 3 | `#7656c7` | `#b59af1` | Down triangle |
| GPT-6 Sol | 4 | `#3568c8` | `#6f9cf4` | Pentagon |
| GPT-6 Luna | 5 | `#bb477d` | `#ee7aaa` | Up triangle |
| GPT-6.1 Sol | 6 | `#c74f37` | `#ef806b` | Circle |
| GPT-6.1 Terra | 8 | `#727327` | `#c6c76a` | Hexagon |

New known identities append slots without renumbering or restyling existing
ones. Promoting an already-used fallback name into the explicit model registry
must retain its prior slot and point shape unless an intentional reviewed design
migration changes that identity; appending a new slot does not authorize such a
change. Unknown names use case-folded SHA-256 and a **frozen** fallback slot tuple;
never grow that tuple with the palette or resolve collisions from visible peers.
Finite color/shape collisions are allowed, so labels remain essential. Slot 7
is neutral Other, excluded from model assignment. Project colors and account
readings use separate domains; hollow small-sample points and outlined
unknown/API-excluded cost diamonds retain their status meanings. Forced colors
use system text colors and preserve point geometry. Exact tokens/geometry are
pinned in `tests/test_model_design_compatibility.py`; cross-renderer output and
presentation-cache invalidation are covered in `tests/test_model_chart_identity.py`.
Changing existing identities is an intentional reviewed design change.

## Review Checklist

Before shipping a day-mode UI change, check:

- Does it preserve the current light theme token vocabulary?
- Is blue reserved for primary action, active state, or the chart line?
- Are financial values easier to scan than the surrounding labels?
- Do charts and tables stay legible without visual clutter?
- Does the page still work cleanly at `390px` width?
- Would the same component be straightforward to theme for night mode?
