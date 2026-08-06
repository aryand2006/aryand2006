"""Git plumbing.

Reading historical trees through `git cat-file --batch` rather than checking
them out means the gate never touches the working directory, so it is safe to
run against a dirty tree and inside CI at the same time.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass


class GitError(RuntimeError):
    pass


def _run(repo: str, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def is_repo(path: str) -> bool:
    try:
        _run(path, ["rev-parse", "--git-dir"])
        return True
    except (GitError, FileNotFoundError):
        return False


def resolve(repo: str, ref: str) -> str:
    return _run(repo, ["rev-parse", ref]).strip()


def list_python_files(repo: str, ref: str) -> list[str]:
    out = _run(repo, ["ls-tree", "-r", "--name-only", ref])
    return sorted(p for p in out.splitlines() if p.endswith(".py"))


def read_blobs(repo: str, ref: str, paths: list[str]) -> dict[str, str]:
    """Read many files at a ref in a single git process.

    Missing paths are simply absent from the result rather than an error, since
    a path present in one ref is routinely absent in another.
    """
    if not paths:
        return {}

    request = "".join(f"{ref}:{p}\n" for p in paths)
    proc = subprocess.run(
        ["git", "-C", repo, "cat-file", "--batch"],
        input=request.encode(),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise GitError(f"git cat-file: {proc.stderr.decode().strip()}")

    result: dict[str, str] = {}
    data = proc.stdout
    cursor = 0
    for path in paths:
        newline = data.find(b"\n", cursor)
        if newline == -1:
            break
        header = data[cursor:newline].decode(errors="replace")
        cursor = newline + 1

        parts = header.split()
        if len(parts) < 3 or parts[1] != "blob":
            # "<oid> missing" or a non-blob; nothing to advance past.
            continue

        size = int(parts[2])
        blob = data[cursor : cursor + size]
        cursor += size + 1  # trailing newline after the payload
        result[path] = blob.decode("utf-8", errors="replace")

    return result


@dataclass(frozen=True)
class FileChange:
    status: str  # A, M, D, R
    path: str
    old_path: str | None = None


def changed_files(repo: str, base: str, head: str) -> list[FileChange]:
    """Python files differing between two refs, with rename tracking."""
    out = _run(
        repo,
        ["diff", "--name-status", "--find-renames", f"{base}..{head}"],
    )
    changes: list[FileChange] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        status = fields[0]
        if status.startswith("R") and len(fields) >= 3:
            old, new = fields[1], fields[2]
            if new.endswith(".py"):
                changes.append(FileChange("R", new, old))
        elif len(fields) >= 2:
            path = fields[1]
            if path.endswith(".py"):
                changes.append(FileChange(status[0], path))
    return changes


def added_line_count(repo: str, base: str, head: str) -> int:
    """Lines added across Python files, used to normalize erosion by change size."""
    out = _run(repo, ["diff", "--numstat", f"{base}..{head}", "--", "*.py"])
    total = 0
    for line in out.splitlines():
        fields = line.split("\t")
        if len(fields) >= 1 and fields[0].isdigit():
            total += int(fields[0])
    return total


def commit_list(repo: str, since: str, head: str = "HEAD", limit: int = 0) -> list[str]:
    """Commits from `since` to `head`, oldest first."""
    args = ["rev-list", "--reverse", f"{since}..{head}"]
    if limit:
        args.insert(1, f"--max-count={limit}")
    return [c for c in _run(repo, args).splitlines() if c.strip()]


def commit_meta(repo: str, ref: str) -> dict[str, str]:
    out = _run(repo, ["show", "-s", "--format=%H%x1f%an%x1f%aI%x1f%s", ref]).strip()
    sha, author, date, subject = out.split("\x1f")
    return {"sha": sha, "author": author, "date": date, "subject": subject}
