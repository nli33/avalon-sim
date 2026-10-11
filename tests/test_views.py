import pytest

from avalon.agents import RandomAgent
from avalon.config import load
from avalon.engine import Game
from avalon.views import build_view, sees


@pytest.fixture
def game():
    return Game(load("configs/classic5.json"), RandomAgent(), seed=4)


def by_role(game, role):
    return next(p for p in game.players if p.role == role)


def test_visibility_matches_config(game):
    name = lambda r: by_role(game, r).name
    assert set(sees(game, by_role(game, "merlin"))["evil"]) == {name("morgana"), name("assassin")}
    assert sees(game, by_role(game, "john")) == {"Percival": [name("percival")]}
    assert set(sees(game, by_role(game, "percival"))["Merlin or Morgana"]) == {name("merlin"), name("morgana")}
    assert sees(game, by_role(game, "morgana")) == {"evil": [name("assassin")]}
    assert sees(game, by_role(game, "assassin")) == {"evil": [name("morgana")]}


def test_percival_order_does_not_leak(game):
    """Across seeds, Merlin must not systematically come first in Percival's list."""
    firsts = set()
    for seed in range(40):
        g = Game(game.cfg, RandomAgent(), seed=seed)
        pv = by_role(g, "percival")
        firsts.add(sees(g, pv)["Merlin or Morgana"][0] == by_role(g, "merlin").name)
    assert firsts == {True, False}


def test_evil_channel_only_visible_to_evil(game):
    game.emit("chat", "evil", player=by_role(game, "morgana").name, text="SECRETPLAN")
    for p in game.players:
        _, prompt = build_view(game, p, "x")
        assert ("SECRETPLAN" in prompt) == (p.team == "evil")


def test_private_notes_not_shared(game):
    a, b = game.players[:2]
    game.notes[a.name] = "MYNOTES"
    assert "MYNOTES" in build_view(game, a, "x")[1]
    assert "MYNOTES" not in build_view(game, b, "x")[1]
