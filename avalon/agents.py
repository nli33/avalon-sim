import asyncio
import json
import random
import tempfile


class RandomAgent:
    """Free, instant stand-in for the LLM agents; used for tests and --dry-run."""

    def __init__(self, seed=0):
        self.rng = random.Random(seed)

    async def act(self, req):
        kind, ctx = req["kind"], req["ctx"]
        if kind == "discuss":
            others = [n for n in ctx["names"] if n != req["player"]]
            return {"notes": "random", "say": self.rng.choice(["Sounds fine to me.", "I'm not sure about this.", "Thoughts?"]),
                    "ask_to": self.rng.choice(["", "", *others]), "ready_to_vote": self.rng.random() < 0.6}
        if kind == "evil_chat":
            return {"say": self.rng.choice(["Sounds fine to me.", "I'm not sure about this.", ""]), "notes": "random"}
        if kind == "propose":
            return {"team": self.rng.sample(ctx["names"], ctx["size"]), "say": "My pick.", "notes": "random"}
        if kind == "vote":
            return {"vote": self.rng.choice(["approve", "reject"]), "notes": "random"}
        if kind == "quest":
            return {"card": self.rng.choice(ctx["cards"]), "notes": "random"}
        return {"target": self.rng.choice([n for n in ctx["names"] if n != req["player"]]), "reasoning": "random"}


class ClaudeCLIAgent:
    """One `claude -p` subprocess per decision, with no tools and no persisted session."""

    def __init__(self, concurrency=3, timeout=180):
        self.sem = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.cwd = tempfile.mkdtemp(prefix="avalon-")  # empty dir so no project CLAUDE.md is picked up
        self.cost = 0.0

    async def act(self, req):
        cmd = ["claude", "-p", req["prompt"], "--model", req["model"], "--system-prompt", req["system"],
               "--tools", "", "--strict-mcp-config", "--no-session-persistence", "--setting-sources", "",
               "--output-format", "json", "--json-schema", json.dumps(req["schema"])]
        err = None
        for _ in range(2):
            async with self.sem:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, cwd=self.cwd, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), self.timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    err = "timeout"
                    continue
            try:
                env = json.loads(stdout)
                self.cost += env.get("total_cost_usd") or 0
                return env["structured_output"]
            except (ValueError, KeyError, TypeError):
                err = f"bad output: {stdout[:200]!r} {stderr[:200]!r}"
        raise RuntimeError(err)
