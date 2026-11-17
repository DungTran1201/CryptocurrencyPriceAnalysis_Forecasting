# `20-architecture/` — System Architecture & Diagrams

## 1. Purpose
This folder defines the logical and physical architecture of the upgraded 3-Plane Data Platform, mapping all 13 canonical components (`COMP-DP-01..13`), process topologies (`LITE` vs `STANDARD` vs optional `EXTENDED`), and visual architecture diagrams.

## 2. Document Types Stored
- Master System Architecture Specification (`system-architecture-specification.md`)
- Architecture Mermaid Diagrams (`diagrams-architecture.md`)

## 3. Naming Rules
- Files use lowercase kebab-case `.md`.
- Every Mermaid diagram MUST be explicitly tagged `[AS-IS]`, `[TO-BE]`, or `[TRANSITION]` in its title and legend.
- Synchronous vs asynchronous paths and Control Plane vs Data Plane flows MUST be visually distinguished.

## 4. Document Structure
Architecture documents start with scope & hardware constraints, followed by Plane boundaries, Component Catalog (`COMP-DP-*`), Deployment Topology & Memory Partitioning, and Transition Strategy.

## 5. Cross-Folder Relationships
- Satisfies [`10-requirements/`](../10-requirements/README.md).
- Justified by [`50-architecture-decisions/`](../50-architecture-decisions/README.md).
- Detailed into implementation specs in [`30-detailed-design/`](../30-detailed-design/README.md) and [`40-interfaces-and-contracts/`](../40-interfaces-and-contracts/README.md).

## 6. Agent Rules for Creating & Updating
- Never reference components that do not have a `COMP-DP-*` entry or implementation WI.
- Every diagram node label containing parentheses, colons, or slashes MUST be double-quoted to guarantee valid Mermaid rendering.

## 7. What Does NOT Belong Here
- Individual SQL column definitions or Python method signatures (belongs in `40-interfaces-and-contracts/`).
- Detailed test step procedures (belongs in `70-testing/`).
- Operational CLI recovery scripts (belongs in `80-operations/`).
