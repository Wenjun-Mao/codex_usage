# Codex Usage Engineering Notebook

This folder is a private-style engineering notebook for future maintainers of Codex Usage. It is not user-facing product documentation. Its job is to explain how the project should be thought about from day 0, how the current architecture hangs together, and what lessons are worth carrying into the next project.

Read in this order:

1. [Day 0 Product Design](01-day-0-product-design.md)
2. [Project Structure](02-project-structure.md)
3. [Architecture Map](03-architecture-map.md)
4. [Source Code Walkthrough](04-source-code-walkthrough.md)
5. [Testing Strategy](05-testing-strategy.md)
6. [Packaging And Release](06-packaging-and-release.md)
7. [Sync Design Retrospective](07-sync-design-retrospective.md)
8. [Developer Exercises](08-developer-exercises.md)
9. [Debugging And Incident Notes](09-debugging-and-incident-notes.md)
10. [Product UX Lessons](10-product-ux-lessons.md)

Use the ADRs in [../adr](../adr) as the companion decision log. The learning docs explain the project as a story. The ADRs capture durable decisions in a format that is easier to review later.

## How To Use This Notebook

Read one page, then open the referenced source files and trace the code. Do not treat the docs as a substitute for reading the implementation. The value is in connecting product constraints to code boundaries.

Future me: the important lesson is not "we built a VS Code extension." The important lesson is that a useful product is usually a chain of contracts: data contract, parsing contract, identity contract, pricing contract, rendering contract, runtime contract, and release contract. When one contract is fuzzy, bugs appear in surprising places.
