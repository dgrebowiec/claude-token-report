"""options.resolve: presets, precedence of saved settings and flags, hard errors."""
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from token_report import i18n
from token_report.cli import build_parser, main
from token_report.options import (ELEMENT_INFO, OptionsError, describe_plan,
                                  no_comparison_note, resolve, uncompared)
from token_report.settings import CORE, ELEMENTS, Settings, describe_level, from_dict


def args(*argv):
    return build_parser().parse_args(list(argv))


def plan(*argv, saved=None):
    return resolve(args(*argv), saved)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")

    def test_default(self):
        p = plan()
        self.assertEqual(p.elements, CORE)
        self.assertEqual(p.base, "default")
        self.assertFalse(p.long_tables)
        self.assertEqual(set(p.origin.values()), {"default"})
        self.assertEqual(p.notes, ())

    def test_presets(self):
        short = plan("--short")
        self.assertEqual((short.base, short.elements, short.long_tables),
                         ("short", ("activities", "models", "sessions"), False))
        full = plan("--full")
        self.assertEqual((full.base, full.elements, full.long_tables), ("full", ELEMENTS, True))
        self.assertEqual(full.origin["map"], "preset")

    def test_section_flag_adds_to_the_default(self):
        p = plan("--bash", "--project-map")
        self.assertEqual(p.elements, CORE + ("bash", "map"))
        self.assertEqual((p.origin["bash"], p.origin["map"], p.origin["tips"]),
                         ("flag", "flag", "default"))

    def test_section_flag_adds_to_the_preset(self):
        p = plan("--short", "--bash")
        self.assertEqual(p.elements, ("activities", "models", "sessions", "bash"))
        self.assertEqual(p.base, "short")

    def test_section_flag_adds_to_the_saved_settings(self):
        saved = Settings(level="compact", elements=["activities", "cache"])
        p = plan("--bash", saved=saved)
        self.assertEqual(p.elements, ("activities", "cache", "bash"))
        self.assertEqual(p.base, "config")
        self.assertEqual(p.origin, {"activities": "config", "cache": "config", "bash": "flag"})

    def test_saved_long_means_long_tables(self):
        p = plan(saved=Settings(level="long", elements=["models", "bash"]))
        self.assertEqual(p.elements, ("models", "bash"))
        self.assertTrue(p.long_tables)

    def test_saved_compact_means_short_tables(self):
        p = plan(saved=Settings(level="compact", elements=["models", "bash"]))
        self.assertEqual((p.elements, p.long_tables), (("models", "bash"), False))

    def test_long_flag_makes_tables_long_and_keeps_the_elements(self):
        self.assertEqual((plan("--long").elements, plan("--long").long_tables), (CORE, True))
        self.assertEqual(plan("--long").base, "default")
        short = plan("--short", "--long")  # allowed: the short set with long tables
        self.assertEqual((short.base, short.elements, short.long_tables),
                         ("short", ("activities", "models", "sessions"), True))
        saved = Settings(level="compact", elements=["models", "cache"])
        p = plan("--long", saved=saved)
        self.assertEqual((p.base, p.elements, p.long_tables), ("config", ("models", "cache"), True))
        self.assertTrue(plan("--only", "models", "--long").long_tables)
        self.assertTrue(plan("--full", "--long").long_tables)

    def test_element_info_covers_every_element(self):
        self.assertEqual(set(ELEMENT_INFO), set(ELEMENTS))
        self.assertEqual([e for e in ELEMENTS if ELEMENT_INFO[e].has_tables],
                         ["activities", "models", "sessions", "skills"])
        self.assertEqual([e for e in ELEMENTS if ELEMENT_INFO[e].comparable],
                         ["activities", "models", "time", "breakdown", "cache", "bash"])
        self.assertIn("bash", describe_level("long"))
        self.assertNotIn("models", describe_level("long"))
        self.assertIn("5", describe_level("compact"))


class MigrationTest(unittest.TestCase):
    """the levels minimal / normal / detailed of older versions"""

    def test_minimal_keeps_the_short_elements(self):
        s = from_dict({"level": "minimal", "elements": ["activities", "tips", "cache"]})
        self.assertEqual((s.level, s.elements), ("compact", ["activities"]))
        self.assertEqual(plan(saved=s).elements, ("activities",))

    def test_minimal_without_short_elements_gets_all_three(self):
        s = from_dict({"level": "minimal", "elements": ["bash", "cache"]})
        self.assertEqual((s.level, s.elements), ("compact", ["activities", "models", "sessions"]))

    def test_normal_is_compact(self):
        s = from_dict({"level": "normal", "elements": ["models", "cache"]})
        self.assertEqual((s.level, s.elements), ("compact", ["models", "cache"]))

    def test_detailed_is_long_with_the_same_elements(self):
        s = from_dict({"level": "detailed", "elements": ["bash", "models"]})
        self.assertEqual((s.level, s.elements), ("long", ["models", "bash"]))
        p = plan(saved=s)
        self.assertEqual((p.elements, p.long_tables), (("models", "bash"), True))

    def test_new_levels_and_junk(self):
        self.assertEqual(from_dict({"level": "long"}).level, "long")
        self.assertEqual(from_dict({"level": "huge"}).level, "compact")
        self.assertEqual(Settings().level, "compact")
        self.assertEqual(from_dict({"level": "detailed"}).to_dict()["level"], "long")

    def test_preset_and_only_replace_the_saved_settings(self):
        saved = Settings(level="long", elements=["bash"])
        self.assertEqual(plan("--short", saved=saved).elements, ("activities", "models", "sessions"))
        p = plan("--only", "cache,models", saved=saved)
        self.assertEqual((p.base, p.elements, p.long_tables), ("only", ("models", "cache"), False))
        self.assertEqual(p.origin["cache"], "flag")

    def test_only_plus_section_flag(self):
        self.assertEqual(plan("--only", "models", "--skills").elements, ("models", "skills"))

    def test_only_rejects_unknown_names(self):
        with contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit) as cm:
            args("--only", "models,nope")
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("nope", err.getvalue())
        self.assertIn("activities", err.getvalue())

    def test_no_config_ignores_the_saved_settings(self):
        saved = Settings(level="long", elements=["bash"])
        p = plan("--no-config", "--cache", saved=saved)
        self.assertEqual((p.base, p.elements, p.long_tables), ("default", CORE + ("cache",), False))

    def test_md_alone_is_full(self):
        p = plan("--md", "x.md")
        self.assertEqual((p.base, p.elements, p.long_tables), ("md", ELEMENTS, True))
        self.assertEqual(plan("--md", "x.md", "--bash").base, "default")
        self.assertEqual(plan("--md", "x.md", saved=Settings(elements=["models"])).base, "config")
        self.assertEqual(plan("--md", "x.md", "--no-config",
                              saved=Settings(elements=["models"])).base, "md")

    def test_modifiers(self):
        p = plan("--diff", "--daily")
        self.assertTrue(p.diff and p.daily and not p.session)
        p = plan("--session", "--daily")  # the days of one session: allowed
        self.assertTrue(p.session and p.daily)
        self.assertTrue(p.has("activities"))
        self.assertFalse(p.has("bash"))

    def test_diff_notes_the_elements_without_comparison(self):
        self.assertEqual(plan("--skills").notes, ())  # no --diff: nothing to note
        p = plan("--skills", "--diff")
        self.assertEqual(uncompared(p.elements), ("sessions", "tips", "skills"))
        self.assertEqual(len(p.notes), 1)
        self.assertTrue(p.notes[0].endswith(": sessions, tips, skills"))
        self.assertEqual(plan("--only", "activities,models,cache", "--diff").notes, ())
        self.assertTrue(plan("--only", "activities,map", "--diff").notes[0].endswith(": map"))
        self.assertEqual(no_comparison_note(("activities", "bash")), "")

    def assertError(self, *argv, words=()):
        with self.assertRaises(OptionsError) as cm:
            plan(*argv)
        for w in words:
            self.assertIn(w, str(cm.exception))

    def test_hard_errors(self):
        self.assertError("--short", "--full", words=("--short", "--full"))
        self.assertError("--short", "--only", "models", words=("--only", "--short"))
        self.assertError("--full", "--only", "models", words=("--only", "--full"))
        self.assertError("--session", "--diff", words=("--session", "--diff"))
        self.assertError("--session", "abc", "--diff", words=("--session", "--diff"))
        self.assertError("--all", "--diff", words=("--all", "--diff"))
        plan("--all", "--daily")  # day by day over all history: allowed
        plan("--days", "2", "--rolling", "--diff")  # a rolling window has a previous one

    def test_separate_commands_take_no_report_options(self):
        for cmd in (["--list"], ["--list", "5"], ["--explain"], ["--configure"], ["--reset-config"]):
            for opt, shown in ((["--bash"], "--bash"), (["--project-map"], "--project-map"),
                               (["--days", "0.5"], "--days"), (["--to", "09-01"], "--to"),
                               (["--rolling"], "--rolling"), (["--short"], "--short"),
                               (["--full"], "--full"), (["--long"], "--long"),
                               (["--only", "models"], "--only"),
                               (["--diff"], "--diff"), (["--daily"], "--daily"),
                               (["--session"], "--session"), (["--html", "x"], "--html"),
                               (["--md", "x"], "--md"), (["--private"], "--private"),
                               (["--no-config"], "--no-config"), (["--today"], "--today")):
                with self.subTest(cmd=cmd, opt=opt):
                    self.assertError(*cmd, *opt, words=(cmd[0], shown))
        self.assertError("--list", "--explain", words=("--list", "--explain"))

    def test_global_options_are_allowed_with_commands(self):
        for cmd in ("--list", "--explain", "--configure", "--reset-config"):
            plan(cmd, "--lang", "pl", "--no-color", "--dir", "/x")
            plan(cmd, "--color")


class DescribePlanTest(unittest.TestCase):
    """the footer "Settings of this report" (options.describe_plan)"""

    def setUp(self):
        i18n.set_lang("en")

    def footer(self, *argv, saved=None, prev=""):
        return describe_plan(plan(*argv, saved=saved), prev, config_path="/cfg/settings.json")

    def test_default(self):
        lines = self.footer()
        self.assertEqual(lines[0], "Settings: the default set · compact tables (5 rows)")
        self.assertEqual(lines[1], "More detail: --time --breakdown --cache --bash --skills "
                                   "--project-map  or --full (everything)")
        self.assertEqual(lines[2], "Your own saved set: --configure · "
                                   "raw and weighted tokens: --explain")
        self.assertEqual(len(lines), 3)

    def test_config_with_a_section_flag(self):
        saved = Settings(level="long", elements=["activities", "cache"])
        lines = self.footer("--bash", saved=saved)
        self.assertEqual(lines[0], "Settings: sections from the configuration "
                                   "(/cfg/settings.json) + --bash · long tables (10 rows)")
        self.assertIn("--time --breakdown --skills --project-map", lines[1])
        self.assertTrue(lines[2].startswith("Without the configuration: --no-config · "
                                            "change it: --configure"))

    def test_short_with_diff_and_daily(self):
        lines = self.footer("--short", "--diff", "--daily", prev="2026-10-08..2026-10-14 (7 days)")
        self.assertEqual(lines[0], "Settings: --short · compact tables (5 rows) · compared with "
                                   "2026-10-08..2026-10-14 (7 days), not compared: sessions · "
                                   "day by day")
        # the "Not compared" line is under the comparison already: not repeated as its own line
        self.assertFalse(any(l.startswith("Not compared") for l in lines))

    def test_only_and_full(self):
        self.assertEqual(self.footer("--only", "models,cache", "--bash")[0],
                         "Settings: --only models,cache + --bash · compact tables (5 rows)")
        full = self.footer("--full")
        self.assertEqual(full[0], "Settings: --full · long tables (10 rows)")
        self.assertEqual(len(full), 2)  # nothing left out: no "More detail"
        self.assertIn("--md default", self.footer("--md", "x")[0])

    def test_polish(self):
        i18n.set_lang("pl")
        try:
            lines = self.footer("--long", "--diff")
        finally:
            i18n.set_lang("en")
        self.assertEqual(lines[0], "Ustawienia: zestaw domyślny · tabele długie (10 wierszy) · "
                                   "porównanie z poprzednim okresem, bez porównania: sessions, tips")
        self.assertTrue(lines[1].startswith("Więcej szczegółów: --time"))

    def test_config_path_shown_with_a_tilde(self):
        home = os.path.expanduser("~")
        with mock.patch.dict(os.environ, {"CLAUDE_TOKEN_REPORT_CONFIG":
                                          os.path.join(home, ".claude", "x.json")}):
            line = describe_plan(plan(saved=Settings(elements=["models"])))[0]
        self.assertIn("(~/.claude/x.json)", line)


class CliErrorTest(unittest.TestCase):
    """the errors reach the user as argparse errors (exit code 2), before anything runs"""

    def setUp(self):
        i18n.set_lang("en")
        self.tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {
            "CLAUDE_TOKEN_REPORT_CONFIG": os.path.join(self.tmp.name, "settings.json")})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self.tmp.cleanup()

    def run_error(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()), \
                self.assertRaises(SystemExit) as cm:
            main(["--dir", os.path.join(self.tmp.name, "missing"), *argv])
        self.assertEqual(cm.exception.code, 2)
        return err.getvalue()

    def test_errors_exit_with_code_2(self):
        self.assertIn("--short and --full", self.run_error("--short", "--full"))
        self.assertIn("--session", self.run_error("--session", "--diff"))
        self.assertIn("all history has no previous window", self.run_error("--all", "--diff"))
        out = self.run_error("--list", "--bash")
        self.assertIn("separate command", out)
        self.assertIn("--bash", out)

    def test_reset_config_with_report_options_does_not_remove_the_file(self):
        path = os.environ["CLAUDE_TOKEN_REPORT_CONFIG"]
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"level": "normal", "elements": ["models"]}')
        self.run_error("--reset-config", "--bash")
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
