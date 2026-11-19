#!/usr/bin/env python3
"""Scan the worktree and git history for credential-shaped strings.

Matches in commits listed in references/known-historical-secret-commits.txt are
reported and ignored. Those commits still contain the removed HAP credential.
The owner must revoke it; rewriting history is optional and is not done here.
Do not add a commit to that file to hide a new secret.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "references" / "known-historical-secret-commits.txt"
SUFFIXES = {".js", ".json", ".md", ".py", ".sh", ".tsv", ".txt", ".yaml", ".yml"}
EXCLUDED = {
    "scripts/preflight.sh",
    "scripts/scan_secrets.py",
    "tests/test_ci_hardening.py",
    "references/known-historical-secret-commits.txt",
}

LINE_PATTERNS = (
    ("OpenAI key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("GitHub OAuth token", re.compile(r"gho_[A-Za-z0-9]{20,}")),
    ("GitHub personal token", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    (
        "JWT",
        re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    ),
    (
        "Bearer token",
        re.compile(r"\bbearer\s+[A-Za-z0-9._~+/-]{20,}", re.IGNORECASE),
    ),
)
HAP_PAIRS = (
    re.compile(
        r"""HAP-Appkey\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?"""
        r""".{0,512}?HAP-Sign\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?""",
        re.DOTALL | re.IGNORECASE,
    ),
    re.compile(
        r"""HAP-Sign\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?"""
        r""".{0,512}?HAP-Appkey\s*[:=]\s*["']?([A-Za-z0-9_-]{8,})["']?""",
        re.DOTALL | re.IGNORECASE,
    ),
)


def allowlisted_commits():
    if not ALLOWLIST.is_file():
        return set()
    commits = set()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            commits.add(line.lower())
    return commits


def scan_text(relative, text):
    hits = []
    for label, pattern in LINE_PATTERNS:
        if pattern.search(text):
            hits.append(label)
    for pattern in HAP_PAIRS:
        if pattern.search(text):
            hits.append("HAP Appkey/Sign pair")
    return [(relative, label) for label in hits]


def scan_worktree():
    hits = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix not in SUFFIXES:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if relative in EXCLUDED:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits.extend(scan_text(relative, text))
    return hits


def scan_history(allowed):
    commits = subprocess.run(
        ["git", "-C", str(ROOT), "rev-list", "--all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    unexpected = []
    ignored = 0
    for sha in commits:
        listing = subprocess.run(
            ["git", "-C", str(ROOT), "grep", "-I", "-l", "-E", r"HAP-Sign|HAP-Appkey|sk-|ghp_|gho_|github_pat_|eyJ", sha],
            capture_output=True,
            text=True,
        )
        if listing.returncode not in (0, 1):
            continue
        for raw in listing.stdout.splitlines():
            # git grep -l output is "<sha>:<path>"
            _, _, relative = raw.partition(":")
            if not relative or relative in EXCLUDED:
                continue
            if Path(relative).suffix not in SUFFIXES and not relative.endswith(".js"):
                continue
            blob = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"{sha}:{relative}"],
                capture_output=True,
            )
            try:
                text = blob.stdout.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for found_path, label in scan_text(relative, text):
                if sha.lower() in allowed and label == "HAP Appkey/Sign pair":
                    ignored += 1
                    continue
                unexpected.append((sha[:12], found_path, label))
    return unexpected, ignored


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", action="store_true")
    parser.add_argument("--history", action="store_true")
    args = parser.parse_args(argv)
    if not args.worktree and not args.history:
        args.worktree = True
        args.history = True

    failures = []
    if args.worktree:
        for relative, label in scan_worktree():
            failures.append(f"worktree {relative}: {label}")
    ignored = 0
    if args.history:
        unexpected, ignored = scan_history(allowlisted_commits())
        for sha, relative, label in unexpected:
            failures.append(f"history {sha} {relative}: {label}")
        print(
            f"historical HAP credential matches ignored: {ignored} "
            "(still recoverable until revoked)",
            file=sys.stderr,
        )

    if failures:
        print("secret scan failed (values hidden):", file=sys.stderr)
        for item in failures:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("secret scan passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
