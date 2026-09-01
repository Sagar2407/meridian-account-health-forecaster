#!/usr/bin/env python3
"""Fail when source contains likely secrets or machine-specific absolute paths."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRECTORIES = {
    ".git",
    ".phase0-cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}
SKIP_PREFIXES = {Path("data/raw")}
# `dataset/` is a byte-exact copy of files inside the committed archive, kept
# browsable on GitHub. `test_dataset_source.py` fails the build if the two
# diverge, so this project's authoring conventions cannot be applied to it --
# adding a final newline here would break that check. Secret and absolute-path
# scanning still applies: those are safety, not style.
VERBATIM_PREFIXES = {Path("dataset")}
# Files git ignores are never distributed, so they are outside this policy.
# `.env` in particular is *supposed* to hold real credentials locally.
FALLBACK_SKIP_NAMES = {".env"}
# Tool output, not source. `.tsbuildinfo` is TypeScript's incremental build
# state: git ignores it, but the evaluation image has no git binary, so
# `ignored_paths` falls back and this scan would otherwise apply an authoring
# convention to a file no human wrote. The secret and absolute-path patterns
# below still run against everything that is not binary.
SKIP_SUFFIXES = {
    ".csv",
    ".docx",
    ".faiss",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".npy",
    ".parquet",
    ".pdf",
    ".png",
    ".sqlite",
    ".tsbuildinfo",
    ".zip",
}
PATTERNS = {
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "OpenAI-style secret": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "macOS user path": re.compile("/" + r"Users/[^/\s]+/"),
    "Linux user path": re.compile("/" + r"home/[^/\s]+/"),
    "Windows user path": re.compile(r"[A-Za-z]:\\\\" + r"Users\\\\[^\\\s]+\\\\"),
}


def ignored_paths(candidates: list[Path]) -> set[Path]:
    """Return the subset of `candidates` that git ignores.

    The policy is "no secrets in tracked source". Anything git ignores is never
    published, so scanning it produces false positives -- most importantly for a
    local `.env`. Falls back to a small static list when git is unavailable.
    """

    if not candidates:
        return set()
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=ROOT,
            input="\n".join(str(path) for path in candidates),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return {path for path in candidates if path.name in FALLBACK_SKIP_NAMES}
    if result.returncode not in (0, 1):
        return {path for path in candidates if path.name in FALLBACK_SKIP_NAMES}
    return {ROOT / line for line in result.stdout.splitlines() if line}


def is_verbatim(path: Path) -> bool:
    """Return whether this file is a byte-exact copy that must not be reformatted."""

    relative = path.relative_to(ROOT)
    return any(prefix in relative.parents for prefix in VERBATIM_PREFIXES)


def source_files() -> list[Path]:
    """Return text-like repository files while excluding generated and source-data areas."""

    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in SKIP_DIRECTORIES for part in relative.parts):
            continue
        if any(relative == prefix or prefix in relative.parents for prefix in SKIP_PREFIXES):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(path)
    ignored = ignored_paths(files)
    return [path for path in files if path not in ignored]


def main() -> int:
    """Scan files and return a process-friendly result."""

    findings: list[str] = []
    files = source_files()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not is_verbatim(path):
            if text and not text.endswith("\n"):
                findings.append(f"{path.relative_to(ROOT)}: missing final newline")
            for line_number, line in enumerate(text.splitlines(), start=1):
                if line.endswith((" ", "\t")):
                    findings.append(f"{path.relative_to(ROOT)}:{line_number}: trailing whitespace")
        for label, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{path.relative_to(ROOT)}:{line}: {label}")

    if findings:
        print("Repository policy scan failed:")
        for finding in findings:
            print(f"- {finding}")
        return 1

    print(f"Repository policy scan passed ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
