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


def schema(kind, names=(), cards=("success", "fail"), me=None):
    """Output schema per decision."""
    s = lambda: {"type": "string"}
    # Wording matters: Sonnet 5.5 refuses (stop_reason "refusal") when a field asks it to write out its reasoning
    # or to fill the field in before deciding. Keep this a memory note for the next turn.
    notes = {"type": "string", "description": "Private notes to your future self, in the first person. The other "
             "players are everyone except you."}
    props = {
        "discuss": {"notes": notes,
                    "say": {"type": "string", "description": "Your public message to the whole table (1-3 sentences). "
                            "If you were asked a question, answer it here. May be empty."},
                    "ask_to": {"enum": [""] + [n for n in names if n != me],
                               "description": "The one player you direct a question at, or empty."},
                    "question": {"type": "string", "description": "The question for ask_to, addressed to them. "
                                 "Empty if ask_to is empty."},
                    "ready_to_vote": {"type": "boolean"}},
        "evil_chat": {"notes": notes, "say": s()},
        "propose": {"notes": notes, "team": {"type": "array", "items": {"enum": list(names)}}, "say": s()},
        "vote": {"notes": notes, "vote": {"enum": ["approve", "reject"]}},
        "quest": {"notes": notes, "card": {"enum": list(cards)}},
        "assassinate": {"reasoning": s(), "target": {"enum": list(names)}},
    }[kind]
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class Game:
    def __init__(self, cfg, agent, seed=0, log_path=None, on_event=None, playbooks=None):
        self.cfg, self.agent, self.seed, self.on_event = cfg, agent, seed, on_event
        self.playbooks = playbooks or {}  # team -> playbook (see playbook.load)
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
        self.groups = 0  # decisions made in parallel share a group id
        self.log = open(log_path, "w") if log_path else None

    def emit(self, type, vis, **data):
        ev = {"i": len(self.events), "type": type, "vis": vis, **data}
        self.events.append(ev)
        if self.log:
            self.log.write(json.dumps(ev) + "\n")
            self.log.flush()
        if self.on_event:
            self.on_event(ev)

    def new_group(self):
        self.groups += 1
        return self.groups

    async def ask(self, player, kind, instruction, size=0, cards=("success", "fail"), group=None):
        """One agent decision. Returns the agent's dict, or {} if the call failed."""
        group = group or self.new_group()
        system, prompt = views.build_view(self, player, instruction)
        req = {"kind": kind, "player": player.name, "model": player.model, "system": system, "prompt": prompt,
               "schema": schema(kind, self.names, cards, player.name),
               "ctx": {"names": self.names, "size": size, "cards": list(cards)}}
        self.calls += 1
        try:
            out = await self.agent.act(req)
        except Exception as e:
            self.emit("fallback", "hidden", player=player.name, kind=kind, error=str(e))
            self.emit("action", "hidden", player=player.name, kind=kind, group=group, output={})
            return {}
        if out.get("notes") is not None:
            self.notes[player.name] = str(out["notes"])
        self.emit("action", "hidden", player=player.name, kind=kind, group=group, output=out)
        return out

    def seat(self, start):
        """Players in seat order beginning at index start."""
        n = len(self.players)
        return [self.players[(start + i) % n] for i in range(n)]

    async def chat(self, player, instruction):
        """One message in the evil channel."""
        out = await self.ask(player, "evil_chat", instruction)
        text = str(out.get("say") or "").strip()
        if text:
            self.emit("chat", "evil", player=player.name, text=text)

    async def discuss(self, team, leader):
        """Free-flowing discussion after a proposal. The engine picks every speaker: a player who has been asked a
        question speaks next (and nobody else), otherwise the players who have spoken least go first."""
        cfg = self.cfg.discussion
        seat = {p.name: i for i, p in enumerate(self.seat(self.leader + 1))}
        turns = {n: 0 for n in self.names}
        last = {n: -1 for n in self.names}
        last[leader.name] = 0  # the proposal counts as the leader's latest message
        ready = {n: False for n in self.names}
        pending = None  # (asked player, asker, question text); at most one, since the asked player speaks next
        step = 0
        while True:
            if pending:
                speaker, question = next(p for p in self.players if p.name == pending[0]), pending
                pending = None
            else:
                pool = [p for p in self.players if turns[p.name] < cfg.min_turns]
                pool = pool or [p for p in self.players if not ready[p.name] and turns[p.name] < cfg.max_turns]
                if not pool:
                    return
                speaker = min(pool, key=lambda p: (turns[p.name], last[p.name], seat[p.name]))
                question = None
            step += 1
            name = speaker.name
            out = await self.ask(speaker, "discuss", self.discussion_prompt(speaker, team, turns, question))
            turns[name] += 1
            last[name] = step
            ready[name] = out.get("ready_to_vote", True) is not False  # a failed call counts as ready
            text = str(out.get("say") or "").strip()
            if question and not text:
                text = "(no answer)"
                self.emit("fallback", "hidden", player=name, kind="discuss", error="asked a question but said nothing")
            target, ask = str(out.get("ask_to") or ""), str(out.get("question") or "").strip()
            if target and not (ask and target in self.names and target != name and turns[name] <= cfg.max_turns):
                self.emit("fallback", "hidden", player=name, kind="discuss", error=f"ignored ask_to {target!r}")
                target = ""
            if target:
                pending = (target, name, ask)
            if text or target:
                self.emit("chat", "public", player=name, text=text, to=target or None, question=ask if target else None,
                          reply_to=question[1] if question else None, quest=self.quest + 1, attempt=self.rejects + 1)

    def discussion_prompt(self, speaker, team, turns, question):
        cfg = self.cfg.discussion
        lines = [f"Discussion on the proposed team {', '.join(team)}. Turns taken so far: "
                 + ", ".join(f"{n} {t}" for n, t in turns.items()) + f". You have used {turns[speaker.name]} of "
                 f"{cfg.max_turns} turns."]
        if question:
            lines.append(f'{question[1]} asked you directly and it is your turn to answer: "{question[2]}"')
        lines.append("In say, write your public message to the table (1-3 sentences; leave it empty to stay "
                     "silent), including your answer if you were asked something. To ask one other player a question, put their name in ask_to and the question "
                     "itself in question only, not in say: they speak next and must answer it. You cannot ask a question once you are "
                     "past your turn limit. Set ready_to_vote to true when you are ready to vote. The discussion "
                     "ends when everyone has spoken and every player is ready to vote, or when turns run out.")
        lines.append("A question that asks the other player to commit to something concrete (a name, a team, a vote) "
                     "is easier to answer and can be checked against what they do later.")
        if cfg.question_examples:
            lines.append("Some question formats (illustrative, not exhaustive; replace X, Y, Z with player names):")
            lines += [f"- {q}" for q in cfg.question_examples]
        return "\n".join(lines)

    async def run(self):
        cfg, n = self.cfg, len(self.players)
        need = len(cfg.quest_sizes) // 2 + 1
        self.emit("setup", "hidden", seed=self.seed, leader=self.players[self.leader].name,
                  playbooks={t: pb["path"] for t, pb in self.playbooks.items()}, players=[{**vars(p), "sees": views.sees(self, p)} for p in self.players])
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

            await self.discuss(team, leader)

            g = self.new_group()
            outs = await asyncio.gather(*(self.ask(p, "vote", f"Vote on the proposed team {team}.", group=g)
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
            g = self.new_group()
            outs = await asyncio.gather(*(
                self.ask(p, "quest", "You are on the quest. Play your card.", group=g,
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
                await self.chat(p, "Good completed three quests. Discuss privately with your evil "
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
