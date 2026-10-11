import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Sees(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    role: str
    label: str = Field(alias="as")


class Role(BaseModel):
    team: Literal["good", "evil"]
    sees: list[Sees] = []
    can_assassinate: bool = False
    description: str = ""


class PlayerCfg(BaseModel):
    name: str
    model: str | None = None


class Discussion(BaseModel):
    min_turns: int = 1  # every player speaks at least this often before the vote
    max_turns: int = 3  # proactive turns per player per proposal
    question_examples: list[str] = []


class Config(BaseModel):
    roles: dict[str, Role]
    assassination_target: str
    quest_sizes: list[int]
    fails_required: list[int]
    max_rejections: int = 5
    discussion: Discussion = Discussion()
    assassination_discussion_rounds: int = 2
    default_model: str = "sonnet"
    players: list[PlayerCfg]

    @model_validator(mode="after")
    def check(self):
        if len(self.players) != len(self.roles):
            raise ValueError(f"{len(self.players)} players but {len(self.roles)} roles")
        if len({p.name for p in self.players}) != len(self.players):
            raise ValueError("player names must be unique")
        for name, role in self.roles.items():
            for s in role.sees:
                if s.role not in self.roles:
                    raise ValueError(f"{name} sees unknown role {s.role}")
        if self.assassination_target not in self.roles:
            raise ValueError("unknown assassination_target")
        if sum(r.can_assassinate for r in self.roles.values()) != 1:
            raise ValueError("exactly one role must have can_assassinate")
        if not 1 <= self.discussion.min_turns <= self.discussion.max_turns:
            raise ValueError("need 1 <= discussion.min_turns <= discussion.max_turns")
        if len(self.fails_required) != len(self.quest_sizes):
            raise ValueError("fails_required and quest_sizes differ in length")
        if max(self.quest_sizes) > len(self.players):
            raise ValueError("quest size exceeds player count")
        return self


def load(path) -> Config:
    with open(path) as f:
        return Config.model_validate(json.load(f))
