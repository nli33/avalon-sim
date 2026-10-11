import asyncio
import random

import pytest

from avalon.agents import RandomAgent
from avalon.config import load
from avalon.engine import Game


@pytest.fixture
def cfg():
    return load("configs/classic5.json")


def play(cfg, agent, seed=0):
    game = Game(cfg, agent, seed)
    return game, asyncio.run(game.run())


def test_random_games_terminate(cfg):
    winners = set()
    for seed in range(100):
        game, result = play(cfg, RandomAgent(seed), seed)
        winners.add(result["winner"])
        assert result["winner"] in ("good", "evil")
        assert not [e for e in game.events if e["type"] == "fallback"]
    assert winners == {"good", "evil"}


def test_roles_assigned_once(cfg):
    game = Game(cfg, RandomAgent(), seed=3)
    assert sorted(p.role for p in game.players) == sorted(cfg.roles)


def test_quest_sizes_and_good_cannot_fail(cfg):
    for seed in range(50):
        game, _ = play(cfg, RandomAgent(seed), seed)
        teams = {p.name: p.team for p in game.players}
        for e in game.events:
            if e["type"] == "quest_result":
                assert len(e["team"]) == cfg.quest_sizes[e["quest"] - 1]
                assert e["fails"] <= sum(teams[n] == "evil" for n in e["team"])


class Scripted(RandomAgent):
    """Random agent with overrides per kind: fn(req) -> dict."""

    def __init__(self, **overrides):
        super().__init__()
        self.overrides = overrides

    async def act(self, req):
        fn = self.overrides.get(req["kind"])
        return fn(req) if fn else await super().act(req)


def test_five_rejections_evil_wins(cfg):
    _, result = play(cfg, Scripted(vote=lambda r: {"vote": "reject"}))
    assert result["winner"] == "evil" and "rejected" in result["reason"]


def test_good_cheating_card_is_ignored(cfg):
    agent = Scripted(vote=lambda r: {"vote": "approve"}, quest=lambda r: {"card": "fail"})
    game, result = play(cfg, agent)
    for e in game.events:
        if e["type"] == "quest_result":
            teams = {p.name: p.team for p in game.players}
            assert e["fails"] == sum(teams[n] == "evil" for n in e["team"])


def test_assassination_correct_and_wrong(cfg):
    approve = lambda r: {"vote": "approve"}
    succeed = lambda r: {"card": "success"}
    game = Game(cfg, RandomAgent(), seed=1)
    merlin = next(p.name for p in game.players if p.role == "merlin")
    guess = lambda r: {"target": merlin}
    game = Game(cfg, Scripted(vote=approve, quest=succeed, assassinate=guess), seed=1)
    assert asyncio.run(game.run())["winner"] == "evil"
    wrong = next(p.name for p in game.players if p.role == "john")
    game = Game(cfg, Scripted(vote=approve, quest=succeed, assassinate=lambda r: {"target": wrong}), seed=1)
    assert asyncio.run(game.run())["winner"] == "good"


def test_invalid_outputs_fall_back(cfg):
    agent = Scripted(propose=lambda r: {"team": ["Nobody"]}, vote=lambda r: {"vote": "approve"})
    game, result = play(cfg, agent)
    assert any(e["type"] == "fallback" for e in game.events)
    assert result["winner"] in ("good", "evil")


def test_agent_exception_falls_back(cfg):
    def boom(r):
        raise RuntimeError("boom")
    game, result = play(cfg, Scripted(discuss=boom))
    assert any(e["type"] == "fallback" for e in game.events)
