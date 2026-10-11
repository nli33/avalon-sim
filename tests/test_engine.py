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
        # asks past the turn limit are ignored by design; anything else would be a real fallback
        assert not [e for e in game.events if e["type"] == "fallback" and "ignored ask_to" not in e["error"]]
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


def test_actions_logged_with_parallel_groups(cfg):
    game, _ = play(cfg, RandomAgent(0))
    actions = [e for e in game.events if e["type"] == "action"]
    assert len(actions) == game.calls
    for kind, size in (("vote", len(game.players)),):
        groups = {}
        for a in actions:
            if a["kind"] == kind:
                groups.setdefault(a["group"], []).append(a["player"])
        assert groups and all(len(v) == size for v in groups.values())
    cards = [a for a in actions if a["kind"] == "quest"]
    assert cards and all(a["output"]["card"] in ("success", "fail") for a in cards)
    # every other decision is its own group
    others = [a["group"] for a in actions if a["kind"] not in ("vote", "quest")]
    assert len(others) == len(set(others))


def attempts(game):
    """Per proposal: (discuss actions, chat events) between the proposal and its vote result."""
    out, acts, chats = [], [], []
    for e in game.events:
        if e["type"] == "proposal":
            acts, chats = [], []
        elif e["type"] == "action" and e["kind"] == "discuss":
            acts.append(e)
        elif e["type"] == "chat" and e["vis"] == "public":
            chats.append(e)
        elif e["type"] == "vote_result":
            out.append((acts, chats))
    return out


def test_everyone_speaks_before_every_vote(cfg):
    for seed in range(100):
        game, _ = play(cfg, RandomAgent(seed), seed)
        for acts, _ in attempts(game):
            assert {a["player"] for a in acts} == set(game.names)


def test_asked_player_speaks_next(cfg):
    asked = 0
    for seed in range(100):
        game, _ = play(cfg, RandomAgent(seed), seed)
        for e in game.events:
            if e["type"] == "chat" and e.get("to"):
                asked += 1
                nxt = next(a for a in game.events[e["i"] + 1:] if a["type"] == "action")
                assert (nxt["player"], nxt["kind"]) == (e["to"], "discuss")
    assert asked > 100  # the property was exercised


def test_turn_limits(cfg):
    for seed in range(100):
        game, _ = play(cfg, RandomAgent(seed), seed)
        for acts, chats in attempts(game):
            for n in game.names:
                turns = sum(a["player"] == n for a in acts)
                answers = sum(c.get("to") == n for c in chats)
                assert turns <= cfg.discussion.max_turns + answers


def test_all_ready_means_one_turn_each(cfg):
    ready = lambda r: {"notes": "", "say": "ok", "ask_to": "", "ready_to_vote": True}
    game, _ = play(cfg, Scripted(discuss=ready, vote=lambda r: {"vote": "approve"}))
    for acts, _ in attempts(game):
        assert sorted(a["player"] for a in acts) == sorted(game.names)


def test_everyone_asking_one_player_cannot_silence_others(cfg):
    def ask_alice(r):
        return {"notes": "", "say": "Alice, what do you think?", "ask_to": "Alice" if r["player"] != "Alice" else "",
                "ready_to_vote": True}
    game, result = play(cfg, Scripted(discuss=ask_alice))
    assert result["winner"] in ("good", "evil")
    for acts, _ in attempts(game):
        assert {a["player"] for a in acts} == set(game.names)
    assert any(e["type"] == "chat" and e["player"] == "Alice" and e["reply_to"] for e in game.events)


def test_bad_ask_targets_are_ignored(cfg):
    def bad(r):
        return {"notes": "", "say": "hm", "ask_to": r["player"] if r["player"] != "Alice" else "Nobody",
                "ready_to_vote": True}
    game, _ = play(cfg, Scripted(discuss=bad))
    assert not [e for e in game.events if e["type"] == "chat" and e.get("to")]
    assert any(e["type"] == "fallback" and "ignored ask_to" in e["error"] for e in game.events)


def test_unanswered_question_is_recorded(cfg):
    def mute_when_asked(r):
        asked = "asked you directly" in r["prompt"]
        return {"notes": "", "say": "" if asked else "Bob?", "ask_to": "" if asked else "Bob", "ready_to_vote": True}
    game, _ = play(cfg, Scripted(discuss=lambda r: mute_when_asked(r) if r["player"] == "Bob" else
                                 {"notes": "", "say": "Bob?", "ask_to": "Bob", "ready_to_vote": True}))
    assert any(e["type"] == "chat" and e["text"] == "(no answer)" for e in game.events)
