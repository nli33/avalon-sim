import asyncio
import json
import subprocess

from avalon import playbook
from avalon.agents import RandomAgent
from avalon.config import load
from avalon.engine import Game
from avalon.learn import learn, pov


class FakeLearner:
    def __init__(self, text="new notes"):
        self.text, self.prompts = text, {}

    async def act(self, req):
        self.prompts[req["system"]] = req["prompt"]
        return {"text": self.text, "changes": [{"kind": "caution", "quote": "proposes team", "edit": "kept"},
                                               {"kind": "exploit", "quote": "NOT IN THE TRANSCRIPT", "edit": "dropped"}]}


def played(tmp_path, playbooks, seed=3):
    cfg = load("configs/classic5.json")
    game = Game(cfg, RandomAgent(seed), seed, tmp_path / "game.jsonl", playbooks=playbooks)
    asyncio.run(game.run())
    return cfg, game


def commits(path):
    return subprocess.run(["git", "-C", str(path), "log", "--format=%s"], capture_output=True, text=True).stdout.split("\n")[:-1]


def test_pov_shows_only_what_the_player_saw(tmp_path):
    _, game = played(tmp_path, {})
    for p in game.players:
        text = pov(game.events, p.name, p.team)
        assert ("(private evil channel)" in text) <= (p.team == "evil")
        own = [e for e in game.events if e["type"] == "action" and e["player"] == p.name and e["output"].get("notes")]
        assert text.count("[your notes:") == len(own)  # nobody else's notes


def test_learning_commits_each_games_edit_to_the_playbook(tmp_path):
    cfg, root = load("configs/classic5.json"), tmp_path / "pb"
    root.mkdir()
    playbook.save(root, {"merlin.md": "old merlin notes"}, "Initial")
    cfg, game = played(tmp_path, {t: playbook.load(root, cfg) for t in ("good", "evil")})
    agent = FakeLearner()
    [(path, commit)] = asyncio.run(learn(game, agent, "sonnet", "run1"))
    assert path == str(root) and commit
    assert commits(root)[0] == "Update after run1 (" + next(e for e in game.events if e["type"] == "game_over")["winner"] + " won)"
    assert sorted(f.name for f in root.glob("*.md")) == sorted(f"{r}.md" for r in cfg.roles)  # every role has a file now
    body = subprocess.run(["git", "-C", str(root), "log", "-1", "--format=%b"], capture_output=True, text=True).stdout
    assert "caution: kept" in body and "exploit: dropped" in body and "(quote not found)" in body
    # the editor saw the current notes through the instructions the player had, and the outcome
    prompt = agent.prompts[f"You maintain the strategy notes for the merlin role in Avalon (The Resistance), read by whoever plays merlin before every decision in future games."]
    assert "old merlin notes" in prompt and "## Outcome" in prompt
    # nothing changed the second time: no new commit
    _, game2 = played(tmp_path, {t: playbook.load(root, cfg) for t in ("good", "evil")})
    n = len(commits(root))
    asyncio.run(learn(game2, agent, "sonnet", "run2"))
    assert len(commits(root)) == n


def test_manual_edits_are_committed_before_a_game(tmp_path):
    cfg, root = load("configs/classic5.json"), tmp_path / "pb"
    root.mkdir()
    playbook.save(root, {"merlin.md": "v1"}, "Initial")
    (root / "merlin.md").write_text("my edit\n")
    pb = playbook.load(root, cfg)
    assert pb["roles"]["merlin"] == "my edit" and commits(root)[0] == "Manual edits before a game"


def test_notes_naming_players_are_not_applied(tmp_path):
    cfg, root = load("configs/classic5.json"), tmp_path / "pb"
    root.mkdir()
    playbook.save(root, {"merlin.md": "old"}, "Initial")
    _, game = played(tmp_path, {t: playbook.load(root, cfg) for t in ("good", "evil")})
    asyncio.run(learn(game, FakeLearner("watch Alice"), "sonnet", "run1"))
    assert (root / "merlin.md").read_text().strip() == "old"
    assert not any("Alice" in f.read_text() for f in root.glob("*.md"))
