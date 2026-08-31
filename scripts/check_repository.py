#!/usr/bin/env python3
"""Fail when source contains likely secrets or machine-specific absolute paths."""

from __future__ import annotations

import re
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
    return files


def main() -> int:
    """Scan files and return a process-friendly result."""

    findings: list[str] = []
    files = source_files()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if text and not text.endswith("\n"):
            findings.append(f"{path.relative_to(ROOT)}: missing final newline")
        for line_number, line in enumerate(text.splitlines(), start=1):
            if line.endswith((" ", "\t")):
                findings.append(
                    f"{path.relative_to(ROOT)}:{line_number}: trailing whitespace"
                )
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
