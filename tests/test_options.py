"""options.resolve: presets, precedence of saved settings and flags, hard errors."""
import contextlib
import io
import os
import tempfile
import unittest
from unittest import mock

from token_report import i18n
from token_report.cli import build_parser, main
from token_report.options import OptionsError, resolve
from token_report.settings import CORE, ELEMENTS, Settings


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
        saved = Settings(level="normal", elements=["activities", "cache"])
        p = plan("--bash", saved=saved)
        self.assertEqual(p.elements, ("activities", "cache", "bash"))
        self.assertEqual(p.base, "config")
        self.assertEqual(p.origin, {"activities": "config", "cache": "config", "bash": "flag"})

    def test_saved_detailed_means_long_tables(self):
        p = plan(saved=Settings(level="detailed", elements=["models", "bash"]))
        self.assertEqual(p.elements, ("models", "bash"))
        self.assertTrue(p.long_tables)

    def test_saved_minimal_is_the_short_set(self):
        p = plan(saved=Settings(level="minimal", elements=["activities", "tips", "cache"]))
        self.assertEqual(p.elements, ("activities",))
        self.assertFalse(p.long_tables)

    def test_preset_and_only_replace_the_saved_settings(self):
        saved = Settings(level="detailed", elements=["bash"])
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
        saved = Settings(level="detailed", elements=["bash"])
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

    def test_separate_commands_take_no_report_options(self):
        for cmd in (["--list"], ["--list", "5"], ["--explain"], ["--configure"], ["--reset-config"]):
            for opt, shown in ((["--bash"], "--bash"), (["--project-map"], "--project-map"),
                               (["--days", "0.5"], "--days"), (["--to", "09-01"], "--to"),
                               (["--rolling"], "--rolling"), (["--short"], "--short"),
                               (["--full"], "--full"), (["--only", "models"], "--only"),
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
