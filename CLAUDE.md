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
- Discussion is engine-scheduled (`Game.discuss`): the asked player speaks next, everyone speaks at least once, per-player turn limit. Question formats shown to agents come from `discussion.question_examples` in the config so they can be ablated or replaced later; the prompt only states that a question should ask for something concrete (answerable and checkable), not what to ask.
- Learned strategy lives in playbooks (`playbooks/<name>/<role id>.md`, one short file per role), never in hand-written prompts. Each playbook is its own git repo (the directory is gitignored here): `--playbook [TEAM=]DIR` plays with one, and after the game (unless `--no-learn`) `learn.learn` has one Sonnet call per role revise that role's file from this game alone (exploit / caution / poor_advice, each edit with a quote) and commits it, so `git -C playbooks/<name> log -p <role>.md` shows what each game changed. Hand edits are committed before the next game, and the setup event records the commit used. A player gets only its own role's file. Files stay short and evidence-backed, with no player names (validated) and no generic Avalon advice. No general notes, no human-in-the-loop step, no automatic evaluation; the user inspects games and diffs. Design in `notes/playbooks.md`.
- Seeds are random by default and recorded in the log (`--seed N` reproduces a game), so seats get different roles each game.
- Sonnet 5.5 refuses (`stop_reason: "refusal"`) when a schema field or prompt asks it to write out its reasoning, or to fill a field in before deciding. Keep `notes` a memory for the next turn; private reasoning already happens in the model's own thinking. A test guards the wording. Check the fallback count printed after each run.
- Prompt wording that fixes a factual confusion (e.g. marking "(you)") is fine. Check effects by comparing logs from the same seed before and after.

## Notes
- Maintain notes regularly via the project-notes skill: `notes/` is a symlink to `~/notes/avalon-sim` (separate repo, commit/push there, not here). Record findings, dead ends, measurements, decisions not obvious from code (e.g. `claude -p` flag behavior, prompt changes and how play changed).

## Git
- Commit messages describe the change itself. Never mention milestone names/numbers.
- No AI attribution in commit messages.
- Don't push unless asked.
