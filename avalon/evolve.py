import asyncio
import json
import re
import shutil
from pathlib import Path

from . import playbook, views
from .agents import RandomAgent
from .engine import Game

WORDS = 350  # per file; players read these before every decision

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text", "changes"], "properties": {
    "text": {"type": "string"}, "changes": {"type": "array", "items": {"type": "string"}}}}

TASK = f"""Rewrite the notes so they take the lessons into account. Players read the notes before every decision in a game, so they must be short ({WORDS} words is a ceiling, not a target; a few lines is fine when there are few lessons), concrete, and usable from a player's own point of view at the moment of a decision: describe evidence a player can actually see and what to do about it.

The lessons were written after games, with every role revealed, so some of their wording rests on knowledge the player did not have then. Keep only what can be stated as observable evidence; never rely on knowing who anyone really is. Each lesson comes from a single game and can be wrong: prefer patterns that recur or follow clearly from the rules, keep what still holds from the current notes, merge duplicates, and drop what the lessons contradict or what is specific to one game. Refer to roles and situations, never to player names.

Every point in the notes must rest on a lesson or on the current notes. Do not add advice from your own general knowledge of Avalon or restate the rules, even to make the notes feel complete: thin notes are expected at this stage.

Return the full new notes as markdown in `text`. In `changes`, give one line per edit (added, merged, removed or rewritten) with the quote it rests on."""


def read_lessons(game_dir):
    """Every lesson in <game_dir>/reflections as (role that wrote it, scope, text), plus who won."""
    over = next(json.loads(l) for l in open(Path(game_dir) / "game.jsonl") if '"game_over"' in l)
    found = []
    for f in sorted((Path(game_dir) / "reflections").glob("*.md")):
        for block in re.split(r"(?m)^(?=## )", f.read_text())[1:]:
            found.append((f.stem, re.match(r"## \d+\. (\w+),", block).group(1), block.strip()))
    return over["winner"], found


async def evolve(name, parent, game_dirs, steer, cfg, agent, model, root="playbooks"):
    """Write playbooks/<name> from the parent playbook (or nothing) and the lessons in the given games. Files
    without new lessons are carried over unchanged; a steer text makes every file get rewritten."""
    out = Path(root) / name
    if out.exists():
        raise ValueError(f"{out} already exists; playbooks are never overwritten")
    old = playbook.load(parent, cfg) if parent else {"general": "", "roles": {}}
    games = [read_lessons(d) for d in game_dirs]
    rules = Game(cfg, RandomAgent(), 0)

    async def rewrite(target):
        """target is "general" or a role id. Returns (new text, changes)."""
        current = old["general"] if target == "general" else old["roles"].get(target, "")
        mine = [(i, w, role, text) for i, (w, found) in enumerate(games, 1) for role, scope, text in found
                if (scope == "general") == (target == "general") and (target == "general" or role == target)]
        if not mine and not steer:
            return current, []
        player = next((p for p in rules.players if p.role == target), rules.players[0])
        lessons = "\n\n".join(f"### Game {i} ({w} won), written by the {role} player\n{text}" for i, w, role, text in mine)
        for_what = "for every role" if target == "general" else f"for the {target} role"
        res = await agent.act({"model": model, "schema": SCHEMA,
                               "system": f"You maintain the strategy notes {for_what} in Avalon (The Resistance).",
                               "prompt": f"""## What players are told in a game
{views.build_view(rules, player, "")[0]}

## Current notes
{current or "(none yet)"}

## Lessons from recent games
{lessons or "(none)"}

## Guidance from the maintainer
{steer or "(none)"}

## Your task
{TASK}"""})
        return res["text"].strip(), res["changes"]

    targets = ["general", *cfg.roles]
    results = await asyncio.gather(*(rewrite(t) for t in targets))
    (out / "roles").mkdir(parents=True)
    changelog = []
    for target, (text, changes) in zip(targets, results):
        if text:
            (out / ("general.md" if target == "general" else f"roles/{target}.md")).write_text(text + "\n")
        changelog.append(f"## {target} ({len(text.split())} words)\n" + ("\n".join(f"- {c}" for c in changes) or "- unchanged"))
    (out / "CHANGELOG.md").write_text("\n\n".join(changelog) + "\n")
    (out / "meta.json").write_text(json.dumps({"parent": parent, "games": [str(d) for d in game_dirs], "model": model,
                                               "steered": bool(steer)}, indent=2) + "\n")
    try:
        playbook.load(out, cfg)
    except ValueError:
        shutil.rmtree(out)
        raise
    return out
