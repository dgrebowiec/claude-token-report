"""Display names of projects, files and prompts — anonymised with --private."""
from __future__ import annotations

import os
import re
from typing import Dict, Optional

from .transcripts import SessionMeta

_WORKTREE = re.compile(r"^(.*?)[/\\]\.claude[/\\]worktrees[/\\]([^/\\]+)")


class Namer:
    def __init__(self, private: bool):
        self.private = private
        self._projects: Dict[str, str] = {}
        self._files: Dict[str, str] = {}

    def project(self, meta: Optional[SessionMeta], proj_dir: str) -> str:
        cwd = meta.cwd if meta else None
        name = self._project_path(cwd) if cwd else proj_dir
        if not self.private:
            return name
        base = name.replace(" [worktree]", "")
        if base not in self._projects:
            self._projects[base] = f"project-{len(self._projects) + 1}"
        return self._projects[base] + (" [worktree]" if base != name else "")

    def _project_path(self, cwd: str) -> str:
        """~-relative working directory; a Claude Code worktree counts as its main project"""
        home = os.path.expanduser("~")
        worktree = None
        match = _WORKTREE.search(cwd)
        if match:
            cwd, worktree = match.group(1), match.group(2)
        if cwd == home:
            name = "~"
        elif cwd.startswith(home + os.sep):
            name = "~/" + cwd[len(home) + 1:]
        else:
            name = cwd
        if worktree:
            name += " [worktree]" if self.private else f" [worktree {worktree}]"
        return name

    def file(self, path: str) -> str:
        base = os.path.basename(path)
        if not self.private:
            return base
        if path not in self._files:
            ext = os.path.splitext(base)[1]
            self._files[path] = f"file-{len(self._files) + 1}{ext}"
        return self._files[path]

    def topic(self, text: Optional[str]) -> str:
        return "" if self.private else (text or "")
