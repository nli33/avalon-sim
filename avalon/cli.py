import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console

from . import views
from .agents import ClaudeCLIAgent, RandomAgent
from .config import load
from .engine import Game

console = Console(highlight=False)


def show(ev, notes=True):
    t = ev["type"]
    if t == "action" and not notes:
        return
    if t == "setup":
        console.print("[bold]Roles[/bold] (spectator view): " + ", ".join(f'{p["name"]}={p["role"]}' for p in ev["players"]))
    elif t == "action":
        if ev["output"].get("notes"):
            console.print(f'  [dim]{ev["player"]} notes: {ev["output"]["notes"]}[/dim]')
    elif t == "fallback":
        console.print(f'  [red]fallback {ev["player"]} {ev["kind"]}: {ev["error"]}[/red]')
    elif t == "assassination":
        console.print(f'[bold magenta]{ev["assassin"]} assassinates {ev["target"]}: '
                      f'{"correct" if ev["correct"] else "wrong"}[/bold magenta] [dim]{ev["reasoning"]}[/dim]')
    elif t == "game_over":
        console.print(f'[bold green]{ev["winner"].upper()} wins:[/bold green] {ev["reason"]}')
    elif line := views.render(ev):
        console.print(f"[yellow]{line}[/yellow]" if ev["vis"] == "evil" else line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/classic5.json")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="random agents instead of claude")
    ap.add_argument("--model", help="override every player's model")
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--out", default="runs")
    ap.add_argument("--serve", action="store_true", help="serve the web replay viewer for games in --out")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--replay", metavar="GAME.JSONL", help="print a saved game instead of running one")
    ap.add_argument("--no-notes", action="store_true", help="with --replay: hide players' private notes")
    args = ap.parse_args()

    if args.serve:
        from .server import serve
        serve(args.out, args.port)
        return

    if args.replay:
        for line in open(args.replay):
            show(json.loads(line), notes=not args.no_notes)
        return

    cfg = load(args.config)
    if args.model:
        cfg.default_model = args.model
        for p in cfg.players:
            p.model = None
    agent = RandomAgent(args.seed) if args.dry_run else ClaudeCLIAgent(args.concurrency)
    out = Path(args.out) / f"{datetime.now():%Y%m%d-%H%M%S}-seed{args.seed}"
    out.mkdir(parents=True)
    game = Game(cfg, agent, args.seed, out / "game.jsonl", show)
    start = time.time()
    result = asyncio.run(game.run())
    cost = getattr(agent, "cost", 0)
    fallbacks = sum(e["type"] == "fallback" for e in game.events)
    console.print(f"{result['calls']} agent calls ({fallbacks} fallbacks), {time.time() - start:.0f}s, "
                  f"list-price ${cost:.2f}, log: {out / 'game.jsonl'}")
