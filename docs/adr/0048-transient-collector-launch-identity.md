# ADR 0048: Transient Collector Launch Identity

## Status

Accepted for the 2.9.1 patch candidate on 2026-09-25.

## Context

The VS Code supervisor used the PID returned by spawning the bundled
PyInstaller executable to identify its collector. In a one-file build, the
bootloader starts a second process: a disposable probe observed spawn PID
`87162` and collector descriptor PID `87163`. Both platform acceptance runs
then treated the VS Code-owned collector as foreign and refused handoff.

## Decision

The supervisor generates a fresh 48-character random launch ID for each
transient start and passes it with the parent PID. The collector records it in
its private descriptor. Ownership requires the expected parent PID, launch ID,
and the same authenticated collector descriptor. Old descriptors without a
launch ID remain readable but cannot be claimed as managed by a new supervisor.

## Rejected Alternatives

- Equating the spawned bootloader PID with the running collector PID fails for
  one-file executables.
- Trusting only the parent PID could claim a replacement collector launched by
  another supervisor in the same extension host.

## Consequences And Guardrails

The descriptor gains an optional private launch ID without changing the HTTP
API. Focused tests cover the ownership match; disposable macOS and Windows CI
handoff checks exercise the packaged collector and real service registries.
