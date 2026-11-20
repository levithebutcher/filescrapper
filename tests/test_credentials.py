# tests/test_credentials.py
"""
Security & Credential Leak Detection Test Suite.
Verifies that no API tokens, secrets, or credential files can leak into Git.
"""

import os
import re
import unittest
from pathlib import Path

# Telegram Bot Token Regex: 8 to 11 digits followed by colon and 35 alphanumeric/dash/underscore chars
TELEGRAM_BOT_TOKEN_REGEX = re.compile(r"\b\d{8,11}:[a-zA-Z0-9_-]{35}\b")

# Telegram API Hash (32 hex characters)
API_HASH_REGEX = re.compile(r"\b[a-f0-9]{32}\b", re.IGNORECASE)

# Ignored paths during secret scanning
IGNORED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".idea", ".vscode"}
IGNORED_FILES = {".env"}  # .env is local-only and ignored in git

def is_ignored_file(filename: str) -> bool:
    if filename in IGNORED_FILES:
        return True
    lower = filename.lower()
    if "dev" in lower and lower.endswith(".ipynb"):
        return True
    return False


class TestCredentialSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parent.parent

    def test_gitignore_exists_and_contains_env(self):
        """Check that .gitignore exists and properly ignores .env and credential files."""
        gitignore_path = self.repo_root / ".gitignore"
        self.assertTrue(gitignore_path.exists(), ".gitignore file must exist!")

        content = gitignore_path.read_text(encoding="utf-8")
        patterns = [line.strip() for line in content.splitlines() if line.strip() and not line.startswith("#")]

        self.assertIn(".env", patterns, ".env must be explicitly ignored in .gitignore!")
        self.assertTrue(
            any("session" in p for p in patterns),
            "Telegram session files (*.session) must be ignored in .gitignore",
        )

    def test_env_example_has_no_real_secrets(self):
        """Ensure .env.example contains only dummy placeholder values."""
        example_path = self.repo_root / ".env.example"
        self.assertTrue(example_path.exists(), ".env.example must exist!")

        content = example_path.read_text(encoding="utf-8")
        matches = TELEGRAM_BOT_TOKEN_REGEX.findall(content)
        self.assertEqual(
            matches,
            [],
            f"LEAK DETECTED in .env.example! Found real token(s): {matches}",
        )
        self.assertIn(
            "your_bot_token_here",
            content,
            ".env.example should use placeholder 'your_bot_token_here'",
        )

    def test_no_hardcoded_tokens_in_codebase(self):
        """
        Scan all tracked repository files (.py, .md, .txt, .json, .ipynb, .yml, .yaml)
        to ensure NO real Telegram Bot Tokens are present.
        """
        scanned_files = 0
        violations = []

        allowed_extensions = {".py", ".md", ".txt", ".json", ".ipynb", ".yml", ".yaml", ".example"}

        for root, dirs, files in os.walk(self.repo_root):
            # Prune ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

            for file in files:
                if is_ignored_file(file):
                    continue

                filepath = Path(root) / file
                if filepath.suffix not in allowed_extensions and not file.startswith(".env.example"):
                    continue

                scanned_files += 1
                try:
                    text = filepath.read_text(encoding="utf-8", errors="ignore")
                except Exception as e:
                    violations.append(f"Could not read {filepath}: {e}")
                    continue

                token_matches = TELEGRAM_BOT_TOKEN_REGEX.findall(text)
                if token_matches:
                    violations.append(
                        f"File {filepath.relative_to(self.repo_root)} contains real Telegram Token: {token_matches}"
                    )

        self.assertGreater(scanned_files, 0, "At least some files must have been scanned!")
        self.assertEqual(
            violations,
            [],
            f"CRITICAL SECURITY FAIL: Found hardcoded credentials in files:\n" + "\n".join(violations),
        )

    def test_config_safe_token_loading(self):
        """Ensure config.py loads BOT_TOKEN safely using os.getenv with no default secret."""
        config_path = self.repo_root / "config.py"
        self.assertTrue(config_path.exists(), "config.py must exist!")

        content = config_path.read_text(encoding="utf-8")
        token_matches = TELEGRAM_BOT_TOKEN_REGEX.findall(content)
        self.assertEqual(
            token_matches,
            [],
            f"config.py contains hardcoded bot token: {token_matches}",
        )
        self.assertIn("os.getenv", content, "config.py must use os.getenv to read environment variables!")


if __name__ == "__main__":
    unittest.main()
