# avalon-sim

Multi-agent Avalon (The Resistance) simulation. Every player is an LLM agent run through `claude -p`. Roles and visibility are configured in JSON. Plan: `~/.claude/plans/scope-out-a-multi-agent-quiet-lemon.md`.

## Code style
- Keep it simple. Plain functions in a few flat modules. No multi-layer abstractions, wrappers around wrappers, or classes that only forward calls.
- Don't spam `_private_helper` functions. Inline code until a helper is clearly needed (used in 2+ places or genuinely hard to read inline).
- Add abstraction only when it has proven necessary, not in anticipation.
- No LangChain/LangGraph. The engine is plain asyncio + pydantic and talks to agents through a single `act(view, schema)` interface.

## Game invariants
- Hidden information flows through one place only: `build_view`. Never put another player's role in a prompt unless the config's `sees` says so.
- Anything that changes game outcome (quest sizes, win conditions, who can play fail) is enforced by the engine and schemas, never trusted to the agent.

## Notes
- Maintain notes regularly via the project-notes skill: `notes/` is a symlink to `~/notes/avalon-sim` (separate repo, commit/push there, not here). Record findings, dead ends, measurements, decisions not obvious from code (e.g. `claude -p` flag behavior, prompt changes and how play changed).

## Git
- Commit messages describe the change itself. Never mention milestone names/numbers.
- No AI attribution in commit messages.
- Don't push unless asked.
