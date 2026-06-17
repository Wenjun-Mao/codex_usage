# ADR 0009: Public And Private-Style Documentation Boundary

Status: Accepted

Date: 2026-06-16

## Context

The repository needs several kinds of documentation:

- public user documentation for GitHub and Marketplace readers;
- privacy and support documents;
- release and operations notes;
- implementation specs and plans;
- private-style learning notes for future development skill.

These documents have different audiences and should not be mixed together.

## Decision

Keep public product documentation in root-level files and Marketplace package files. Keep durable architecture decisions in `docs/adr/`. Keep private-style but public-safe learning notes in `docs/learning/`. Keep implementation history under `docs/superpowers/`.

The learning docs may use a candid "future me" voice, but they must remain safe for a public repository: no raw Codex logs, credentials, private prompts, personal machine paths, access tokens, or unpublished sensitive details.

## Alternatives Considered

- Put all documentation in the root README. This would make the README too long and mix users, maintainers, and personal learning goals.
- Keep learning notes outside the repo. Safer, but disconnects the lessons from the code they explain.
- Treat implementation plans as architecture docs. Useful history, but plans are too detailed and time-specific to be the main durable documentation.

## Consequences

The repo can support Marketplace users and future personal learning at the same time. The cost is that documentation must be curated by audience.

## Guardrails

Before committing learning notes or historical plans, scan for personal paths, emails, credentials, raw JSONL, generated reports, and local artifacts. Prefer synthetic examples.

