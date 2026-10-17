"""Bash noise and unused skills."""
import datetime
import json
import os
import tempfile
import unittest

from token_report import i18n
from token_report.classify import command_family, limits_output
from token_report.transcripts import Call, Prompt, SessionMeta, load
from token_report.waste import NOISY_TOKENS, find_waste

T0 = datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc)
BIG = NOISY_TOKENS * 4 + 400  # characters of a noisy result


def _call(n, tools, results, session="s1"):
    key = ("proj", session)
    call = Call(time=T0 + datetime.timedelta(minutes=n), model="claude-opus-5", session_key=key,
                file_key=key + (None,), agent_id=None, is_subagent=False,
                tools={i: t for i, t in enumerate(tools)}, result_chars=dict(enumerate(results)))
    call._finish()
    return call


class CommandTest(unittest.TestCase):
    def test_family(self):
        self.assertEqual(command_family("git -C x diff HEAD"), "git diff")
        self.assertEqual(command_family("cd a && npm run test -- --bail"), "npm run test")
        self.assertEqual(command_family("python3 -m pytest tests"), "python -m pytest")
        self.assertEqual(command_family("cd a && sed -n 1,5p f && git diff"), "git diff")
        self.assertEqual(command_family("cat f | head"), "cat")
        self.assertEqual(command_family("cd /tmp"), "?")

    def test_limits_output(self):
        for command in ("pytest -q", "git log --oneline", "cat f | head -20", "npm test > o.txt",
                        "sed -n 1,20p f", "grep -rn x . | wc -l", "git diff --stat"):
            with self.subTest(command=command):
                self.assertTrue(limits_output(command))
        for command in ("git diff", "cat f", "grep -rn x .", "pytest 2>&1", "python3 -m pytest"):
            with self.subTest(command=command):
                self.assertFalse(limits_output(command))


class BashNoiseTest(unittest.TestCase):
    def test_only_long_unlimited_results_count(self):
        calls = [_call(i, [("Bash", {"command": "git diff"})], [BIG]) for i in range(3)]
        calls.append(_call(4, [("Bash", {"command": "git diff --stat"})], [BIG]))  # limited
        calls.append(_call(5, [("Bash", {"command": "git status"})], [40]))  # short
        calls.append(_call(6, [("Read", {"file_path": "x"})], []))
        w = find_waste(calls, {})
        self.assertEqual(w.bash_results, 5)
        self.assertEqual([f.name for f in w.families], ["git diff"])
        self.assertEqual(w.families[0].unlimited, 3)
        self.assertEqual(w.families[0].runs, 4)  # the limited one counts as a run
        self.assertEqual(w.noisy_tokens, 3 * (BIG // 4))
        # the first result is re-read by the calls after it, the last one by none
        self.assertGreater(w.families[0].weighted, 3 * (BIG // 4) * 1.25)

    def test_a_kind_seen_once_is_not_reported(self):
        w = find_waste([_call(0, [("Bash", {"command": "cat big.txt"})], [BIG])], {})
        self.assertEqual(w.families, [])
        self.assertEqual(w.noisy_tokens, BIG // 4)


class SkillsTest(unittest.TestCase):
    def _sessions(self, prompts=()):
        meta = SessionMeta("proj", skills={"plan-tracker": 400, "pdf": 200, "docx": 200,
                                           "run": 80})
        meta.prompts = [Prompt(T0, "prompt", text) for text in prompts]
        return {("proj", "s1"): meta}

    def test_used_unused_and_named(self):
        calls = [_call(0, [("Skill", {"skill": "plan-tracker"}),
                           ("Read", {"file_path": "/a/report.pdf"}),
                           ("Bash", {"command": "run build"})], [])]
        w = find_waste(calls, self._sessions(["please use docx"]))
        sk = w.skills
        self.assertEqual(sk.conversations, 1)
        self.assertEqual(dict(sk.used), {"plan-tracker": 1})
        self.assertEqual([r.name for r in sk.unused()][:2], ["pdf", "run"])  # named ones first
        self.assertEqual(dict(sk.named), {"pdf": 1, "run": 1})  # "docx" is a plain word
        self.assertEqual(sk.unused_tokens(), (200 + 200 + 80) // 4)

    def test_slash_command_counts_as_use(self):
        w = find_waste([_call(0, [], [])], self._sessions(["/plan-tracker next step"]))
        self.assertEqual(dict(w.skills.used), {"plan-tracker": 1})


class LoaderTest(unittest.TestCase):
    def test_result_sizes_and_skill_listing(self):
        listing = ("- plan-tracker: Plans work.\n- anthropic-skills:pdf: Handles PDFs.\n"
                   "- fake: a bullet inside the description")
        records = [
            {"type": "attachment", "timestamp": "2026-09-01T10:00:00Z",
             "attachment": {"type": "skill_listing", "content": listing,
                            "names": ["plan-tracker", "anthropic-skills:pdf"]}},
            {"type": "assistant", "timestamp": "2026-09-01T10:00:05Z", "cwd": "/p",
             "message": {"id": "m1", "model": "claude-opus-5",
                         "usage": {"input_tokens": 1, "output_tokens": 1},
                         "content": [{"type": "tool_use", "id": "tu1", "name": "Bash",
                                      "input": {"command": "ls"}}]}},
            {"type": "user", "timestamp": "2026-09-01T10:00:06Z",
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": "tu1",
                  "content": [{"type": "text", "text": "x" * 123}]}]}},
        ]
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "proj", "s1.jsonl")
            os.makedirs(os.path.dirname(path))
            with open(path, "w") as f:
                f.write("\n".join(json.dumps(r) for r in records))
            calls, sessions = load(root, None, None)
        self.assertEqual(calls[0].result_chars, {"tu1": 123})
        skills = sessions[("proj", "s1")].skills
        self.assertEqual(set(skills), {"plan-tracker", "anthropic-skills:pdf"})
        self.assertEqual(skills["plan-tracker"], len("- plan-tracker: Plans work.\n"))


class RenderTest(unittest.TestCase):
    def test_reports_mention_both_sections(self):
        from token_report.context import ReportContext
        from token_report.naming import Namer
        from token_report.report_html import html_report
        from token_report.report_text import text_report
        from token_report.stats import aggregate

        i18n.set_lang("en")
        namer = Namer(private=False)
        sessions = {("proj", "s1"): SessionMeta("proj", skills={"a-skill": 400, "b-skill": 400,
                                                                  "c-skill": 400, "d-skill": 400,
                                                                  "e-skill": 400})}
        calls = [_call(i, [("Bash", {"command": "git diff"})], [BIG]) for i in range(3)]
        stats = aggregate(calls, sessions, namer)
        ctx = ReportContext("period", "~/.claude/projects", sessions, namer, calls, full=True)
        text = text_report(stats, ctx)
        self.assertIn("BASH NOISE", text)
        self.assertIn("git diff --stat", text)
        self.assertIn("SKILLS", text)
        self.assertIn("never used", text)
        page = html_report(stats, ctx)
        self.assertIn("Bash noise", page)
        self.assertIn("a-skill", page)
        private = text_report(aggregate(calls, sessions, Namer(private=True)),
                              ReportContext("p", "~", sessions, Namer(private=True), calls,
                                           full=True))
        self.assertNotIn("a-skill", private)
        self.assertIn("skill-1", private)


if __name__ == "__main__":
    unittest.main()
