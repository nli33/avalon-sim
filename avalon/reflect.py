import asyncio
import json
import re
from pathlib import Path

from . import playbook, views
from .agents import RandomAgent
from .engine import Game

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["lessons"], "properties": {"lessons": {
    "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["scope", "kind", "quote", "lesson"],
                               "properties": {"scope": {"enum": ["role", "general"]},
                                              "kind": {"enum": ["missed_signal", "sound_play"]},
                                              "quote": {"type": "string"}, "lesson": {"type": "string"}}}}}}

TASK = """The game is over and every role is now revealed. The point is better Avalon strategy, for your role and for the game in general. Player names mean nothing: they are reshuffled every game, so lessons must refer to roles, to seats relative to the leader, and to situations, never to names.

Each lesson has a scope: "role" if it helps anyone who plays your role, "general" if it helps any role (for example how to read votes or quest results).

Judge your play only against what you knew when you acted. The reveal tells you which signals were real, but a lesson is only worth keeping if the information was available to you at the time. There are two kinds:
- missed_signal: something visible to you then (a vote, a message, a quest result, your own earlier notes) that pointed toward the truth and that you did not act on or misread, and what to look for next time.
- sound_play: a decision that was reasonable given what you knew, including one that turned out badly, and why it was reasonable.

Every lesson needs a quote: the exact words from the transcript or your notes that the lesson rests on. Skip any lesson you cannot back with a quote. Fewer, sharper lessons are better."""


def pov(events, me, team):
    """The game as `me` experienced it: what they saw, their own notes and the cards they played."""
    lines = []
    for ev in events:
        if ev["type"] == "action" and ev["player"] == me:
            if ev["output"].get("card"):
                lines.append(f'[you played {ev["output"]["card"]}]')
            if ev["output"].get("notes"):
                lines.append(f'[your notes: {ev["output"]["notes"]}]')
        elif ev["type"] == "assassination":
            lines.append(f'{ev["assassin"]} (assassin) names {ev["target"]} as merlin')
        elif ev["vis"] == "public" or (ev["vis"] == "evil" and team == "evil"):
            if line := views.render(ev, me):
                lines.append(line)
    return "\n".join(lines)


async def reflect(log_path, cfg, agent, model):
    """One reflection per role, written to <game dir>/reflections/<role>.md (each role is played by one player)."""
    events = [json.loads(line) for line in open(log_path)]
    setup, over = events[0], next(e for e in events if e["type"] == "game_over")
    game = Game(cfg, RandomAgent(), setup["seed"], playbooks={t: playbook.load(p, cfg) for t, p in setup["playbooks"].items()})
    if [(p.name, p.role) for p in game.players] != [(p["name"], p["role"]) for p in setup["players"]]:
        raise ValueError("config no longer reproduces the roles of this game")
    out_dir = Path(log_path).parent / "reflections"
    out_dir.mkdir(exist_ok=True)

    async def one(player):
        seen = pov(events, player.name, player.team)
        prompt = f"""## The instructions you were given during the game
{views.build_view(game, player, "")[0]}

## The game as you experienced it
{seen}

## Outcome
{over["winner"].upper()} won: {over["reason"]}
Roles: {", ".join(f"{n}={r}" for n, r in over["roles"].items())}

## Your task
{TASK}"""
        system = f"You are reviewing a game of Avalon in which you played {player.role}, to improve strategy for that role."
        res = await agent.act({"prompt": prompt, "system": system, "model": model, "schema": SCHEMA})
        squash = lambda s: " ".join(s.split())
        kept = [l for l in res["lessons"] if squash(l["quote"]) and squash(l["quote"]) in squash(seen)]
        names = re.compile(r"\b(" + "|".join(p.name for p in game.players) + r")\b")
        parts = [f"# {player.role} ({player.team}), {over['winner']} won ({over['reason']})\n",
                 f"{len(kept)} lessons kept, {len(res['lessons']) - len(kept)} dropped because the quote is not in what "
                 "this role saw. Edit or delete lessons freely before evolving a playbook.\n"]
        for i, l in enumerate(kept, 1):
            warn = " (mentions a player name)" if names.search(l["lesson"]) else ""
            parts.append(f"## {i}. {l['scope']}, {l['kind'].replace('_', ' ')}{warn}\n\n> {l['quote']}\n\n{l['lesson']}\n")
        path = out_dir / f"{player.role}.md"
        path.write_text("\n".join(parts))
        return path

    return await asyncio.gather(*(one(p) for p in game.players))
