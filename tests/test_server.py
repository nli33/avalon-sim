import asyncio
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from avalon.agents import RandomAgent
from avalon.config import load
from avalon.engine import Game
from avalon.server import serve


def test_server_lists_and_serves_games(tmp_path):
    (tmp_path / "g1").mkdir()
    game = Game(load("configs/classic5.json"), RandomAgent(1), 1, tmp_path / "g1" / "game.jsonl")
    asyncio.run(game.run())
    port = 18765
    threading.Thread(target=serve, args=(tmp_path, port), daemon=True).start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    get = lambda p: urllib.request.urlopen(base + p).read().decode()
    assert json.loads(get("/api/games")) == ["g1"]
    lines = get("/api/games/g1").splitlines()
    assert json.loads(lines[0])["type"] == "setup" and json.loads(lines[-1])["type"] == "game_over"
    assert "<html" in get("/")
    with pytest.raises(urllib.error.HTTPError):
        get("/api/games/..%2F..%2Fetc")
