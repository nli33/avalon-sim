import asyncio
import json

from avalon.agents import RandomAgent
from avalon.config import load
from avalon.engine import Game
from avalon.reflect import pov, reflect


class FakeReflector:
    def __init__(self):
        self.prompts = {}

    async def act(self, req):
        self.prompts[req["system"]] = req["prompt"]
        return {"lessons": [{"scope": "role", "kind": "sound_play", "quote": "proposes team", "lesson": "kept"},
                            {"scope": "general", "kind": "missed_signal", "quote": "NOT IN THE TRANSCRIPT", "lesson": "dropped"}]}


def played(tmp_path, seed=3):
    cfg = load("configs/classic5.json")
    path = tmp_path / "game.jsonl"
    game = Game(cfg, RandomAgent(seed), seed, path)
    asyncio.run(game.run())
    return cfg, path, game


def test_pov_shows_only_what_the_player_saw(tmp_path):
    _, _, game = played(tmp_path)
    for p in game.players:
        text = pov(game.events, p.name, p.team)
        assert ("(private evil channel)" in text) <= (p.team == "evil")
        own = [e for e in game.events if e["type"] == "action" and e["player"] == p.name and e["output"].get("notes")]
        assert text.count("[your notes:") == len(own)  # nobody else's notes


def test_reflections_keep_only_quoted_lessons(tmp_path):
    cfg, path, game = played(tmp_path)
    agent = FakeReflector()
    paths = asyncio.run(reflect(path, cfg, agent, "haiku"))
    assert sorted(p.name for p in paths) == sorted(f"{p.role}.md" for p in game.players)
    for p in paths:
        text = p.read_text()
        assert "1 lessons kept, 1 dropped" in text and "kept" in text and "NOT IN THE TRANSCRIPT" not in text
    # the reflecting player sees its own instructions, with its role, and the revealed outcome
    prompt = agent.prompts[f"You are reviewing a game of Avalon in which you played {game.players[0].role}, to improve strategy for that role."]
    assert f"Your secret role: {game.players[0].role}" in prompt and "## Outcome" in prompt
