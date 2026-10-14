# Model Economics And Diagnostic Safety Checkpoint

Date: 2026-10-14. Nonpublishing local checkpoint, not release qualification.

## Scope

Within each project, primary model rows now expose average cost per response,
responses per turn, compact tokens per turn and measured turns. All models share
the existing scoped ledger population. Secondary totals, shares, exact costs,
priceability and missing-turn coverage remain inspectable. Model identity stays
visible during table-local scrolling. No accounting, schema, query or data-source
change is introduced. The new economics browser inventory is mandatory inside
the existing screenshot/allowance qualification gate.

The privileged temporal-tracing prototype is not on main or pushed: local branch
`codex/held-temporal-trace-prototype`, commit `ec705ce`, preserves it and its hold
note. Ownership association, privileged child containment and independent export
bounds are unresolved. The older aggregate sampler is held before any attachment;
its same-bundle XPC selection assumption was not sufficient ownership evidence.
Default unsampled checks and read-only capability discovery are unaffected.

The evidence writer now preserves the original input assertion when diagnostic
I/O fails, and rejects missing evidence after an otherwise successful replay.
This is a diagnostic error-retention repair, not a causal WebKit correction.

## Verification

All outputs below are ignored local synthetic artifacts; none is a release receipt.

| Check | Result | Evidence |
| --- | --- | --- |
| Complete Python suite after safety changes | 2,192 passed; one approved native-Windows-only skip; 65.80 s | `output/qualification/model-economics-safety-core/` |
| Collection/JUnit/baseline reconciliation | 2,193 unique collected/result identities; no lost required cases | Same inventory and JUnit validated by `validate_python` |
| Complete extension build/tests | 48 passed; no skips | `output/qualification/model-economics-extension/` validated by `validate_extension` |
| Combined screenshot/allowance/economics gate | 15 screenshot, 216 allowance and 18 economics cases validated | `output/qualification/model-economics-final-visual/` |
| Original real-input hover gate | All 72 identities, scripts disabled | `output/qualification/model-economics-final-hover/` |
| Economics controlled first-case failure | Required case rejected; zero completed cases; diagnostics retained | `output/qualification/project-economics-injected/` |
| Monetary parity and work guards | Exact frozen parity; zero quota-only reprices and unchanged-recovery source opens | `check_speed_parity.py`, `check_speed_work.py` |
| Focused safety/UI checks | 76 passed | Sampler/probe/workflow/economics/inventory tests |
| Ruff and diff whitespace | Passed | Local checks |

The initial full-suite invocation lacked `PYTHONPATH=scripts` and failed before
collection. It was corrected to the existing workflow invocation, not patched
around. An earlier 2,190-pass suite preceded the two new sampler refusal cases;
the complete later inventory above supersedes it. Original historical hosted
proof remains historical and cannot qualify this changed source.

## Gates Still Open

Stage A has a reproduced pre-expression wait but no owning causal diagnosis;
B remains gated. No fresh normal, controlled hover retry, exact-qualified-VSIX
native or dry-run promotion has been completed for the combined source. The
small economics injection is not a substitute for stage C's hosted retry pilot.
`PROMOTION_ENABLED` remains false, version remains 2.12.2, no new release tag
exists from this work and no publication was dispatched. Owner UI acceptance is
required before publication. A prepared local preview is not an eligible release
package, and no new user window is opened while the owner is away.
