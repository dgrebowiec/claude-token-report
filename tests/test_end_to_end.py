"""Runs the whole pipeline on a small synthetic ~/.claude/projects directory."""
import contextlib
import datetime
import html
import io
import json
import os
import tempfile
import unittest
from unittest import mock

from token_report import i18n
from token_report.cli import main
from token_report.naming import Namer
from token_report.session_detail import session_detail
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
        _user(0, "fix the login bug ultracode"),
        {"type": "attachment", "timestamp": _ts(0.5), "attachment": {"type": "ultra_effort_enter"}},
        _assistant(1, "m1", _usage(write=30_000),
                   tools=[("Read", {"file_path": "/home/user/myproj/app.py"})],
                   effort="xhigh", gitBranch="main", version="2.1.289"),
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
        _assistant(69, "m5", _usage(cache_read=5_000, output=800), model="claude-sonnet-5",
                   tools=[("Workflow", {"script": "..."})], effort="high"),
    ]
    _write_jsonl(os.path.join(root, PROJECT, SESSION + ".jsonl"), main_records)
    sub_dir = os.path.join(root, PROJECT, SESSION, "subagents")
    _write_jsonl(os.path.join(sub_dir, f"agent-{AGENT}.jsonl"), [
        _user(3, "find it", isSidechain=True),
        _assistant(3.5, "s1", _usage(write=8_000), tools=[("Grep", {"pattern": "login"})],
                   model="claude-haiku-4-5", isSidechain=True),
    ])
    # an agent of a Workflow run, one directory level deeper
    run_dir = os.path.join(sub_dir, "workflows", "wf_1234")
    _write_jsonl(os.path.join(run_dir, "agent-f00dcafe01.jsonl"), [
        _assistant(70, "w1", _usage(write=6_000), model="claude-sonnet-5", isSidechain=True,
                   tools=[("Bash", {"command": "cat src/login.py"})]),
    ])
    _write_jsonl(os.path.join(run_dir, "journal.jsonl"), [{"type": "launched"}])
    with open(os.path.join(run_dir, "agent-f00dcafe01.meta.json"), "w") as f:
        json.dump({"agentType": "workflow-subagent", "description": "review:login"}, f)


class EndToEndTest(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.join(self.tmp.name, "projects")
        make_transcripts(self.root)
        self.config = os.path.join(self.tmp.name, "settings.json")  # never the user's real file
        self._env = mock.patch.dict(os.environ, {"CLAUDE_TOKEN_REPORT_CONFIG": self.config})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--dir", self.root, *args])
        return out.getvalue()

    def test_load_and_aggregate(self):
        calls, sessions = load(self.root, None, None)
        self.assertEqual([c.time for c in calls], sorted(c.time for c in calls))
        self.assertEqual(len(calls), 7)  # m4 is logged twice but counted once
        m4 = next(c for c in calls if c.tokens["output"] == 300)
        self.assertEqual(len(m4.tools), 2)
        sub = [c for c in calls if c.is_subagent]
        self.assertEqual(len(sub), 2)
        self.assertEqual(sub[0].agent_type, "Explore")
        self.assertEqual(sub[0].agent_task, "")
        self.assertEqual((sub[1].agent_type, sub[1].agent_task), ("workflow-subagent", "review:login"))

        meta = sessions[(PROJECT, SESSION)]
        self.assertEqual(meta.topic, "fix the login bug ultracode")
        self.assertEqual([p.text for p in meta.prompts],
                         ["fix the login bug ultracode", "/compact", "now add a test"])
        self.assertEqual((meta.git_branch, meta.version), ("main", "2.1.289"))
        self.assertEqual(len(meta.ultracode), 1)

        stats = aggregate(calls, sessions, Namer(private=False))
        self.assertEqual(stats.n_calls, 7)
        self.assertEqual(stats.n_sessions, 1)
        self.assertEqual(stats.n_subagents, 2)
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

    def test_session_detail(self):
        calls, sessions = load(self.root, None, None)
        d = session_detail((PROJECT, SESSION), calls, sessions[(PROJECT, SESSION)],
                           Namer(private=False))
        self.assertEqual(d.calls, 7)
        self.assertEqual(d.branch, "main")
        self.assertEqual([m.model for m in d.models][0], "claude-opus-5")
        self.assertEqual(sum(m.sub_calls for m in d.models), 2)
        self.assertEqual({level: u.calls for level, u in d.efforts}, {"xhigh": 1, "high": 1, "?": 5})
        self.assertEqual((len(d.ultracode_on), d.ultracode_requests, d.workflows), (1, 1, 1))
        self.assertEqual({a.agent_id for a in d.agents}, {AGENT, "f00dcafe01"})
        files = {f.name: f for f in d.files}
        self.assertEqual((files["app.py"].reads, files["app.py"].edits), (2, 1))
        self.assertIn("src/login.py", files)
        self.assertEqual(d.searches["login"], 1)
        self.assertAlmostEqual(sum(m.weighted for m in d.models), d.weighted)

    def test_text_report(self):
        out = self.run_cli("--all", "--daily", "--full")
        self.assertIn("CLAUDE CODE TOKEN USAGE — all history", out)
        self.assertIn("DAY BY DAY", out)
        self.assertIn("fix the login bug", out)
        self.assertIn("Explore", out)
        self.assertIn("such calls: 1", out)
        self.assertNotIn("\033[", out)
        colored = self.run_cli("--all", "--color")
        self.assertIn("\033[1;36m", colored)
        plain = self.run_cli("--all", "--no-color")
        self.assertNotIn("\033[", plain)

    def test_private_hides_names(self):
        out = self.run_cli("--all", "--private", "--full")
        self.assertNotIn("fix the login bug", out)
        self.assertNotIn("myproj", out)
        self.assertIn("project-1", out)
        self.assertIn("PROJECT MAP", out)
        self.assertIn("Hidden with --private", out)

    def test_default_report_is_core_only(self):
        out = self.run_cli("--all")
        for title in ("WHERE THE TOKENS GO", "MODELS", "HEAVIEST CONVERSATIONS",
                      "WHAT YOU COULD IMPROVE"):
            self.assertIn(title, out)
        for title in ("EXPIRED CACHE", "PROJECT MAP", "BASH NOISE", "SKILLS —",
                      "TOKEN TYPES", "SUBAGENTS BY TYPE"):
            self.assertNotIn(title, out)
        self.assertIn("--cache", out)  # the tip about the expired cache points to its section
        self.assertIn("More detail: --time --breakdown --cache --bash --skills --project-map", out)

    def test_section_flags(self):
        out = self.run_cli("--all", "--cache", "--breakdown")
        self.assertIn("EXPIRED CACHE", out)
        self.assertIn("SUBAGENTS BY TYPE", out)
        self.assertNotIn("BASH NOISE", out)
        self.assertNotIn("--cache --bash", out)  # a section shown is not offered again
        self.assertIn("More detail: --time --bash --skills --project-map", out)
        full = self.run_cli("--all", "--full")
        self.assertIn("EXPIRED CACHE", full)
        self.assertIn("TOKEN TYPES", full)
        self.assertNotIn("More detail", full)

    def test_html_follows_the_same_flags(self):
        path = os.path.join(self.root, "r.html")
        self.run_cli("--all", "--html", path)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Where the tokens go", page)
        self.assertNotIn("Cache and repeats", page)
        self.assertIn("--cache", page)
        self.run_cli("--all", "--html", path, "--cache")
        with open(path, encoding="utf-8") as f:
            self.assertIn("Cache and repeats", f.read())

    def test_polish(self):
        i18n.set_lang("en")
        out = self.run_cli("--all", "-l", "pl")
        self.assertIn("ZUŻYCIE TOKENÓW CLAUDE CODE — cała historia", out)

    def test_short(self):
        out = self.run_cli("--all", "--short")
        self.assertIn("HEAVIEST CONVERSATIONS", out)
        self.assertIn("WHERE THE TOKENS GO", out)
        self.assertNotIn("EXPIRED CACHE", out)
        self.assertNotIn("PROJECT MAP", out)
        self.assertNotIn("WHAT YOU COULD IMPROVE", out)  # --short has no tips
        self.assertNotIn("without --short", out)  # no separate short mode any more
        self.assertIn("More detail: --time --breakdown", out)

    def test_short_is_a_set_of_elements(self):
        out = self.run_cli("--all", "--short", "--cache", "--bash")
        self.assertIn("EXPIRED CACHE", out)
        self.assertIn("HEAVIEST CONVERSATIONS", out)
        more = out.split("More detail:")[1]
        self.assertNotIn("--bash", more)  # the section is in the report (the data has no noise)
        self.assertNotIn("--cache", more)
        short = self.run_cli("--all", "--short")
        long = self.run_cli("--all", "--short", "--long")
        self.assertNotIn("SUBAGENTS BY TYPE", long)
        # long tables: the same sections, the short set; all rankings follow --long
        heads = [l for l in short.splitlines() if l.startswith("── ")]
        self.assertEqual(heads, [l for l in long.splitlines() if l.startswith("── ")])

    def test_html_short_keeps_comparison_and_daily(self):
        path = os.path.join(self.tmp.name, "r.html")
        self.run_cli("--all", "--short", "--html", path)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Heaviest conversations", page)
        self.assertNotIn("What you could improve", page)
        self.assertNotIn("This is the short report", page)
        self.run_cli("--days", "3650", "--short", "--diff", "--html", path)
        with open(path, encoding="utf-8") as f:
            self.assertIn("<h2>Comparison", f.read())
        self.run_cli("--all", "--short", "--daily", "--html", path)
        with open(path, encoding="utf-8") as f:
            self.assertIn("Day by day", f.read())
        self.run_cli("--all", "--short", "--cache", "--html", path)
        with open(path, encoding="utf-8") as f:
            self.assertIn("Cache and repeats", f.read())

    def test_session_and_list(self):
        out = self.run_cli("--session", "1111")
        self.assertIn("SESSION PHASES", out)
        self.assertIn("now add a test", out)
        self.assertIn("SESSION DETAILS", out)
        self.assertIn("(branch main)", out)
        self.assertIn("on (", out)  # ultracode
        self.assertIn("xhigh", out)
        self.assertIn("review:login", out)
        self.assertIn("src/login.py", out)
        short = self.run_cli("--session", "1111", "--short")
        self.assertIn("SESSION DETAILS", short)
        self.assertIn("SESSION PHASES", short)
        self.assertNotIn("TOKEN TYPES", short)
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
        self.assertIn("<tr class=sess>", page)
        self.assertIn("<tr class=sdet hidden>", page)
        self.assertIn("review:login", page)
        self.assertIn("tr.sess", page)  # the script that expands a session
        self.assertTrue(page.rstrip().endswith("</body></html>"))

    def test_html_short_and_session(self):
        path = os.path.join(self.tmp.name, "r.html")
        self.run_cli("--all", "--short", "--html", path)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Heaviest conversations", page)
        self.assertNotIn("Project map", page)
        self.run_cli("--session", "1111", "--html", path)
        with open(path, encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Session details", page)
        self.assertNotIn("<tr class=sess>", page)

    def test_private_session_detail(self):
        out = self.run_cli("--session", "1111", "--private")
        self.assertNotIn("app.py", out)
        self.assertNotIn("review:login", out)
        self.assertNotIn("branch main", out)

    def test_no_data(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_cli("--date", "2020-01-01")
        self.assertIn("no data", str(cm.exception.code))

    def comparison(self, *args):
        """the --diff block of the text report, of the HTML page and of the Markdown file"""
        text = self.run_cli("--days", "3650", "--diff", *args)
        text = text.split("CLAUDE CODE TOKEN USAGE")[0]
        page_path = os.path.join(self.tmp.name, "r.html")
        md_path = os.path.join(self.tmp.name, "r.md")
        self.run_cli("--days", "3650", "--diff", "--html", page_path, *args)
        self.run_cli("--days", "3650", "--diff", "--md", md_path, *args)
        with open(page_path, encoding="utf-8") as f:
            page = f.read()
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
        page = page[page.index("<h2>Comparison"):]
        page = page[:page.index("<h2>", 5)]
        md = md.split("## Comparison with the previous period")[1].split("## ")[0]
        return text, page, md

    def test_every_format_ends_with_the_settings_footer(self):
        self.save_settings("compact", ["activities", "cache"])
        text = self.run_cli("--days", "3650", "--diff", "--bash")
        page_path = os.path.join(self.tmp.name, "r.html")
        md_path = os.path.join(self.tmp.name, "r.md")
        self.run_cli("--days", "3650", "--diff", "--bash", "--html", page_path)
        self.run_cli("--days", "3650", "--diff", "--bash", "--md", md_path)
        with open(page_path, encoding="utf-8") as f:
            page = f.read()
        with open(md_path, encoding="utf-8") as f:
            md = f.read()
        settings = ("Settings: sections from the configuration (" + self.config
                    + ") + --bash · compact tables (5 rows) · compared with ")
        more = "More detail: --time --breakdown --skills --project-map  or --full (everything)"
        change = "Without the configuration: --no-config · change it: --configure"
        last = [l.strip() for l in text.rstrip().splitlines()[-4:-1]]  # above the closing rule
        self.assertTrue(last[0].startswith(settings), last)
        self.assertNotIn("not compared", last[0])  # activities, cache, bash: all compared
        self.assertEqual(last[1], more)
        self.assertTrue(last[2].startswith(change))
        self.assertEqual(text.count("Settings: "), 1)
        tail = page[page.rindex("<p class=sub>"):page.index("<footer>")]
        self.assertIn(html.escape(settings), tail)
        self.assertIn(more, tail)
        self.assertIn(change, tail)
        footer = md.rstrip().split("## Settings of this report")[1]
        self.assertIn("- " + settings, footer)
        self.assertIn("- " + more, footer)
        self.assertEqual(md.count("Settings: "), 1)  # not in the report block as well
        # the three formats say the same
        self.assertEqual(last, [l[2:] for l in footer.strip().splitlines()][:3])

    def test_footer_follows_the_preset(self):
        self.assertIn("Settings: --short · compact tables (5 rows)", self.run_cli("--all", "--short"))
        out = self.run_cli("--all", "--only", "models", "--long")
        self.assertIn("Settings: --only models · long tables (10 rows)", out)
        self.assertIn("Your own saved set: --configure", out)

    def test_diff_follows_the_elements_of_the_report(self):
        self.save_settings("compact", ["activities", "sessions"])  # no models
        for part in self.comparison():
            low = part.lower()
            self.assertIn("weighted tokens", low)  # the summary numbers: always
            self.assertIn("where the tokens go", low)
            self.assertNotIn("models (weighted)", low)
            self.assertNotIn("projects (weighted)", low)
            self.assertNotIn("takeaways", low)
            self.assertIn("Not compared: sessions", part)
        for part in self.comparison("--breakdown", "--cache", "--time"):
            low = part.lower()
            self.assertIn("projects (weighted)", low)
            self.assertIn("takeaways", low)
            self.assertIn("long conversations", low)
            self.assertIn("cache read", low)  # time: the token types

    def test_diff_names_the_elements_without_comparison(self):
        for part in self.comparison("--no-config", "--skills"):
            self.assertIn("Not compared: sessions, tips, skills", part)
        for part in self.comparison("--only", "activities,models"):
            self.assertNotIn("Not compared", part)

    def save_settings(self, level, elements):
        with open(self.config, "w", encoding="utf-8") as f:
            json.dump({"level": level, "elements": elements}, f)

    def test_saved_settings_choose_elements(self):
        default = self.run_cli("--all")
        self.assertIn("WHAT YOU COULD IMPROVE", default)
        self.save_settings("normal", ["models", "cache"])
        out = self.run_cli("--all")
        self.assertNotIn("WHAT YOU COULD IMPROVE", out)
        self.assertNotIn("WHERE THE TOKENS GO", out)
        self.assertIn("MODELS", out)
        self.assertIn("CONVERSATION LENGTH", out)
        self.assertNotIn("CONVERSATION LENGTH", self.run_cli("--all", "--no-config"))
        added = self.run_cli("--all", "--time")  # a section flag adds to the saved set
        self.assertIn("MODELS", added)
        self.assertIn("CONVERSATION LENGTH", added)
        self.assertNotIn("WHAT YOU COULD IMPROVE", added)
        self.assertIn("TOKEN TYPES", added)

    def test_saved_minimal_level_migrates_to_its_elements(self):
        self.save_settings("minimal", ["activities", "tips", "cache"])
        out = self.run_cli("--all")
        self.assertIn("WHERE THE TOKENS GO", out)
        self.assertNotIn("WHAT YOU COULD IMPROVE", out)
        self.assertNotIn("CONVERSATION LENGTH", out)
        self.assertNotIn("MODELS", out)

    def test_long_flag_lengthens_tables_only(self):
        def headers(*argv):
            return [line for line in self.run_cli("--all", *argv).splitlines()
                    if line.startswith("── ")]
        # the fixture is too small for the longer tables to show; the sections must not change
        self.assertEqual(headers("--long"), headers())
        self.save_settings("compact", ["models", "cache"])
        self.assertEqual(headers("--long"), headers())
        self.assertNotIn("── WHERE THE TOKENS GO", "\n".join(headers("--long")))

    def test_configure_saves_through_the_line_editor(self):
        from token_report import configure
        answers = iter(["l", "5", "w", "y"])  # compact -> long, then toggle "time"
        saved = configure.run(__import__("pathlib").Path(self.config), ask=lambda _p: next(answers),
                              out=lambda _t: None)
        self.assertEqual(str(saved), self.config)
        with open(self.config, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["level"], "long")
        self.assertEqual(data["elements"], ["activities", "models", "sessions", "tips", "time"])

    def test_configure_line_editor_shows_the_summary_before_saving(self):
        from pathlib import Path
        from token_report import configure
        self.save_settings("long", ["activities", "bash"])
        printed, prompts = [], []
        answers = iter(["w", "n", "q"])  # summary, decline, quit

        def ask(prompt):
            prompts.append(prompt)
            return next(answers)
        from pathlib import Path as _P
        before = _P(self.config).read_text(encoding="utf-8")
        self.assertIsNone(configure.run(Path(self.config), ask=ask, out=printed.append))
        text = "\n".join(printed)
        self.assertIn("SETTINGS SUMMARY", text)
        self.assertIn("   ✓ bash        n/a           compared", text)
        self.assertIn("   · skills      yes           not compared", text)
        self.assertIn("⚠ long does not change: bash (fixed length, no tables)", text)
        self.assertIn("not saved — back to editing", text)
        self.assertTrue(prompts[1].startswith("save?"))
        self.assertEqual(_P(self.config).read_text(encoding="utf-8"), before)
        # s: the summary only; the editor is not printed again before the next command
        printed.clear()
        answers = iter(["s", "q"])
        configure.run(Path(self.config), ask=lambda _p: next(answers), out=printed.append)
        after_summary = printed[printed.index(" SETTINGS SUMMARY"):]
        self.assertNotIn("commands:", "\n".join(after_summary))

    def test_configure_full_screen_editor_confirms_in_the_summary(self):
        from token_report import configure
        from token_report.settings import Settings
        editor = configure.Editor(Settings(level="long", elements=["activities", "map"]))
        self.assertIsNone(editor.handle_key("enter"))  # ENTER opens the summary, does not save
        screen = "\n".join(configure.strip_ansi(line) for line in editor.screen(100, 40))
        self.assertIn("SETTINGS SUMMARY", screen)
        self.assertIn("⚠ long does not change: map", screen)
        self.assertIn("ENTER/w save", screen)
        self.assertIsNone(editor.handle_key("space"))  # any other key: back, nothing toggled
        self.assertFalse(editor.summary_open)
        self.assertEqual(editor.settings.elements, ["activities", "map"])
        self.assertIsNone(editor.handle_key("s"))
        self.assertTrue(editor.summary_open)
        self.assertEqual(editor.handle_key("w"), "save")
        editor.summary_open = False
        self.assertIn("s summary", configure.key_help())
        self.assertNotIn("s", configure.KEYS.values())

    def test_configure_section_preview_and_reset(self):
        from token_report import configure
        preview_act = configure.section_preview("activities", "compact", color=False)
        self.assertTrue(any("NA CO IDĄ TOKENY" in line or "WHERE THE TOKENS GO" in line for line in preview_act))
        self.assertGreater(len(configure.section_preview("activities", "long", color=False)),
                           len(preview_act))
        fixed = configure.section_preview("bash", "long", color=False)
        self.assertTrue(any("do not change" in line for line in fixed))
        self.assertFalse(any("do not change" in line
                             for line in configure.section_preview("bash", "compact", color=False)))

        # Test restoring defaults with 'd'
        self.save_settings("detailed", ["bash", "skills"])
        answers = iter(["d", "w", "y"])
        saved = configure.run(__import__("pathlib").Path(self.config), ask=lambda _p: next(answers),
                              out=lambda _t: None)
        with open(self.config, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["level"], "compact")
        self.assertEqual(data["elements"], ["activities", "models", "sessions", "tips"])

    def test_cli_reset_config(self):
        self.save_settings("detailed", ["bash"])
        self.assertTrue(os.path.exists(self.config))
        out = self.run_cli("--reset-config")
        self.assertIn("default", out.lower())
        self.assertFalse(os.path.exists(self.config))
        # Second call when already default
        out2 = self.run_cli("--reset-config")
        self.assertIn("already default", out2.lower())


if __name__ == "__main__":
    unittest.main()
