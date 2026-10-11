import asyncio
import json
import random
from dataclasses import dataclass

from . import views


@dataclass
class Player:
    name: str
    role: str
    team: str
    model: str


def schema(kind, names=(), cards=("success", "fail")):
    s = lambda: {"type": "string"}
    props = {
        "discuss": {"say": s(), "notes": s()},
        "evil_chat": {"say": s(), "notes": s()},
        "propose": {"team": {"type": "array", "items": {"enum": list(names)}}, "say": s(), "notes": s()},
        "vote": {"vote": {"enum": ["approve", "reject"]}, "notes": s()},
        "quest": {"card": {"enum": list(cards)}, "notes": s()},
        "assassinate": {"target": {"enum": list(names)}, "reasoning": s()},
    }[kind]
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class Game:
    def __init__(self, cfg, agent, seed=0, log_path=None, on_event=None):
        self.cfg, self.agent, self.seed, self.on_event = cfg, agent, seed, on_event
        self.rng = random.Random(seed)
        roles = list(cfg.roles)
        self.rng.shuffle(roles)
        self.players = [Player(p.name, r, cfg.roles[r].team, p.model or cfg.default_model)
                        for p, r in zip(cfg.players, roles)]
        self.names = [p.name for p in self.players]
        self.notes = {p.name: "" for p in self.players}
        self.events = []
        self.leader = self.rng.randrange(len(self.players))
        self.quest = 0  # index of the quest being played
        self.rejects = 0
        self.results = []  # True = quest succeeded
        self.calls = 0
        self.log = open(log_path, "w") if log_path else None

    def emit(self, type, vis, **data):
        ev = {"i": len(self.events), "type": type, "vis": vis, **data}
        self.events.append(ev)
        if self.log:
            self.log.write(json.dumps(ev) + "\n")
            self.log.flush()
        if self.on_event:
            self.on_event(ev)

    async def ask(self, player, kind, instruction, size=0, cards=("success", "fail")):
        """One agent decision. Returns the agent's dict, or {} if the call failed."""
        system, prompt = views.build_view(self, player, instruction)
        req = {"kind": kind, "player": player.name, "model": player.model, "system": system, "prompt": prompt,
               "schema": schema(kind, self.names, cards),
               "ctx": {"names": self.names, "size": size, "cards": list(cards)}}
        self.calls += 1
        try:
            out = await self.agent.act(req)
        except Exception as e:
            self.emit("fallback", "hidden", player=player.name, kind=kind, error=str(e))
            return {}
        if out.get("notes") is not None:
            self.notes[player.name] = str(out["notes"])
            self.emit("notes", "hidden", player=player.name, notes=self.notes[player.name])
        return out

    def seat(self, start):
        """Players in seat order beginning at index start."""
        n = len(self.players)
        return [self.players[(start + i) % n] for i in range(n)]

    async def chat(self, player, kind, instruction):
        out = await self.ask(player, kind, instruction)
        text = str(out.get("say") or "").strip()
        if text and kind == "discuss":
            self.emit("chat", "public", player=player.name, text=text, quest=self.quest + 1, attempt=self.rejects + 1)
        elif text:
            self.emit("chat", "evil", player=player.name, text=text)

    async def run(self):
        cfg, n = self.cfg, len(self.players)
        need = len(cfg.quest_sizes) // 2 + 1
        self.emit("setup", "hidden", seed=self.seed, leader=self.players[self.leader].name,
                  players=[vars(p) for p in self.players])
        while True:
            wins = sum(self.results)
            if wins == need:
                winner, reason = await self.assassinate()
                break
            if len(self.results) - wins == need:
                winner, reason = "evil", f"{need} quests failed"
                break
            leader = self.players[self.leader]
            size = cfg.quest_sizes[self.quest]

            out = await self.ask(leader, "propose", f"You are the leader. Propose a team of exactly {size} players "
                                 "(you may include yourself) and say a short sentence to justify it.", size)
            team = out.get("team")
            if not (isinstance(team, list) and len(team) == size and len(set(team)) == size
                    and all(t in self.names for t in team)):
                team = self.rng.sample(self.names, size)
                self.emit("fallback", "hidden", player=leader.name, kind="propose", error="invalid team")
            self.emit("proposal", "public", quest=self.quest + 1, attempt=self.rejects + 1, leader=leader.name,
                      team=team, say=str(out.get("say") or "").strip())

            for _ in range(cfg.discussion_rounds):
                for p in self.seat(self.leader + 1):
                    await self.chat(p, "discuss", f"Discuss the proposed team {team}. Say what you think in 1-3 "
                                    "sentences, or say nothing.")

            outs = await asyncio.gather(*(self.ask(p, "vote", f"Vote on the proposed team {team}.")
                                          for p in self.players))
            votes = {p.name: ("reject" if o.get("vote") == "reject" else "approve") for p, o in zip(self.players, outs)}
            approved = sum(v == "approve" for v in votes.values()) * 2 > n
            self.emit("vote_result", "public", quest=self.quest + 1, attempt=self.rejects + 1, team=team,
                      votes=votes, approved=approved)
            self.leader = (self.leader + 1) % n
            if not approved:
                self.rejects += 1
                if self.rejects == cfg.max_rejections:
                    winner, reason = "evil", f"{cfg.max_rejections} teams rejected in a row"
                    break
                continue

            members = [p for p in self.players if p.name in team]
            outs = await asyncio.gather(*(
                self.ask(p, "quest", "You are on the quest. Play your card.",
                         cards=("success", "fail") if p.team == "evil" else ("success",)) for p in members))
            fails = sum(p.team == "evil" and o.get("card") == "fail" for p, o in zip(members, outs))
            ok = fails < cfg.fails_required[self.quest]
            self.emit("quest_result", "public", quest=self.quest + 1, team=team, fails=fails, success=ok)
            self.results.append(ok)
            self.quest += 1
            self.rejects = 0

        self.emit("game_over", "public", winner=winner, reason=reason,
                  roles={p.name: p.role for p in self.players})
        if self.log:
            self.log.close()
        return {"winner": winner, "reason": reason, "calls": self.calls}

    async def assassinate(self):
        evil = [p for p in self.players if p.team == "evil"]
        assassin = next(p for p in self.players if self.cfg.roles[p.role].can_assassinate)
        for _ in range(self.cfg.assassination_discussion_rounds):
            for p in evil:
                await self.chat(p, "evil_chat", "Good completed three quests. Discuss privately with your evil "
                                "teammates who Merlin is, in 1-3 sentences.")
        out = await self.ask(assassin, "assassinate", f"Good won three quests. Name the one player you believe is "
                             f"{self.cfg.assassination_target}.")
        target = out.get("target")
        if target not in self.names or target == assassin.name:
            target = self.rng.choice([nm for nm in self.names if nm != assassin.name])
            self.emit("fallback", "hidden", player=assassin.name, kind="assassinate", error="invalid target")
        hit = next(p for p in self.players if p.name == target).role == self.cfg.assassination_target
        self.emit("assassination", "public", assassin=assassin.name, target=target, correct=hit,
                  reasoning=str(out.get("reasoning") or ""))
        if hit:
            return "evil", f"{assassin.name} assassinated {target} ({self.cfg.assassination_target})"
        return "good", f"{assassin.name} guessed {target}, not {self.cfg.assassination_target}"
