import argparse
import datetime
import unittest

from token_report import i18n
from token_report.classify import NO_TOOL, classify_bash, classify_tool
from token_report.formatting import arrow, fmt_change, fmt_tok, short
from token_report.periods import parse_day, resolve_window
from token_report.pricing import model_weight, split_usage, weighted_by_type


class ClassifyBashTest(unittest.TestCase):
    def test_groups(self):
        cases = {
            "grep -rn foo src": "bash_search",
            "cat a.txt | head -5": "bash_read",
            "git status": "bash_git",
            "gh pr view 12": "bash_gh",
            "npm install left-pad": "bash_pkg",
            "npm run build": "bash_build",
            "python3 script.py": "bash_script",
            "./gradlew test": "bash_build",
            "./run.sh": "bash_script",
            "docker ps": "bash_container",
            "curl -s https://example.com": "bash_net",
            "sleep 5": "bash_wait",
            "mkdir -p out": "bash_fileops",
            "some-unknown-tool --flag": "bash_other",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(classify_bash(command), expected)

    def test_skips_trivial_commands_and_prefixes(self):
        self.assertEqual(classify_bash("cd /repo && git log"), "bash_git")
        self.assertEqual(classify_bash("FOO=1 sudo -E pytest -x"), "bash_build")
        self.assertEqual(classify_bash("for f in *.py; do wc -l $f; done"), "bash_read")
        self.assertEqual(classify_bash("ls > out.txt 2>&1"), "bash_search")

    def test_unparseable_and_empty(self):
        self.assertEqual(classify_bash("echo 'unterminated"), "bash_other")
        self.assertEqual(classify_bash(""), "bash_other")
        self.assertEqual(classify_bash(None), "bash_other")


class ClassifyToolTest(unittest.TestCase):
    def test_tools(self):
        self.assertEqual(classify_tool("Read", {}), "read")
        self.assertEqual(classify_tool("MultiEdit", {}), "edit")
        self.assertEqual(classify_tool("Bash", {"command": "git diff"}), "bash_git")
        self.assertEqual(classify_tool("mcp__github__create_issue", {}), "mcp:github")
        self.assertEqual(classify_tool("SomethingNew", {}), "SomethingNew")
        self.assertEqual(classify_tool(None, {}), "?")
        self.assertNotEqual(classify_tool("Read", {}), NO_TOOL)


class PricingTest(unittest.TestCase):
    def test_split_usage_with_and_without_ttl_split(self):
        new = split_usage({"input_tokens": 3, "cache_read_input_tokens": 100,
                           "cache_creation_input_tokens": 30, "output_tokens": 7,
                           "cache_creation": {"ephemeral_5m_input_tokens": 10,
                                              "ephemeral_1h_input_tokens": 20}})
        self.assertEqual(new, {"input": 3, "cache_read": 100, "cache_write_5m": 10,
                               "cache_write_1h": 20, "output": 7})
        old = split_usage({"cache_creation_input_tokens": 30})
        self.assertEqual(old["cache_write_5m"], 30)
        self.assertEqual(old["cache_write_1h"], 0)

    def test_weights(self):
        tokens = {"input": 0, "cache_read": 100_000, "cache_write_5m": 2_000,
                  "cache_write_1h": 0, "output": 500}
        # the worked example from --explain
        self.assertAlmostEqual(sum(weighted_by_type(tokens, "claude-opus-5").values()), 15_000)
        self.assertAlmostEqual(sum(weighted_by_type(tokens, "claude-sonnet-5").values()), 6_000)
        self.assertAlmostEqual(model_weight("claude-opus-5-5"), 0.8)
        self.assertAlmostEqual(model_weight("claude-haiku-4-5-20251001"), 0.2)


class FormattingTest(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")

    def test_fmt_tok(self):
        self.assertEqual(fmt_tok(999), "999")
        self.assertEqual(fmt_tok(12_345), "12k")
        self.assertEqual(fmt_tok(3_400_000), "3.4M")
        self.assertEqual(fmt_tok(2_500_000_000), "2.50B")

    def test_change_and_arrow(self):
        self.assertEqual(fmt_change(150, 100), "+50%")
        self.assertEqual(fmt_change(5, 0), "new")
        self.assertEqual(arrow(100, 100.5), "=")
        self.assertEqual(arrow(120, 100), "▲")
        self.assertEqual(arrow(80, 100), "▼")
        self.assertEqual(arrow(1, None), " ")

    def test_short(self):
        self.assertEqual(short("abc", 5), "abc")
        self.assertEqual(short("~/projects/some-long-name", 10), "…long-name")


def _args(**kw):
    base = dict(days=None, date=None, from_=None, to=None, today=False, yesterday=False,
                all=False, rolling=False)
    base.update(kw)
    return argparse.Namespace(**base)


class PeriodsTest(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")

    def test_parse_day(self):
        today = datetime.date.today()
        self.assertEqual(parse_day("2026-09-15"), datetime.date(2026, 9, 15))
        self.assertEqual(parse_day("15.09.2026"), datetime.date(2026, 9, 15))
        self.assertEqual(parse_day("09-15"), datetime.date(today.year, 9, 15))
        self.assertEqual(parse_day("yesterday"), today - datetime.timedelta(days=1))
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_day("garbage")

    def test_default_is_last_7_days(self):
        w = resolve_window(_args())
        self.assertEqual(w.last_n, 7)
        self.assertEqual((w.last - w.first).days, 6)

    def test_all_history(self):
        w = resolve_window(_args(all=True))
        self.assertIsNone(w.start)

    def test_rolling(self):
        w = resolve_window(_args(days=1.5))
        self.assertEqual(w.rolling, 1.5)
        self.assertAlmostEqual((w.end - w.start).total_seconds(), 1.5 * 86400)

    def test_invalid_combinations(self):
        for args in (_args(days=3, today=True), _args(to=datetime.date(2026, 1, 1)),
                     _args(days=0), _args(date=datetime.date.today() + datetime.timedelta(days=2)),
                     _args(from_=datetime.date(2026, 2, 1), to=datetime.date(2026, 1, 1))):
            with self.subTest(args=args), self.assertRaises(ValueError):
                resolve_window(args)


if __name__ == "__main__":
    unittest.main()
