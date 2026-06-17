#!/usr/bin/env python3
"""#21 secret scanner — exits 1 if likely secrets are committed.

Conservative patterns (to avoid false positives in source). Intended for the CI
gate (#33) and as a pre-commit check. Prints file:line + a label, never the value.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "dist", "build", ".venv", "venv",
             "__pycache__", ".secrets", ".mypy_cache", ".pytest_cache"}
TEXT_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".yaml", ".yml", ".json",
            ".env", ".sh", ".md", ".txt", ".cfg", ".ini", ".toml"}

PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b")),
    ("generic secret assignment",
     re.compile(r"(?i)(?:api[_-]?key|secret|access[_-]?token|password)\s*[:=]\s*"
                r"['\"][^'\"\s]{20,}['\"]")),
]
# Obvious placeholders/examples to ignore.
ALLOW = re.compile(r"(?i)(change-?me|placeholder|example|your[_-]|xxx+|<[^>]+>|"
                   r"redacted|dummy|\btest[_-]?token\b|\$\{)")


def tracked_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                             check=True).stdout
        return [Path(p) for p in out.splitlines() if p.strip()]
    except Exception:
        return [p for p in Path(".").rglob("*")
                if p.is_file() and not (set(p.parts) & SKIP_DIRS)]


def scan() -> int:
    findings: list[tuple[str, int, str]] = []
    files = tracked_files()
    for f in files:
        if f.name == ".env":
            findings.append((str(f), 0, "tracked .env (should be gitignored)"))
    for f in files:
        if (set(f.parts) & SKIP_DIRS) or f.suffix not in TEXT_EXT or f.name == ".env.example":
            continue
        try:
            text = f.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if ALLOW.search(line):
                continue
            for label, rx in PATTERNS:
                if rx.search(line):
                    findings.append((str(f), i, label))
                    break
    if findings:
        print("POTENTIAL SECRETS DETECTED:")
        for path, line, label in findings:
            print(f"  [{label}] {path}:{line}" if line else f"  [{label}] {path}")
        return 1
    print("scan_secrets: clean")
    return 0


if __name__ == "__main__":
    sys.exit(scan())
