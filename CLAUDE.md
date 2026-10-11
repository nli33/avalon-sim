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

## Prompts
- Prompts state rules, role facts, what the player knows, and game state. They do not contain tactical advice ("lie about X", "stay hidden", "fail sparingly"). Strategy is the agent's job; later we may add a store of learned strategies written by an agent that reviews games.
- Beware hindsight when writing or learning from strategies: something obvious to an observer who knows every role may be non-obvious from one player's view. Judge play against what that player could know (the per-player `sees` info and the public transcript), not the final role reveal.
- Prompt wording that fixes a factual confusion (e.g. marking "(you)") is fine. Check effects by comparing logs from the same seed before and after.

## Notes
- Maintain notes regularly via the project-notes skill: `notes/` is a symlink to `~/notes/avalon-sim` (separate repo, commit/push there, not here). Record findings, dead ends, measurements, decisions not obvious from code (e.g. `claude -p` flag behavior, prompt changes and how play changed).

## Git
- Commit messages describe the change itself. Never mention milestone names/numbers.
- No AI attribution in commit messages.
- Don't push unless asked.
