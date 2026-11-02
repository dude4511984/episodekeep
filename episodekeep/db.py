"""Episodekeep core: one SQLite file holds a series (episodes, quests, characters, events). Standard library only."""
import json, os, re, sqlite3, time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS characters(id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL COLLATE NOCASE, kind TEXT NOT NULL DEFAULT 'npc',
  sheet TEXT NOT NULL DEFAULT '', voice TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS episodes(id INTEGER PRIMARY KEY, number INTEGER UNIQUE NOT NULL, title TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'open', created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quests(id INTEGER PRIMARY KEY, title TEXT UNIQUE NOT NULL COLLATE NOCASE, status TEXT NOT NULL DEFAULT 'open',
  description TEXT NOT NULL DEFAULT '', opened_ep INTEGER, closed_ep INTEGER, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, episode INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'event',
  text TEXT NOT NULL, quest TEXT NOT NULL DEFAULT '', known_by TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(text, content='events', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS ev_ai AFTER INSERT ON events BEGIN INSERT INTO events_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS ev_ad AFTER DELETE ON events BEGIN INSERT INTO events_fts(events_fts, rowid, text) VALUES('delete', old.id, old.text); END;
"""
KINDS = ("event", "fact", "promise", "secret", "relationship")   # secret/relationship use known_by
QUEST_STATUS = ("open", "done", "failed", "dormant")
MAX_TEXT = 4000


class StoryError(ValueError):
    pass


def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _clean(s, field, limit=MAX_TEXT, required=False):
    s = (s or "").strip()
    if required and not s:
        raise StoryError(f"{field} is empty")
    if len(s) > limit:
        raise StoryError(f"{field} is longer than {limit} characters")
    return s


def default_path():
    return Path(os.environ.get("EPISODEKEEP_DB", "story.db"))


class Story:
    def __init__(self, path=None):
        self.path = Path(path or default_path())
        self.db = sqlite3.connect(str(self.path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- series
    def set_meta(self, key, value):
        self.db.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _clean(value, key)))
        self.db.commit()

    def meta(self, key, default=""):
        r = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    # ---- characters
    def upsert_character(self, name, kind=None, sheet=None, voice=None):
        name = _clean(name, "name", 80, True)
        if kind is not None and kind not in ("pc", "npc"):
            raise StoryError("kind must be pc (the character you play) or npc")
        row = self.db.execute("SELECT * FROM characters WHERE name=?", (name,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO characters(name,kind,sheet,voice,created) VALUES(?,?,?,?,?)",
                            (name, kind or "npc", _clean(sheet, "sheet"), _clean(voice, "voice"), _now()))
        else:
            self.db.execute("UPDATE characters SET kind=?, sheet=?, voice=? WHERE id=?",
                            (kind or row["kind"], row["sheet"] if sheet is None else _clean(sheet, "sheet"),
                             row["voice"] if voice is None else _clean(voice, "voice"), row["id"]))
        self.db.commit()

    def characters(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM characters ORDER BY kind DESC, name")]

    def character(self, name):
        r = self.db.execute("SELECT * FROM characters WHERE name=?", (name.strip(),)).fetchone()
        return dict(r) if r else None

    # ---- episodes
    def current_episode(self):
        r = self.db.execute("SELECT * FROM episodes WHERE status='open' ORDER BY number DESC LIMIT 1").fetchone()
        return dict(r) if r else None

    def start_episode(self, title="", number=None):
        if self.current_episode():
            raise StoryError(f"episode {self.current_episode()['number']} is still open; end it first")
        if number is None:
            r = self.db.execute("SELECT MAX(number) m FROM episodes").fetchone()
            number = (r["m"] or 0) + 1
        self.db.execute("INSERT INTO episodes(number,title,created) VALUES(?,?,?)", (int(number), _clean(title, "title", 200), _now()))
        self.db.commit()
        return int(number)

    def end_episode(self, summary):
        ep = self.current_episode()
        if not ep:
            raise StoryError("no open episode")
        self.db.execute("UPDATE episodes SET summary=?, status='done' WHERE id=?", (_clean(summary, "summary", 8000, True), ep["id"]))
        self.db.commit()
        return ep["number"]

    # ---- quests
    def add_quest(self, title, description=""):
        ep = self.current_episode()
        self.db.execute("INSERT INTO quests(title,description,opened_ep,created) VALUES(?,?,?,?)",
                        (_clean(title, "title", 200, True), _clean(description, "description"), ep["number"] if ep else None, _now()))
        self.db.commit()

    def update_quest(self, title, status=None, description=None):
        r = self.db.execute("SELECT * FROM quests WHERE title=?", (title.strip(),)).fetchone()
        if not r:
            raise StoryError(f"no quest called {title!r}")
        if status is not None and status not in QUEST_STATUS:
            raise StoryError("status must be one of: " + ", ".join(QUEST_STATUS))
        ep = self.current_episode()
        closed = (ep["number"] if ep else r["closed_ep"]) if status in ("done", "failed") else (None if status in ("open", "dormant") else r["closed_ep"])
        self.db.execute("UPDATE quests SET status=?, description=?, closed_ep=? WHERE id=?",
                        (status or r["status"], r["description"] if description is None else _clean(description, "description"), closed, r["id"]))
        self.db.commit()

    def quests(self, status=None):
        q, a = "SELECT * FROM quests", ()
        if status:
            q, a = q + " WHERE status=?", (status,)
        return [dict(r) for r in self.db.execute(q + " ORDER BY id", a)]

    # ---- events
    def log(self, text, kind="event", quest="", known_by=""):
        ep = self.current_episode()
        if not ep:
            raise StoryError("no open episode; start one first")
        if kind not in KINDS:
            raise StoryError("kind must be one of: " + ", ".join(KINDS))
        quest = _clean(quest, "quest", 200)
        if quest and not self.db.execute("SELECT 1 FROM quests WHERE title=?", (quest,)).fetchone():
            raise StoryError(f"no quest called {quest!r}")
        self.db.execute("INSERT INTO events(episode,kind,text,quest,known_by,created) VALUES(?,?,?,?,?,?)",
                        (ep["number"], kind, _clean(text, "text", required=True), quest, _clean(known_by, "known_by", 300), _now()))
        self.db.commit()

    def search(self, query, limit=10):
        terms = re.findall(r"\w+", query)
        if not terms:
            return []
        q = " ".join(f'"{t}"' for t in terms)          # quoted: user text can never become FTS syntax
        rows = self.db.execute("SELECT e.* FROM events_fts f JOIN events e ON e.id=f.rowid WHERE events_fts MATCH ? ORDER BY rank LIMIT ?", (q, int(limit)))
        return [dict(r) for r in rows]

    @staticmethod
    def _knows(ev, who):
        """Metagame guard: a secret/relationship tagged known_by is only for those named (and always for the narrator, who=None)."""
        if who is None or not ev["known_by"]:
            return True
        return who.lower() in [n.strip().lower() for n in ev["known_by"].split(",")]

    # ---- the thing you paste into any AI
    def recap(self, as_character=None, episodes=3, events=25):
        out = []
        title = self.meta("title") or "Untitled series"
        out.append(f"# {title}: story so far")
        if self.meta("premise"):
            out.append(self.meta("premise"))
        if as_character:
            c = self.character(as_character)
            if not c:
                raise StoryError(f"no character called {as_character!r}")
            out.append(f"\n## You are {c['name']}\n{c['sheet']}".rstrip())
            if c["voice"]:
                out.append(f"How you speak: {c['voice']}")
            out.append("Stay in character. You only know what is written below as known to you; do not use knowledge your character could not have.")
        others = [c for c in self.characters() if not as_character or c["name"].lower() != as_character.lower()]
        if others:
            out.append("\n## Cast")
            out += [f"- {c['name']} ({c['kind']}): {c['sheet']}".rstrip(": ") for c in others]
        done = [dict(r) for r in self.db.execute("SELECT * FROM episodes WHERE status='done' ORDER BY number DESC LIMIT ?", (int(episodes),))][::-1]
        if done:
            out.append("\n## Previously")
            out += [f"- Episode {e['number']}{': ' + e['title'] if e['title'] else ''}: {e['summary']}" for e in done]
        openq = self.quests("open")
        if openq:
            out.append("\n## Open quests")
            out += [f"- {q['title']}" + (f": {q['description']}" if q["description"] else "") + (f" (since episode {q['opened_ep']})" if q["opened_ep"] else "") for q in openq]
        dormant = self.quests("dormant")
        if dormant:
            out.append("\n## Dormant quests (not forgotten)")
            out += [f"- {q['title']}" for q in dormant]
        evs = [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 500")]
        evs = [e for e in evs if self._knows(e, as_character)]
        promises = [e for e in evs if e["kind"] == "promise"]
        if promises:
            out.append("\n## Promises made and not forgotten")
            out += [f"- (ep {e['episode']}) {e['text']}" for e in reversed(promises)]
        facts = [e for e in evs if e["kind"] in ("fact", "secret", "relationship")]
        if facts:
            out.append("\n## What you know to be true" if as_character else "\n## Established facts")
            out += [f"- {e['text']}" for e in reversed(facts[:40])]
        recent = [e for e in evs if e["kind"] == "event"][:int(events)]
        if recent:
            out.append("\n## Recent events")
            out += [f"- (ep {e['episode']}) {e['text']}" for e in reversed(recent)]
        ep = self.current_episode()
        out.append(f"\n## Now\nEpisode {ep['number']}{': ' + ep['title'] if ep['title'] else ''} is in progress." if ep else "\n## Now\nBetween episodes.")
        return "\n".join(out).strip() + "\n"

    def episode_list(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM episodes ORDER BY number")]

    def draft_summary_prompt(self):
        """Everything logged in the open episode plus an instruction, to paste into an AI so it drafts the summary. Calls no AI itself."""
        ep = self.current_episode()
        if not ep:
            raise StoryError("no open episode")
        evs = [dict(r) for r in self.db.execute("SELECT * FROM events WHERE episode=? ORDER BY id", (ep["number"],))]
        if not evs:
            raise StoryError("nothing logged in this episode yet; log what happened first")
        lines = [f"- [{e['kind']}] {e['text']}" + (f" (known by: {e['known_by']})" if e["known_by"] else "") for e in evs]
        return ("Write the end-of-episode summary for episode %d%s of \"%s\". 3 to 6 sentences, past tense, plain words. Keep names, "
                "promises, open quests and anything a character will need to remember next time. Do not reveal secrets to characters who do not "
                "know them; if a secret matters, say only that it exists. Use only what is below; invent nothing.\n\nWhat was logged:\n%s\n"
                % (ep["number"], ": " + ep["title"] if ep["title"] else "", self.meta("title") or "this series", "\n".join(lines)))

    def export_markdown(self):
        return self.recap(None, episodes=10**6, events=10**6)
