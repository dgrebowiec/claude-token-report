"""The project map: what Claude looks up again and again, and what CLAUDE.md already says."""
import datetime
import os
import tempfile
import unittest

from token_report import i18n
from token_report.classify import file_commands
from token_report.hotspots import (_lookups, find_hotspots, instruction_files, linked_docs,
                                    symbols_in)
from token_report.transcripts import Call, SessionMeta

T0 = datetime.datetime(2026, 9, 1, 10, 0, tzinfo=datetime.timezone.utc)


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _call(session, tools):
    key = ("proj", session)
    return Call(time=T0, model="claude-opus-5", session_key=key, file_key=key + (None,),
                agent_id=None, is_subagent=False,
                tools={i: tool for i, tool in enumerate(tools)})


class SymbolsTest(unittest.TestCase):
    def test_symbols_in_patterns(self):
        self.assertEqual(symbols_in(r"\bUserManager\b|fun loadUser"), {"UserManager", "loadUser"})
        self.assertEqual(symbols_in("**/*ShopDialog*.kt"), {"ShopDialog"})
        self.assertEqual(symbols_in("detect_lang"), {"detect_lang"})
        # plain words, short names and noise are not symbols
        self.assertEqual(symbols_in("class|import|Test|^diff --git|node_modules|aB"), set())

    def test_piped_grep_is_not_a_search(self):
        self.assertEqual(file_commands("git log | grep FooBar"), [("git", "log")])
        self.assertEqual(len(file_commands("find . -name '*.kt' | xargs grep FooBar")), 2)

    def test_bash_lookups(self):
        def lookups(command):
            return sorted((k, v) for k, v, _ in _lookups("Bash", {"command": command}))

        self.assertEqual(lookups("grep -rn -A3 'fun saveUser' src/"), [("symbol", "saveUser")])
        self.assertEqual(lookups("rg -e UserManager -e load_user"),
                         [("symbol", "UserManager"), ("symbol", "load_user")])
        self.assertEqual(lookups("git grep -n parseConfig"), [("symbol", "parseConfig")])
        self.assertEqual(lookups("find app -iname '*PackageType*'"), [("symbol", "PackageType")])
        self.assertEqual(lookups("adb logcat | grep mCurrentFocus"), [])
        self.assertEqual(lookups("sed -n 1,80p src/app.py"), [("bash_file", "src/app.py")])
        self.assertEqual(lookups("sed -i s/a/b/ src/app.py"), [])

    def test_cd_and_search_paths(self):
        found = list(_lookups("Bash", {"command": "cd ~/other && grep -rn FooBar src"}))
        self.assertEqual(found, [("symbol", "FooBar", ["~/other/src"])])
        found = list(_lookups("Grep", {"pattern": "FooBar", "path": "/elsewhere"}))
        self.assertEqual(found, [("symbol", "FooBar", ["/elsewhere"])])


class InstructionFilesTest(unittest.TestCase):
    def test_claude_md_imports_rules_and_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            home, root = os.path.join(tmp, "home"), os.path.join(tmp, "home", "proj")
            _write(os.path.join(root, "CLAUDE.md"),
                   "See @docs/map.md and `@not/imported.md`, mail me@example.com\n")
            _write(os.path.join(root, "docs", "map.md"), "UserManager lives in user.py\n")
            _write(os.path.join(root, ".claude", "rules", "ui", "views.md"), "views\n")
            _write(os.path.join(root, "AGENTS.md"), "agents\n")
            _write(os.path.join(home, ".claude", "CLAUDE.md"), "user prefs\n")
            names = [os.path.relpath(p, tmp) for p, _ in instruction_files(root, home)]
            self.assertEqual(names, ["home/proj/CLAUDE.md", "home/proj/docs/map.md",
                                     "home/.claude/CLAUDE.md",
                                     "home/proj/.claude/rules/ui/views.md"])
            os.remove(os.path.join(root, "CLAUDE.md"))  # AGENTS.md counts only without CLAUDE.md
            names = [os.path.basename(p) for p, _ in instruction_files(root, home)]
            self.assertIn("AGENTS.md", names)

    def test_linked_docs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "proj")
            _write(os.path.join(root, "docs", "router.md"), "UserManager: src/user.kt\n")
            _write(os.path.join(root, "docs", "plan.md"), "plan\n")
            _write(os.path.join(tmp, "outside.md"), "outside\n")
            claude_md = os.path.join(root, "CLAUDE.md")
            loaded = [(claude_md, "Read [the router](docs/router.md) first; see `docs/plan.md`, "
                                  "[gone](docs/missing.md), [out](../outside.md)")]
            names = [os.path.relpath(p, root) for p, _ in linked_docs(root, loaded)]
            self.assertEqual(names, [os.path.join("docs", "router.md"),
                                     os.path.join("docs", "plan.md")])


class FindHotspotsTest(unittest.TestCase):
    def setUp(self):
        i18n.set_lang("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.root = os.path.join(self.home, "proj")
        _write(os.path.join(self.root, "src", "UserManager.kt"), "line\n" * 900)
        _write(os.path.join(self.root, "src", "small.py"), "x\n")
        _write(os.path.join(self.root, "CLAUDE.md"), "# Proj\n- `src/small.py` — helpers\n")
        self.sessions = {("proj", s): SessionMeta("proj", cwd=self.root) for s in "abc"}

    def tearDown(self):
        self.tmp.cleanup()

    def hotspots(self, calls):
        return find_hotspots(calls, self.sessions, home=self.home)

    def test_lookups_across_conversations(self):
        user_manager = os.path.join(self.root, "src", "UserManager.kt")
        calls = []
        for session in "abc":
            calls += [_call(session, [("Read", {"file_path": user_manager})]),
                      _call(session, [("Read", {"file_path": "src/small.py"})]),
                      _call(session, [("Grep", {"pattern": "UserManager"}),
                                      ("Bash", {"command": "grep -rn userManager src"})]),
                      _call(session, [("Read", {"file_path": "/tmp/scratch/x.png"})])]
        calls += [_call("a", [("Read", {"file_path": user_manager})])] * 3
        calls += [_call("a", [("Grep", {"pattern": "OtherThing", "path": "/elsewhere"})])] * 9

        [project] = self.hotspots(calls)
        self.assertEqual(project.root, self.root)
        self.assertEqual([(i.name, i.uses, i.sessions, i.documented, i.lines)
                          for i in project.files],
                         [(os.path.join("src", "UserManager.kt"), 6, 3, False, 900)])
        [symbol] = project.symbols  # userManager merged into UserManager; OtherThing elsewhere
        self.assertEqual((symbol.name, symbol.uses, symbol.documented, symbol.path),
                         ("UserManager", 6, False, os.path.join("src", "UserManager.kt")))
        self.assertEqual(project.draft(), [
            f"- `UserManager` — `{os.path.join('src', 'UserManager.kt')}` — …"])
        self.assertEqual([f.name for f in project.instructions], ["CLAUDE.md"])

    def test_linked_map_counts_as_documented(self):
        _write(os.path.join(self.root, "CLAUDE.md"), "Where is X: [map](docs/map.md)\n")
        _write(os.path.join(self.root, "docs", "map.md"), "- UserManager: src/UserManager.kt\n")
        calls = [_call(s, [("Grep", {"pattern": "UserManager"}),
                           ("Grep", {"pattern": "OrderQueue"})]) for s in "abc"] * 2
        [project] = self.hotspots(calls)
        by_name = {i.name: i for i in project.symbols}
        self.assertTrue(by_name["UserManager"].linked)
        self.assertFalse(by_name["OrderQueue"].linked)
        self.assertEqual(project.draft(), ["- `OrderQueue` — …"])

    def test_one_conversation_is_not_a_pattern(self):
        calls = [_call("a", [("Grep", {"pattern": "UserManager"})])] * 6
        calls.append(_call("b", [("Read", {"file_path": "src/small.py"})]))
        self.assertEqual(self.hotspots(calls), [])

    def test_home_directory_is_not_a_project(self):
        self.sessions = {("proj", "a"): SessionMeta("proj", cwd=self.home),
                         ("proj", "b"): SessionMeta("proj", cwd=self.home)}
        calls = [_call(s, [("Grep", {"pattern": "UserManager"})]) for s in "ab"] * 5
        self.assertEqual(self.hotspots(calls), [])


if __name__ == "__main__":
    unittest.main()
