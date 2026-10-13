import asyncio
import json

import pytest

from avalon import playbook
from avalon.config import load
from avalon.evolve import evolve, read_lessons


class FakeEditor:
    def __init__(self, text="new notes"):
        self.text, self.calls = text, []

    async def act(self, req):
        self.calls.append(req)
        return {"text": self.text, "changes": ["added: something"]}


@pytest.fixture
def game_dir(tmp_path):
    d = tmp_path / "run"
    (d / "reflections").mkdir(parents=True)
    (d / "game.jsonl").write_text(json.dumps({"type": "game_over", "winner": "evil"}) + "\n")
    (d / "reflections" / "merlin.md").write_text("# merlin\n\n## 1. role, missed signal\n\n> q\n\nrole lesson\n\n"
                                                 "## 2. general, sound play\n\n> q\n\ngeneral lesson\n")
    return d


def test_lessons_are_split_by_role_and_scope(game_dir):
    winner, found = read_lessons(game_dir)
    assert winner == "evil" and [(r, s) for r, s, _ in found] == [("merlin", "role"), ("merlin", "general")]


def test_evolve_rewrites_only_files_with_lessons_and_never_overwrites(game_dir, tmp_path):
    cfg, agent = load("configs/classic5.json"), FakeEditor()
    parent = tmp_path / "parent"
    (parent / "roles").mkdir(parents=True)
    (parent / "roles" / "percival.md").write_text("old percival notes")
    out = asyncio.run(evolve("child", str(parent), [game_dir], "", cfg, agent, "haiku", root=tmp_path / "pb"))
    assert len(agent.calls) == 2  # general and merlin only
    assert (out / "roles" / "percival.md").read_text().strip() == "old percival notes"  # carried over
    assert (out / "roles" / "merlin.md").read_text().strip() == "new notes"
    assert not (out / "roles" / "john.md").exists()
    assert json.loads((out / "meta.json").read_text())["parent"] == str(parent)
    assert "added: something" in (out / "CHANGELOG.md").read_text()
    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(evolve("child", str(parent), [game_dir], "", cfg, agent, "haiku", root=tmp_path / "pb"))


def test_steer_rewrites_every_file_and_names_are_rejected(game_dir, tmp_path):
    cfg, agent = load("configs/classic5.json"), FakeEditor()
    asyncio.run(evolve("a", None, [game_dir], "focus on voting", cfg, agent, "haiku", root=tmp_path / "pb"))
    assert len(agent.calls) == 1 + len(cfg.roles)
    with pytest.raises(ValueError, match="Alice"):
        asyncio.run(evolve("b", None, [game_dir], "", cfg, FakeEditor("watch Alice"), "haiku", root=tmp_path / "pb"))
    assert not (tmp_path / "pb" / "b").exists()
