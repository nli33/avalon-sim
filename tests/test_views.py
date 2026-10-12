import pytest

from avalon.agents import RandomAgent
from avalon.config import load
from avalon import playbook
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


def test_directed_chat_is_rendered_and_question_goes_to_asked_player(game):
    game.emit("chat", "public", player="Alice", text="Fine by me.", to="Bob", question="Who would you pick?",
              reply_to=None, quest=1, attempt=1)
    game.emit("chat", "public", player="Bob", text="Cara.", to=None, question=None, reply_to="Alice", quest=1, attempt=1)
    _, prompt = build_view(game, game.players[1], "x")  # Bob
    assert 'Alice: "Fine by me." [asks Bob (you): "Who would you pick?"]' in prompt
    assert 'Bob (you) (answering Alice): "Cara."' in prompt
    bob = game.players[1]
    text = game.discussion_prompt(bob, ["Alice", "Bob"], {n: 0 for n in game.names}, ("Bob", "Alice", "who would you pick?"))
    assert 'Alice asked you directly' in text
    assert "asked you directly" not in game.discussion_prompt(game.players[0], ["Alice"], {n: 0 for n in game.names}, None)


def test_question_examples_come_from_config(game):
    prompt = lambda: game.discussion_prompt(game.players[0], ["Alice"], {n: 0 for n in game.names}, None)
    assert "question formats" not in prompt()  # the shipped config has none
    game.cfg.discussion.question_examples = ["If this fails, who would you propose?"]
    assert "- If this fails, who would you propose?" in prompt()


def test_playbook_goes_to_its_team_and_role_only(game):
    pb = playbook.load("tests/playbooks/sample", game.cfg)
    game.playbooks = {"good": pb}
    for p in game.players:
        system = build_view(game, p, "x")[0]
        assert ("GENERAL-MARKER" in system) == (p.team == "good")
        assert ("MERLIN-MARKER" in system) == (p.role == "merlin")
        assert "ASSASSIN-MARKER" not in system  # evil has no playbook in this game


def test_no_playbook_leaves_prompt_unchanged(game):
    assert "Lessons" not in build_view(game, game.players[0], "x")[0]


def test_playbook_rejects_player_names_and_unknown_roles(game, tmp_path):
    (tmp_path / "general.md").write_text("Be wary of Alice.")
    with pytest.raises(ValueError, match="Alice"):
        playbook.load(tmp_path, game.cfg)
    (tmp_path / "general.md").write_text("fine")
    (tmp_path / "roles").mkdir()
    (tmp_path / "roles" / "wizard.md").write_text("x")
    with pytest.raises(ValueError, match="wizard"):
        playbook.load(tmp_path, game.cfg)
