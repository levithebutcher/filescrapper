#!/usr/bin/env python3
"""
check_leaks.py - Security & Credential Leak Auditor.
Scans the entire repository before committing or pushing to ensure
no private API keys, Telegram Bot tokens, or sensitive files are exposed.
"""

import os
import re
import sys
from pathlib import Path

# Match Telegram bot token format: 8-11 digits followed by colon and 35 chars
TELEGRAM_BOT_TOKEN_REGEX = re.compile(r"\b\d{8,11}:[a-zA-Z0-9_-]{35}\b")

# Private key header pattern
PRIVATE_KEY_REGEX = re.compile(r"-----BEGIN\s+(?:RSA|OPENSSH|DSA|EC|PGP)?\s*PRIVATE\s+KEY-----")

IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".idea", ".vscode"}
IGNORED_FILES = {".env"}  # .env is deliberately ignored by git


def run_security_check() -> bool:
    root = Path(__file__).resolve().parent
    print("=" * 65)
    print("🔍 RUNNING PRE-PUSH SECURITY & CREDENTIAL LEAK CHECK")
    print("=" * 65)

    has_error = False

    # 1. Check .gitignore
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        print("❌ CRITICAL: .gitignore does not exist!")
        has_error = True
    else:
        content = gitignore.read_text(encoding="utf-8")
        if ".env" not in [line.strip() for line in content.splitlines()]:
            print("❌ CRITICAL: '.env' is NOT present in .gitignore!")
            has_error = True
        else:
            print("✅ .gitignore properly ignores '.env'")

    # 2. Check .env.example
    env_example = root / ".env.example"
    if env_example.exists():
        example_text = env_example.read_text(encoding="utf-8")
        tokens = TELEGRAM_BOT_TOKEN_REGEX.findall(example_text)
        if tokens:
            print(f"❌ CRITICAL: Real token found in .env.example: {tokens}")
            has_error = True
        else:
            print("✅ .env.example contains only placeholder credentials")
    else:
        print("⚠️ Warning: .env.example not found.")

    # 3. Scan all committable files
    print("\n📁 Scanning all tracked / committable files...")
    allowed_extensions = {".py", ".md", ".txt", ".json", ".ipynb", ".yml", ".yaml", ".example"}
    scanned_count = 0
    leaks = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]

        for fname in filenames:
            if fname in IGNORED_FILES:
                continue

            fpath = Path(dirpath) / fname
            if fpath.suffix not in allowed_extensions and not fname.startswith(".env.example"):
                continue

            scanned_count += 1
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                print(f"⚠️ Could not read {fpath}: {e}")
                continue

            # Check bot tokens
            token_matches = TELEGRAM_BOT_TOKEN_REGEX.findall(text)
            if token_matches:
                leaks.append((fpath.relative_to(root), f"Telegram Bot Token: {token_matches}"))

            # Check private keys
            if PRIVATE_KEY_REGEX.search(text):
                leaks.append((fpath.relative_to(root), "Private cryptographic key block"))

    print(f"Scanned {scanned_count} files.")

    if leaks:
        print("\n❌ CRITICAL LEAKS DETECTED:")
        for relpath, reason in leaks:
            print(f"  - {relpath}: {reason}")
        has_error = True
    else:
        print("✅ No hardcoded Telegram tokens or private keys found in scanned files!")

    print("=" * 65)
    if has_error:
        print("❌ SECURITY AUDIT FAILED! DO NOT COMMIT OR PUSH TO GITHUB!")
        print("=" * 65)
        return False
    else:
        print("🎉 ALL SECURITY CHECKS PASSED! Safe to commit and push.")
        print("=" * 65)
        return True


if __name__ == "__main__":
    success = run_security_check()
    sys.exit(0 if success else 1)
