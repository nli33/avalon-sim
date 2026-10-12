import re
from pathlib import Path


def load(path, cfg):
    """Read a playbook directory: general.md plus roles/<role id>.md. Seats are reshuffled between games, so the
    text must not mention player names."""
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"playbook {path} is not a directory")
    general = root / "general.md"
    pb = {"path": str(root), "general": general.read_text().strip() if general.exists() else "", "roles": {}}
    for f in sorted((root / "roles").glob("*.md")):
        if f.stem not in cfg.roles:
            raise ValueError(f"{f}: unknown role {f.stem!r}")
        pb["roles"][f.stem] = f.read_text().strip()
    for where, text in [("general", pb["general"]), *pb["roles"].items()]:
        for p in cfg.players:
            if re.search(rf"\b{re.escape(p.name)}\b", text):
                raise ValueError(f"{path} ({where}) mentions the player name {p.name!r}; refer to roles or seats instead")
    return pb
