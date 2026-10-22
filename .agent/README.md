# Agent Toolkit

This directory contains a framework-neutral policy pack for coding agents working on Binance Predict Value & Trend.

## Layout

- `rules/`: repository-wide engineering constraints by concern.
- `skills/`: task playbooks with trigger conditions, procedure, checks, and deliverables.
- `agents/`: role briefs for specialized audit/implementation/review passes. These are guidance files, not necessarily auto-discovered subagents in every coding tool.
- `workflows/`: orchestrated implementation workflows for repeatable tasks.

## How to use

1. Start from root `AGENTS.md`.
2. Read the workflow for the requested task.
3. Select only the relevant skills and role briefs to keep context focused.
4. Inspect actual repository code and current Git status before editing.
5. Implement changes, run checks, and update audit/report documents.

Some tools use different conventions (`.agents/`, `.agent/skills/`, IDE-specific rules, etc.). Do not rename this directory automatically. If a tool needs another convention, add a thin adapter or copy only the necessary files after confirming that tool's documented discovery rules. Root `AGENTS.md` remains authoritative.
