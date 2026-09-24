# ADR 0044: Observed Plan Allowance Analytics

## Status

Accepted for 2.8.0 on 2026-09-21; amended for 2.8.4 on 2026-09-24.

## Context

Quota percentages are account-wide meters, while the local ledger describes
observed workload. Neither a subscription price nor account lifetime tokens
establishes a fixed monetary entitlement. Historical quota windows can change
slots, durations, reset timestamps, and plan. The retained calibration research
is [2026-09-21-plan-allowance-calibration.md](../research/2026-09-21-plan-allowance-calibration.md).

## Decision

Every capture reads the official App Server `account/read`,
`account/rateLimits/read`, and `account/usage/read` methods through a short-lived
stdio RPC client. Initialization and metadata requests never start a model turn.
A shared total timeout bounds the probe. Failure is a content-free capture
diagnostic and does not fail ordinary usage capture. The selected CODEX_HOME is
passed explicitly. Retain only plan, bucket, slot, numeric usage/reset metadata,
reset-credit count, and lifetime-token coverage diagnostics. Never persist
account identity, authentication, prompts, response content, or raw RPC frames.
Protocol reference: https://learn.chatgpt.com/docs/app-server.

Ledger schema 3 and parser cache schema 10 add quota tables without rebuilding
language/image usage or losing parser checkpoints. Existing databases receive
private SQLite backups before migration. Future token_count events contribute
allowlisted rate_limits metadata. Registered historical sources recover newest
first using complete files up to 128 KiB or at most 64 KiB from each endpoint.
Partial boundary lines are discarded. Each capture spends at most 8 MiB in the
existing coalesced heavy-I/O lane. Source fingerprints persist resume progress;
changed sources are reconsidered. Device/inode transitions also invalidate
recovery state. Unknown pre-parser identities are not treated as mismatches;
size/mtime and the open-file identity guards still protect endpoint reads. Repeated recovered states use compressed
unique timestamps and retain source provenance, allowing future analysis without
another source scan. Endpoint recovery is always disclosed as partial history.

Reset segmentation uses limit ID, plan, and reported duration; slot is metadata,
not identity. One-point decreases and unsupported decreases below five points
remain meter corrections. Supported boundaries are classified conservatively:
scheduled-compatible, banked-reset-compatible, global-reset-compatible, or
early/unknown. Classifications describe evidence, not proven causes. A plan
change invalidates continuity. No cost or percentage delta crosses a segment.
No weekly duration is hard-coded.

For each segment, fit the median cumulative priced ledger API-equivalent cost
per integer percentage bin against used percentage, with a free intercept.
The estimated full-allowance value is 100 times the positive slope. At least
five distinct observation times and bins are required. Confidence gates:

- High: completed; at least 50 percentage points and 10 bins; fully priced;
  R² >= 0.98; pairwise slope P90/P10 <= 1.15; no ambiguous reset boundary.
- Medium: completed; at least 20 percentage points and 5 bins; fully priced;
  R² >= 0.95; pairwise slope P90/P10 <= 1.35.
- Low/provisional: at least 10 percentage points and a valid positive fit,
  with weaker evidence or an ongoing window; never a qualified completed estimate.
- Otherwise: insufficient data with no monetary estimate. Unpriced intervals
  never produce a monetary estimate. Incomplete ledger coverage cannot qualify.

The summary shows the latest window's valid priced fit in the largest type.
An ongoing window is labeled **Current · provisional**, with its observed date
range. Series identity appears when multiple buckets are active or the headline
cannot be matched to one active bucket; the active bucket row already identifies
an unambiguous current series. The summary omits repeated provisional confidence
wording and retains High/Medium confidence on qualified current headlines. Fit
evidence stays in collapsed diagnostics. If the latest reset window lacks a
valid priced estimate, use the most recent earlier valid priced estimate only
when limit ID, plan, and duration all match. Label it **Previous window**, show
its observation dates and series identity, and retain its confidence. Never
present that value as current or borrow it from another series. If no such
estimate exists, show insufficient data. When the latest window becomes valid,
it takes over the headline. The summary contains one economic figure. Earlier
High/Medium windows with series identity, dates, and confidence remain in the
collapsed reset-window disclosure. Current windows have dashed detail styling.
Lifetime account usage is coverage context only, never a fit input. Provisional
estimates are workload-specific observations, not cash or contractual
entitlements.

The additive API-v1 capability is `plan-allowance`. Status includes plan, active
buckets/reset timing, probe timestamp/freshness/diagnostics, and recovery counts.
Active reset times use the report's configured timezone and show both its
abbreviation and UTC offset. The report passes the timezone already resolved
for its range through the shared HTML renderer, so native and VS Code reports
use the same formatting. The report cache already keys by timezone; changes to
the allowance markup also advance the report-render revision to invalidate old
cached HTML.
The shared script-free report places Plan Allowance after KPIs/notices and
before Project Economics. It remains account-wide under project/date filters
and exposes reset-window and capture details in Day/Night and narrow layouts.
Probe timestamps, recovery counts, fit diagnostics, and allowance history stay
in one collapsed diagnostics disclosure. History includes valid priced fits
from ongoing, completed, and plan-change-ended windows, including provisional
fits, sorted newest first across series. Each row identifies its series,
observation dates, current/completed/ended status, confidence, percentage span,
bins, and local ledger coverage. It shows at most the latest 12 valid priced
windows and gives the full count; individual reset windows remain available
below. Capture tables
show at most the latest 100 points per window and disclose the full count. The
economic summary is unframed and uses a subtle divider. Report interactions
read only the ledger and never probe or open JSONLs.

## Rejected Alternatives

- Dividing cumulative lifetime dollars by current usage crosses resets and
  produces misleading values.
- Treating slot or exact reset timestamp as identity creates false windows when
  producers move slots or adjust clocks.
- Scanning historical file interiors creates unbounded capture latency.
- Reusing account identity to reconcile devices adds sensitive retention without
  proving local coverage.
- Inferring entitlement changes from fitted values confuses workload/pricing
  changes with upstream policy.

## Consequences and Guardrails

Local estimates remain workload-specific and may omit usage on other devices.
No UI claims cash value, contractual entitlement, or changes to OpenAI limits.
Oracle tests enforce segmentation, pricing, confidence, and no cross-window
consumption; migration tests preserve usage; report tests forbid source reads and
probes. Quota storage is independent of language and image accounting.
