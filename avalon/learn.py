import asyncio
import re
from pathlib import Path

from . import playbook, views

WORDS = 350  # per role file; players read it before every decision

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["text", "changes"], "properties": {
    "text": {"type": "string"},
    "changes": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "required": ["kind", "quote", "edit"],
                                           "properties": {"kind": {"enum": ["exploit", "caution", "poor_advice"]},
                                                          "quote": {"type": "string"}, "edit": {"type": "string"}}}}}}

TASK = f"""The game is over and every role is now revealed. Revise the strategy notes for the {{role}} role using only this game. The notes the player had (if any) are in the instructions above. Look for three things:
- exploit: something in how the other players behaved that this role can use next time.
- caution: something this role should have been more careful about.
- poor_advice: advice in the current notes that this game showed to be misleading or harmful; fix or remove it.

Judge by what the player could see when they acted. The reveal tells you which signals were real, but a note is only worth writing if it can be stated as evidence a player can observe and what to do about it, never as knowledge of who anyone really is. One game is weak evidence: phrase new points conditionally, and keep well-supported old advice unless this game clearly contradicts it. Every point must rest on this game or on the current notes; do not add generic Avalon advice or restate the rules. Keep the notes short ({WORDS} words is a ceiling, not a target). Player names are reshuffled every game, so refer to roles and situations, never to names.

Return the complete revised notes as markdown in `text`. In `changes`, give one entry per edit: its kind, the exact quote from the transcript, your notes or the current notes that it rests on, and a one-line description. If nothing should change, return the notes as they were and no changes."""


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


async def learn(game, agent, model, run_dir):
    """After a game, every role whose team used a playbook revises its notes from this game alone. The edits are
    committed in each playbook's own git repo, with the game and where the edit came from in the message.
    Returns [(playbook path, commit)]."""
    over = next(e for e in game.events if e["type"] == "game_over")
    squash = lambda s: " ".join(s.split())
    names = re.compile(r"\b(" + "|".join(game.names) + r")\b")

    async def one(player):
        pb = game.playbooks[player.team]
        current = pb["roles"].get(player.role, "")
        seen = pov(game.events, player.name, player.team)
        prompt = f"""## The instructions the {player.role} player was given
{views.build_view(game, player, "")[0]}

## The game as the {player.role} player experienced it
{seen}

## Outcome
{over["winner"].upper()} won: {over["reason"]}
Roles: {", ".join(f"{n}={r}" for n, r in over["roles"].items())}

## Your task
{TASK.format(role=player.role)}"""
        system = (f"You maintain the strategy notes for the {player.role} role in Avalon (The Resistance), read by "
                  f"whoever plays {player.role} before every decision in future games.")
        res = await agent.act({"prompt": prompt, "system": system, "model": model, "schema": SCHEMA})
        text, lines = res["text"].strip(), []
        evidence = squash(seen + "\n" + current)
        for c in res["changes"]:
            found = squash(c["quote"]) and squash(c["quote"]) in evidence
            lines.append(f"{player.role} {c['kind']}: {c['edit']} [\"{c['quote']}\"]" + ("" if found else " (quote not found)"))
        if text != current and names.search(text):
            lines.append(f"{player.role}: NOT APPLIED, the new notes mention the player name {names.search(text).group(1)!r}")
            text = current
        return pb["path"], player.role, text, current, lines

    run = Path(run_dir)
    edits = {}  # playbook path -> (files, edit lines, roles that were played)
    for path, role, text, current, lines in await asyncio.gather(*(one(p) for p in game.players if p.team in game.playbooks)):
        files, notes, roles = edits.setdefault(path, ({}, [], []))
        if text and text != current:
            files[f"{role}.md"] = text
        notes += lines
        roles.append(role)
    commits = []
    for path, (files, notes, roles) in edits.items():
        used = next(pb["commit"] for pb in game.playbooks.values() if pb["path"] == path)
        message = f"""Learn from game {run.name}: {over['winner']} won, edited {', '.join(sorted(f[:-3] for f in files)) or 'nothing'}

Game: {run.name} ({run / 'game.jsonl'})
Seed: {game.seed}
Result: {over['winner']} won, {over['reason']}
Playbook used in this game: {used}
Player model(s): {', '.join(sorted({p.model for p in game.players}))}; learner model: {model}
Roles reviewed: {', '.join(sorted(roles))}
Origin: post-game learn step (avalon/learn.py), one call per role, each seeing only that role's view of this game

""" + "\n".join(notes)
        commits.append((path, playbook.save(path, files, message)))
    return commits
