import re
import subprocess
from pathlib import Path


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=check)


def save(root, files, message):
    """Write {filename: text} into a playbook directory and commit whatever changed. Every playbook is its own git
    repo, so the edit made after each game can be diffed or reverted. Returns the short commit hash."""
    root = Path(root)
    if not (root / ".git").exists():
        git(root, "init", "-q")
    for name, text in files.items():
        (root / name).write_text(text.strip() + "\n")
    git(root, "add", "-A")
    if git(root, "status", "--porcelain").stdout.strip():
        git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "--short", "HEAD", check=False).stdout.strip() or None


def load(path, cfg):
    """Read a playbook: one <role id>.md file per role. Seats are reshuffled between games, so the text must not
    mention player names. Edits made by hand are committed first, so a game always uses an exact commit."""
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"playbook {path} is not a directory")
    commit = None
    if (root / ".git").exists():
        edited = [line[3:] for line in git(root, "status", "--porcelain").stdout.splitlines()]
        commit = save(root, {}, f"Manual edits to {', '.join(edited)}\n\nNot written by the learn step; committed "
                                "automatically when the playbook was loaded for the next game.")
    roles = {}
    for f in sorted(root.glob("*.md")):
        if f.stem not in cfg.roles:
            raise ValueError(f"{f}: unknown role {f.stem!r}")
        roles[f.stem] = f.read_text().strip()
        for p in cfg.players:
            if re.search(rf"\b{re.escape(p.name)}\b", roles[f.stem]):
                raise ValueError(f"{f} mentions the player name {p.name!r}; refer to roles or seats instead")
    return {"path": str(root), "roles": roles, "commit": commit}
