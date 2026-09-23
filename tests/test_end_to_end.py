"""Runs the whole pipeline on a small synthetic ~/.claude/projects directory."""
import contextlib
import datetime
import io
import json
import os
import tempfile
import unittest

from token_report import i18n
from token_report.cli import main
from token_report.naming import Namer
from token_report.stats import aggregate
from token_report.transcripts import load

PROJECT = "-home-user-myproj"
SESSION = "11111111-aaaa-bbbb-cccc-000000000000"
AGENT = "a1b2c3d4e5"
T0 = datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc)


def _ts(minutes):
    return (T0 + datetime.timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _usage(cache_read=0, write=0, output=100, input_tokens=5):
    return {"input_tokens": input_tokens, "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": write, "output_tokens": output,
            "cache_creation": {"ephemeral_5m_input_tokens": write, "ephemeral_1h_input_tokens": 0}}


def _assistant(minutes, msg_id, usage, tools=(), model="claude-opus-5", **extra):
    content = [{"type": "tool_use", "id": f"tu-{msg_id}-{i}", "name": name, "input": inp}
               for i, (name, inp) in enumerate(tools)]
    return {"type": "assistant", "timestamp": _ts(minutes), "cwd": "/home/user/myproj",
            "message": {"id": msg_id, "model": model, "usage": usage, "content": content},
            **extra}


def _user(minutes, content, **extra):
    return {"type": "user", "timestamp": _ts(minutes), "cwd": "/home/user/myproj",
            "message": {"role": "user", "content": content}, **extra}


def _write_jsonl(path, records):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def make_transcripts(root):
    main_records = [
        _user(0, "fix the login bug"),
        _assistant(1, "m1", _usage(write=30_000),
                   tools=[("Read", {"file_path": "/home/user/myproj/app.py"})]),
        _assistant(2, "m2", _usage(cache_read=30_000, write=1_000),
                   tools=[("Read", {"file_path": "/home/user/myproj/app.py"})]),
        _assistant(3, "m3", _usage(cache_read=31_000, write=500),
                   tools=[("Agent", {"subagent_type": "Explore", "prompt": "find it"})]),
        _user(4, [{"type": "tool_result", "tool_use_id": "tu-m3-0",
                   "content": [{"type": "text", "text": f"done\nagentId: {AGENT}"}]}]),
        # an hour later: the cache expired and the whole conversation is written again
        _assistant(64, "m4", _usage(write=32_000),
                   tools=[("Bash", {"command": "git diff"}),
                          ("Edit", {"file_path": "/home/user/myproj/app.py"})]),
        _assistant(65, "m4", _usage(write=32_000, output=300)),  # same message, final usage
        {"type": "system", "subtype": "compact_boundary", "timestamp": _ts(66)},
        _user(67, "<command-name>/compact</command-name>"),
        _user(68, "now add a test"),
        _assistant(69, "m5", _usage(cache_read=5_000, output=800), model="claude-sonnet-5"),
    ]
    _write_jsonl(os.path.join(root, PROJECT, SESSION + ".jsonl"), main_records)
    sub_dir = os.path.join(root, PROJECT, SESSION, "subagents")
    _write_jsonl(os.path.join(sub_dir, f"agent-{AGENT}.jsonl"), [
        _user(3, "find it", isSidechain=True),
        _assistant(3.5, "s1", _usage(write=8_000), tools=[("Grep", {"pattern": "login"})],
                   model="claude-haiku-4-5", isSidechain=True),
    ])


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "projects")
        make_transcripts(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--dir", self.root, *args])
        return out.getvalue()

    def test_load_and_aggregate(self):
        calls, sessions = load(self.root, None, None)
        self.assertEqual([c.time for c in calls], sorted(c.time for c in calls))
        self.assertEqual(len(calls), 6)  # m4 is logged twice but counted once
        m4 = next(c for c in calls if c.tokens["output"] == 300)
        self.assertEqual(len(m4.tools), 2)
        sub = [c for c in calls if c.is_subagent]
        self.assertEqual(len(sub), 1)
        self.assertEqual(sub[0].agent_type, "Explore")

        meta = sessions[(PROJECT, SESSION)]
        self.assertEqual(meta.topic, "fix the login bug")
        self.assertEqual([p.text for p in meta.prompts],
                         ["fix the login bug", "/compact", "now add a test"])

        stats = aggregate(calls, sessions, Namer(private=False))
        self.assertEqual(stats.n_calls, 6)
        self.assertEqual(stats.n_sessions, 1)
        self.assertEqual(stats.n_subagents, 1)
        self.assertEqual(stats.rebuilds.count, 1)
        self.assertEqual(stats.rereads.reads, 2)
        self.assertEqual(stats.rereads.repeats, 1)
        self.assertEqual(set(stats.by_model), {"claude-opus-5", "claude-sonnet-5",
                                               "claude-haiku-4-5"})
        self.assertIn("bash_git", stats.by_activity)
        self.assertAlmostEqual(stats.by_activity["bash_git"].weighted,
                               stats.by_activity["edit"].weighted)
        self.assertAlmostEqual(sum(b.weighted for b in stats.by_activity.values()),
                               stats.weighted)

    def test_text_report(self):
        out = self.run_cli("--all", "--daily", "--chart")
        self.assertIn("CLAUDE CODE TOKEN USAGE — all history", out)
        self.assertIn("DAY BY DAY", out)
        self.assertIn("fix the login bug", out)
        self.assertIn("Explore", out)
        self.assertIn("such calls: 1", out)

    def test_private_hides_names(self):
        out = self.run_cli("--all", "--private")
        self.assertNotIn("fix the login bug", out)
        self.assertNotIn("myproj", out)
        self.assertIn("project-1", out)

    def test_polish(self):
        i18n.set_lang("en")
        out = self.run_cli("--all", "-l", "pl")
        self.assertIn("ZUŻYCIE TOKENÓW CLAUDE CODE — cała historia", out)

    def test_session_and_list(self):
        out = self.run_cli("--session", "1111")
        self.assertIn("SESSION PHASES", out)
        self.assertIn("now add a test", out)
        listing = self.run_cli("--list")
        self.assertIn(SESSION[:8], listing)

    def test_html(self):
        path = os.path.join(self.tmp.name, "r.html")
        self.run_cli("--all", "--daily", "--html", path)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("<style>", page)
        self.assertIn("getElementById('tip')", page)
        self.assertIn("Day by day", page)
        self.assertTrue(page.rstrip().endswith("</body></html>"))

    def test_no_data(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_cli("--date", "2020-01-01")
        self.assertIn("no data", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
