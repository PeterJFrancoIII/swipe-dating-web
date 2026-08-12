# Swipe Dating agent operating contract

## Authority order
1. `PRODUCT_SCOPE.md` is the canonical product master. No agent may contradict or silently expand it.
2. `agent_memory/STATE.json` is the canonical operational state.
3. `agent_memory/ACTIVE_TASK.json` selects the only task Cursor may execute.
4. The selected `agent_memory/tasks/<task-id>.json` is the bounded implementation contract.
5. `agent_memory/DECISIONS.ndjson` is append-only architectural history.

## Mandatory Cursor start protocol
Before analysis, edits, terminal commands, or tests, read the four authorities above and the active task. Then emit exactly one machine-readable acknowledgement:

`MEMORY_ACK {"head":"<git-head-sha>","refs":["PRODUCT_SCOPE.md@<head>","agent_memory/STATE.json@<head>","agent_memory/ACTIVE_TASK.json@<head>","<task-path>@<head>"]}`

If there is no active assigned task, the task file is missing, the branch/ref does not match, or the requested work exceeds the task packet: STOP and report `BLOCKED_SCOPE`.

## Roles
- Product owner: UI tester and product decision-maker. Coding, terminal, Git, CI, and repository operations are NOT expected from the product owner. Never delegate those operations to them. Ask only for UI observations, preferences, or explicit product decisions.
- Architect: ChatGPT. Owns architecture, task packets, acceptance review, shared-memory state, and scope decisions.
- Implementer: Cursor. Executes only the active task, cites shared memory, gathers evidence, and never self-assigns or self-approves.

## Scope and Git rules
- Edit only `allowed_writes` in the active task.
- Treat every other path as read-only unless the active task explicitly says otherwise.
- Never change `PRODUCT_SCOPE.md` unless the task explicitly names it and records product-owner authorization.
- Never merge a PR.
- Commit/push only when `git_write_policy` explicitly permits it, and only the permitted paths.
- Do not weaken tests, CI, governance, safety boundaries, coverage thresholds, or release blocks to make work pass.

## Completion protocol
- Produce the exact evidence requested by the task.
- If an evidence file is authorized, write it using the task's evidence schema.
- End Cursor's response with `MEMORY_CITATIONS` listing the same authoritative refs plus any evidence path, then `ready_for_architect_review`.
- `ready_for_architect_review` is not acceptance. Only the architect accepts work.

## Human-facing rule
When owner UI testing is requested, Cursor performs all setup and supplies a clickable local/preview URL plus UI-only actions. Never ask the owner to type commands, edit files, resolve Git, or interpret CI logs.
