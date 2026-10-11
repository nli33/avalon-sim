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


def test_prompt_marks_self_and_lists_unknowns(game):
    game.emit("proposal", "public", quest=1, attempt=1, leader=game.names[0], team=game.names[:2], say="go")
    for p in game.players:
        system, prompt = build_view(game, p, "x")
        assert f"{p.name} (you)" in system
        assert sum("(you)" in line for line in prompt.splitlines()) == (p.name in game.names[:2])
        known = {n for names in sees(game, p).values() for n in names}
        unknown = [n for n in game.names if n != p.name and n not in known]
        if unknown:
            assert f"No information about: {', '.join(unknown)}" in system
        assert p.name not in unknown


def test_assassination_phase_is_stated(game):
    game.results = [True, False, True, True]
    game.quest = 4
    _, prompt = build_view(game, game.players[0], "x")
    assert "assassination phase" in prompt and "Quest 5 of 5" not in prompt
