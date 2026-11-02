import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from episodekeep.db import Story, StoryError
from episodekeep import mcp_server


def fresh():
    d = tempfile.mkdtemp(); return Story(os.path.join(d, "s.db"))


def seeded():
    st = fresh(); st.set_meta("title", "The Salt Road"); st.set_meta("premise", "A caravan crosses the dry sea.")
    st.upsert_character("Mara", "pc", "Scarred caravan guard, 40.", "Dry, short sentences.")
    st.upsert_character("Vell", "npc", "Merchant who owes Mara.")
    st.start_episode("The Crossing"); st.add_quest("Find the well", "Somewhere past the dunes")
    st.log("Vell lied about the cargo", "secret", known_by="Vell, Narrator")
    st.log("The caravan reached the dunes"); st.log("Mara promised to bring the child home", "promise", "Find the well")
    return st


class Core(unittest.TestCase):
    def test_episode_flow(self):
        st = fresh()
        with self.assertRaises(StoryError): st.log("x")                      # no open episode
        st.start_episode("One")
        with self.assertRaises(StoryError): st.start_episode("Two")           # one open at a time
        st.end_episode("It began."); self.assertEqual(st.start_episode(), 2)  # numbers continue

    def test_recap_for_character_hides_secrets_they_dont_know(self):
        st = seeded()
        self.assertIn("Vell lied", st.recap(None))
        self.assertIn("Vell lied", st.recap("Vell"))
        r = st.recap("Mara")
        self.assertNotIn("Vell lied", r); self.assertIn("You are Mara", r); self.assertIn("Dry, short sentences", r)
        self.assertIn("promised to bring the child home", r); self.assertIn("Find the well", r)

    def test_previously_and_quest_close(self):
        st = seeded(); st.end_episode("They crossed the sea of salt."); st.start_episode("Dunes")
        st.update_quest("Find the well", "done")
        r = st.recap("Mara"); self.assertIn("They crossed the sea of salt", r); self.assertNotIn("## Open quests", r)
        self.assertEqual(st.quests("done")[0]["closed_ep"], 2)

    def test_search_is_safe_against_fts_syntax(self):
        st = seeded()
        self.assertEqual(len(st.search("child home")), 1)
        for evil in ('"', "NEAR(", "a OR", "*", "x' --", ""): st.search(evil)  # must not raise

    def test_validation(self):
        st = seeded()
        for bad in (lambda: st.log("x", "bogus"), lambda: st.log("x", quest="nope"), lambda: st.log(""), lambda: st.log("y" * 5000),
                    lambda: st.update_quest("Find the well", "weird"), lambda: st.upsert_character("a", "boss"), lambda: st.recap("Nobody")):
            with self.assertRaises(StoryError): bad()

    def test_persists_across_opens(self):
        st = seeded(); p = st.path; st.close()
        self.assertIn("The caravan reached the dunes", Story(p).recap("Mara"))


class Mcp(unittest.TestCase):
    def rpc(self, st, method, params=None, mid=1):
        return mcp_server.handle(st, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})

    def test_protocol(self):
        st = seeded()
        self.assertEqual(self.rpc(st, "initialize")["result"]["serverInfo"]["name"], "episodekeep")
        self.assertIsNone(mcp_server.handle(st, {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(len(self.rpc(st, "tools/list")["result"]["tools"]), 8)
        r = self.rpc(st, "tools/call", {"name": "recap", "arguments": {"as": "Mara"}})["result"]
        self.assertFalse(r["isError"]); self.assertIn("You are Mara", r["content"][0]["text"])
        e = self.rpc(st, "tools/call", {"name": "log", "arguments": {"text": "x", "kind": "bogus"}})["result"]
        self.assertTrue(e["isError"])
        self.assertEqual(self.rpc(st, "nope")["error"]["code"], -32601)

    def test_stdio_end_to_end(self):
        d = tempfile.mkdtemp(); env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                 {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "start_episode", "arguments": {"title": "Pilot"}}}]
        out = subprocess.run([sys.executable, "-m", "episodekeep", "--db", os.path.join(d, "s.db"), "mcp"], input="\n".join(map(json.dumps, lines)) + "\n\nnot json\n",
                             capture_output=True, text=True, env=env, timeout=30).stdout.strip().splitlines()
        self.assertEqual(len(out), 3); self.assertIn("episode 1 started", out[1]); self.assertIn("-32700", out[2])


class Cli(unittest.TestCase):
    def test_cli(self):
        d = tempfile.mkdtemp(); db = os.path.join(d, "s.db"); env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parent.parent))
        run = lambda *a: subprocess.run([sys.executable, "-m", "episodekeep", "--db", db, *a], capture_output=True, text=True, env=env, timeout=30)
        for a in (("init", "T"), ("character", "Mara", "--pc", "--sheet", "Guard"), ("start", "One"), ("log", "hello world")): self.assertEqual(run(*a).returncode, 0)
        self.assertIn("hello world", run("recap", "--as", "Mara").stdout)
        bad = run("log", "x", "--quest", "ghost"); self.assertEqual(bad.returncode, 1); self.assertIn("no quest", bad.stderr)


if __name__ == "__main__":
    unittest.main()
