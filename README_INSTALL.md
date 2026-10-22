# Installing the Agent Kit

1. Extract this bundle into the repository root so `AGENTS.md` sits beside `backend/`, `frontend/`, and `ml/`.
2. Keep the `.agent/` directory name unless your coding tool documents a different supported discovery path.
3. Open/read `AGENTS.md` first, then execute the prompt from `PROMPT_FIX_BACKEND_AND_REDESIGN_UI.md` in the coding agent.
4. If the workspace already has an `AGENTS.md` or `.agent/` content, merge carefully rather than overwrite it. Preserve existing rules and user edits.
5. Review `docs/audit/codebase-audit.md` as an initial audit. The Agent must confirm findings against the current local working tree and update statuses after tests.

The toolkit itself does not change project source code; it provides instructions and an implementation prompt for the coding agent.
