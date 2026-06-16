# Codex Usage Engineering Notebook

This folder is a private-style engineering notebook for future maintainers of Codex Usage. It is not user-facing product documentation. Its job is to explain how the project should be thought about from day 0, how the current architecture hangs together, and what lessons are worth carrying into the next project.

Read in this order:

1. [Day 0 Product Design](01-day-0-product-design.md)
2. [Architecture Map](02-architecture-map.md)
3. [Source Code Walkthrough](03-source-code-walkthrough.md)
4. [Testing Strategy](04-testing-strategy.md)
5. [Packaging And Release](05-packaging-and-release.md)
6. [Sync Design Retrospective](06-sync-design-retrospective.md)
7. [Developer Exercises](07-developer-exercises.md)

Use the ADRs in [../adr](../adr) as the companion decision log. The learning docs explain the project as a story. The ADRs capture durable decisions in a format that is easier to review later.

## How To Use This Notebook

Read one page, then open the referenced source files and trace the code. Do not treat the docs as a substitute for reading the implementation. The value is in connecting product constraints to code boundaries.

Future me: the important lesson is not "we built a VS Code extension." The important lesson is that a useful product is usually a chain of contracts: data contract, parsing contract, identity contract, pricing contract, rendering contract, runtime contract, and release contract. When one contract is fuzzy, bugs appear in surprising places.

