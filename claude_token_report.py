#!/usr/bin/env python3
"""
claude_token_report.py — where do your Claude Code tokens actually go?

Reads ONLY the local Claude Code transcripts (~/.claude/projects/**/*.jsonl).
Sends nothing anywhere, calls no API, uses 0 tokens. Python 3.8+, no dependencies.

  python3 claude_token_report.py               # last 7 days
  python3 claude_token_report.py --explain     # what raw and weighted tokens mean
  python3 claude_token_report.py --html r.html # HTML report
  python3 claude_token_report.py --help        # all options

The code lives in the token_report/ package next to this file.
"""
import os
import sys

# works when started through a symlink too (e.g. ~/.local/bin/claude-token-report)
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from token_report.cli import run  # noqa: E402

if __name__ == "__main__":
    run()
