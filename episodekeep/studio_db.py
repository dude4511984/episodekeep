"""Living Story Studio data & consent layer built on top of episodekeep.db.Story.

Standard library only, single SQLite file (story.db). Adds manual approved
entry import with provenance, story layers (real_life / live_action / fantasy),
permission labels (private / studio_draft / approved_canon / audience_safe),
editable world rules, draft/approval workflow, and consent-gated recap/export.
"""
from __future__ import annotations

import hashlib
from .db import KINDS, MAX_TEXT, Story, StoryError, _clean, _now

LAYERS = ("real_life", "live_action", "fantasy")
PERMISSIONS = ("private", "studio_draft", "approved_canon", "audience_safe")
SCOPES = ("creator", "studio", "audience")
ARTIFACT_KINDS = ("themes", "outline", "script", "shotlist", "experience_brief")
ARTIFACT_STATUS = ("draft", "approved", "rejected")
MODES = ("storyteller", "writer", "worldbuilder", "producer")
MAX_ARTIFACT_TEXT = 32000

STUDIO_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  text TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  layer TEXT NOT NULL DEFAULT 'real_life',
  permission TEXT NOT NULL DEFAULT 'private',
  source_label TEXT NOT NULL DEFAULT '',
  revoked INTEGER NOT NULL DEFAULT 0,
  created TEXT NOT NULL,
  revoked_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS world_rules(
  id INTEGER PRIMARY KEY,
  title TEXT UNIQUE NOT NULL COLLATE NOCASE,
  rule TEXT NOT NULL,
  layer TEXT NOT NULL DEFAULT 'live_action',
  permission TEXT NOT NULL DEFAULT 'studio_draft',
  source_id INTEGER,
  created TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS character_meta(
  name TEXT PRIMARY KEY COLLATE NOCASE,
  layer TEXT NOT NULL DEFAULT 'live_action',
  permission TEXT NOT NULL DEFAULT 'studio_draft',
  source_id INTEGER,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_meta(
  event_id INTEGER PRIMARY KEY,
  layer TEXT NOT NULL DEFAULT 'live_action',
  permission TEXT NOT NULL DEFAULT 'studio_draft',
  source_id INTEGER
);
CREATE TABLE IF NOT EXISTS artifacts(
  id INTEGER PRIMARY KEY,
  episode INTEGER NOT NULL,
  kind TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  mode TEXT NOT NULL DEFAULT 'writer',
  layer TEXT NOT NULL DEFAULT 'live_action',
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  permission TEXT NOT NULL DEFAULT 'studio_draft',
  source_id INTEGER,
  version INTEGER NOT NULL DEFAULT 1,
  parent_id INTEGER,
  review_note TEXT NOT NULL DEFAULT '',
  created TEXT NOT NULL,
  approved_at TEXT NOT NULL DEFAULT ''
);
"""


def _check_choice(val: str, valid: tuple[str, ...], label: str) -> str:
    if val not in valid:
        raise StoryError(f"{label} must be one of: " + ", ".join(valid))
    return val


class StudioStory(Story):
    """Consent-gated story studio extending episodekeep.db.Story.

    Security boundary: private journal entries live only in `sources` and are
    never written into base `events` or `events_fts`. However, base `Story`
    methods (`recap`, `search`, `export_markdown`) and base `episodekeep mcp`
    do not read `studio_db` permission tables, so a studio `story.db` must ONLY
    be exposed to AI apps via `episodekeep.studio_mcp` (never `episodekeep mcp`),
    and real-life private details should stay in `sources` rather than base
    `characters` rows.
    """

    def __init__(self, path=None):
        super().__init__(path)
        self.db.executescript(STUDIO_SCHEMA)

    # ------------------------------------------------------------------ helpers
    def _validate_source(self, source_id: int | None, *, require_active: bool = False) -> dict | None:
        if source_id is None:
            return None
        row = self.db.execute("SELECT * FROM sources WHERE id=?", (int(source_id),)).fetchone()
        if not row:
            raise StoryError(f"no source entry #{source_id}")
        d = dict(row)
        if require_active and d["revoked"]:
            raise StoryError(f"source entry #{source_id} has been revoked")
        return d

    def _source_allows(self, source_id: int | None, scope: str) -> bool:
        if source_id is None or scope == "creator":
            return True
        src = self.db.execute("SELECT permission, revoked FROM sources WHERE id=?", (int(source_id),)).fetchone()
        if not src:
            return False
        if src["revoked"]:
            return False
        if scope == "studio" and src["permission"] == "private":
            return False
        return True

    def _visible(self, permission: str, layer: str, scope: str, source_id: int | None = None) -> bool:
        _check_choice(scope, SCOPES, "scope")
        if scope == "creator":
            return True
        if not self._source_allows(source_id, scope):
            return False
        if scope == "studio":
            return permission in ("studio_draft", "approved_canon", "audience_safe")
        # scope == "audience"
        return permission == "audience_safe" and layer != "real_life"

    # ------------------------------------------------------------------ sources
    def import_entry(
        self,
        title: str,
        text: str,
        layer: str = "real_life",
        permission: str = "private",
        source_label: str = "",
    ) -> int:
        title = _clean(title, "title", 200, required=True)
        text = _clean(text, "text", MAX_ARTIFACT_TEXT, required=True)
        _check_choice(layer, LAYERS, "layer")
        _check_choice(permission, PERMISSIONS, "permission")
        label = _clean(source_label, "source_label", 200)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        cur = self.db.execute(
            "INSERT INTO sources(title,text,sha256,layer,permission,source_label,revoked,created) "
            "VALUES(?,?,?,?,?,?,0,?)",
            (title, text, digest, layer, permission, label, _now()),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def set_entry_permission(self, source_id: int, permission: str) -> None:
        _check_choice(permission, PERMISSIONS, "permission")
        src = self._validate_source(source_id)
        if src["revoked"] and permission != "private":
            raise StoryError(f"source entry #{source_id} is revoked")
        self.db.execute("UPDATE sources SET permission=? WHERE id=?", (permission, int(source_id)))
        self.db.commit()

    def revoke_entry(self, source_id: int) -> None:
        self._validate_source(source_id)
        self.db.execute(
            "UPDATE sources SET revoked=1, permission='private', revoked_at=? WHERE id=?",
            (_now(), int(source_id)),
        )
        self.db.commit()

    def list_entries(self, scope: str = "creator") -> list[dict]:
        _check_choice(scope, SCOPES, "scope")
        rows = [dict(r) for r in self.db.execute("SELECT * FROM sources ORDER BY id")]
        if scope == "creator":
            return rows
        return [
            r for r in rows
            if not r["revoked"] and self._visible(r["permission"], r["layer"], scope, None)
        ]

    def get_entry(self, source_id: int, scope: str = "creator") -> dict | None:
        _check_choice(scope, SCOPES, "scope")
        row = self.db.execute("SELECT * FROM sources WHERE id=?", (int(source_id),)).fetchone()
        if not row:
            return None
        d = dict(row)
        if scope != "creator":
            if d["revoked"] or not self._visible(d["permission"], d["layer"], scope, None):
                return None
        return d

    # ------------------------------------------------------------------ world rules & canon metadata
    def add_rule(
        self,
        title: str,
        rule: str,
        layer: str = "live_action",
        permission: str = "studio_draft",
        source_id: int | None = None,
    ) -> int:
        title = _clean(title, "title", 200, required=True)
        rule = _clean(rule, "rule", MAX_TEXT, required=True)
        _check_choice(layer, LAYERS, "layer")
        _check_choice(permission, PERMISSIONS, "permission")
        self._validate_source(source_id, require_active=(permission != "private"))
        now = _now()
        row = self.db.execute("SELECT id FROM world_rules WHERE title=?", (title,)).fetchone()
        if row is None:
            cur = self.db.execute(
                "INSERT INTO world_rules(title,rule,layer,permission,source_id,created,updated_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (title, rule, layer, permission, source_id, now, now),
            )
            rid = int(cur.lastrowid)
        else:
            rid = int(row["id"])
            self.db.execute(
                "UPDATE world_rules SET rule=?, layer=?, permission=?, source_id=?, updated_at=? WHERE id=?",
                (rule, layer, permission, source_id, now, rid),
            )
        self.db.commit()
        return rid

    def list_rules(self, scope: str = "creator", layer: str | None = None) -> list[dict]:
        _check_choice(scope, SCOPES, "scope")
        if layer is not None:
            _check_choice(layer, LAYERS, "layer")
        rows = [dict(r) for r in self.db.execute("SELECT * FROM world_rules ORDER BY id")]
        out = []
        for r in rows:
            if layer is not None and r["layer"] != layer:
                continue
            if self._visible(r["permission"], r["layer"], scope, r["source_id"]):
                out.append(r)
        return out

    def tag_character(
        self,
        name: str,
        layer: str = "live_action",
        permission: str = "studio_draft",
        source_id: int | None = None,
    ) -> None:
        if not self.character(name):
            raise StoryError(f"no character called {name!r}")
        _check_choice(layer, LAYERS, "layer")
        _check_choice(permission, PERMISSIONS, "permission")
        self._validate_source(source_id, require_active=(permission != "private"))
        self.db.execute(
            "INSERT INTO character_meta(name,layer,permission,source_id,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET layer=excluded.layer, permission=excluded.permission, "
            "source_id=excluded.source_id, updated_at=excluded.updated_at",
            (name.strip(), layer, permission, source_id, _now()),
        )
        self.db.commit()

    def _char_meta_map(self) -> dict[str, dict]:
        return {
            r["name"].lower(): dict(r)
            for r in self.db.execute("SELECT * FROM character_meta")
        }

    def log_studio(
        self,
        text: str,
        kind: str = "event",
        quest: str = "",
        known_by: str = "",
        layer: str = "live_action",
        permission: str = "studio_draft",
        source_id: int | None = None,
    ) -> int:
        _check_choice(layer, LAYERS, "layer")
        _check_choice(permission, PERMISSIONS, "permission")
        if permission == "private":
            raise StoryError("private notes belong in import_entry (sources), not the shared episode event log")
        _check_choice(kind, KINDS, "kind")
        self._validate_source(source_id, require_active=True)
        super().log(text, kind=kind, quest=quest, known_by=known_by)
        row = self.db.execute("SELECT MAX(id) AS mid FROM events").fetchone()
        eid = int(row["mid"])
        self.db.execute(
            "INSERT INTO event_meta(event_id,layer,permission,source_id) VALUES(?,?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET layer=excluded.layer, permission=excluded.permission, source_id=excluded.source_id",
            (eid, layer, permission, source_id),
        )
        self.db.commit()
        return eid

    def _event_meta_map(self) -> dict[int, dict]:
        return {
            int(r["event_id"]): dict(r)
            for r in self.db.execute("SELECT * FROM event_meta")
        }

    # ------------------------------------------------------------------ consent-gated recap
    def studio_recap(
        self,
        scope: str = "studio",
        layer: str | None = None,
        as_character: str | None = None,
        episodes: int = 3,
        events: int = 25,
        entries: bool = True,
    ) -> str:
        _check_choice(scope, SCOPES, "scope")
        if layer is not None:
            _check_choice(layer, LAYERS, "layer")

        out = []
        title = self.meta("title") or "Untitled series"
        header = f"# {title} ({scope} view" + (f", layer={layer}" if layer else "") + ")"
        out.append(header)
        if scope != "audience" and self.meta("premise"):
            out.append(self.meta("premise"))

        cmeta = self._char_meta_map()
        if as_character:
            c = self.character(as_character)
            if not c:
                raise StoryError(f"no character called {as_character!r}")
            cm = cmeta.get(c["name"].lower(), {"layer": "real_life", "permission": "private", "source_id": None})
            if not self._visible(cm["permission"], cm["layer"], scope, cm["source_id"]):
                raise StoryError(f"character {as_character!r} is not visible in {scope!r} scope")
            out.append(f"\n## You are {c['name']} [{cm['layer']}]\n{c['sheet']}".rstrip())
            if c["voice"]:
                out.append(f"How you speak: {c['voice']}")

        others = []
        for c in self.characters():
            if as_character and c["name"].lower() == as_character.lower():
                continue
            cm = cmeta.get(c["name"].lower(), {"layer": "real_life", "permission": "private", "source_id": None})
            if layer is not None and cm["layer"] != layer:
                continue
            if self._visible(cm["permission"], cm["layer"], scope, cm["source_id"]):
                others.append((c, cm))
        if others:
            out.append("\n## Cast")
            for c, cm in others:
                out.append(f"- {c['name']} ({c['kind']}, {cm['layer']}, {cm['permission']}): {c['sheet']}".rstrip(": "))

        rules = self.list_rules(scope=scope, layer=layer)
        if rules:
            out.append("\n## World rules")
            for r in rules:
                prov = f" [source #{r['source_id']}]" if r["source_id"] else ""
                out.append(f"- {r['title']} ({r['layer']}, {r['permission']}{prov}): {r['rule']}")

        if scope != "audience":
            done = [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM episodes WHERE status='done' ORDER BY number DESC LIMIT ?",
                    (int(episodes),),
                )
            ][::-1]
            if done:
                out.append("\n## Previously")
                out.extend(
                    f"- Episode {e['number']}{': ' + e['title'] if e['title'] else ''}: {e['summary']}"
                    for e in done
                )

            openq = self.quests("open")
            if openq:
                out.append("\n## Open quests")
                out.extend(
                    f"- {q['title']}" + (f": {q['description']}" if q["description"] else "")
                    for q in openq
                )

        if entries:
            entry_rows = self.list_entries(scope=scope)
            if layer is not None:
                entry_rows = [e for e in entry_rows if e["layer"] == layer]
            if entry_rows:
                out.append("\n## Approved source entries")
                for e in entry_rows:
                    rev = " [REVOKED]" if e["revoked"] else ""
                    out.append(f"- Source #{e['id']} ({e['layer']}, {e['permission']}{rev}) {e['title']}: {e['text']}")

        emeta = self._event_meta_map()
        raw_evs = [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 500")]
        vis_evs = []
        for e in raw_evs:
            if not self._knows(e, as_character):
                continue
            em = emeta.get(int(e["id"]), {"layer": "real_life", "permission": "private", "source_id": None})
            if layer is not None and em["layer"] != layer:
                continue
            if self._visible(em["permission"], em["layer"], scope, em["source_id"]):
                vis_evs.append((e, em))

        promises = [(e, em) for e, em in vis_evs if e["kind"] == "promise"]
        if promises:
            out.append("\n## Promises")
            out.extend(f"- (ep {e['episode']}) {e['text']}" for e, _ in reversed(promises))

        facts = [(e, em) for e, em in vis_evs if e["kind"] in ("fact", "secret", "relationship")]
        if facts:
            out.append("\n## Established canon")
            out.extend(f"- [{em['layer']}/{em['permission']}] {e['text']}" for e, em in reversed(facts[:40]))

        recent = [(e, em) for e, em in vis_evs if e["kind"] == "event"][: int(events)]
        if recent:
            out.append("\n## Recent beats")
            out.extend(f"- (ep {e['episode']}, {em['layer']}/{em['permission']}) {e['text']}" for e, em in reversed(recent))

        ep = self.current_episode()
        out.append(
            f"\n## Now\nEpisode {ep['number']}{': ' + ep['title'] if ep['title'] else ''} is in progress."
            if ep
            else "\n## Now\nBetween episodes."
        )
        return "\n".join(out).strip() + "\n"

    # ------------------------------------------------------------------ drafts & approval
    def save_draft(
        self,
        kind: str,
        content: str,
        *,
        episode: int | None = None,
        mode: str = "writer",
        layer: str = "live_action",
        source_id: int | None = None,
        title: str = "",
    ) -> int:
        _check_choice(kind, ARTIFACT_KINDS, "kind")
        _check_choice(mode, MODES, "mode")
        _check_choice(layer, LAYERS, "layer")
        content = _clean(content, "content", MAX_ARTIFACT_TEXT, required=True)
        title = _clean(title, "title", 200)
        self._validate_source(source_id, require_active=True)
        if episode is None:
            ep = self.current_episode()
            if not ep:
                raise StoryError("no open episode; start one or pass episode number")
            episode = ep["number"]
        else:
            if not self.db.execute("SELECT 1 FROM episodes WHERE number=?", (int(episode),)).fetchone():
                raise StoryError(f"no episode #{episode}")
        cur = self.db.execute(
            "INSERT INTO artifacts(episode,kind,title,mode,layer,content,status,permission,source_id,version,created) "
            "VALUES(?,?,?,?,?,?,'draft','studio_draft',?,1,?)",
            (int(episode), kind, title, mode, layer, content, source_id, _now()),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def revise_draft(self, draft_id: int, content: str) -> int:
        old = self.db.execute("SELECT * FROM artifacts WHERE id=?", (int(draft_id),)).fetchone()
        if not old:
            raise StoryError(f"no draft #{draft_id}")
        content = _clean(content, "content", MAX_ARTIFACT_TEXT, required=True)
        self._validate_source(old["source_id"], require_active=True)
        cur = self.db.execute(
            "INSERT INTO artifacts(episode,kind,title,mode,layer,content,status,permission,source_id,version,parent_id,created) "
            "VALUES(?,?,?,?,?,?,'draft','studio_draft',?,?,?,?)",
            (
                old["episode"],
                old["kind"],
                old["title"],
                old["mode"],
                old["layer"],
                content,
                old["source_id"],
                int(old["version"]) + 1,
                int(old["id"]),
                _now(),
            ),
        )
        self.db.commit()
        return int(cur.lastrowid)

    def approve_draft(self, draft_id: int, permission: str = "approved_canon") -> dict:
        if permission not in ("approved_canon", "audience_safe"):
            raise StoryError("approval permission must be approved_canon or audience_safe")
        row = self.db.execute("SELECT * FROM artifacts WHERE id=?", (int(draft_id),)).fetchone()
        if not row:
            raise StoryError(f"no draft #{draft_id}")
        if row["status"] == "rejected":
            raise StoryError(f"draft #{draft_id} was rejected; create a new revision before approving")
        if permission == "audience_safe" and row["layer"] == "real_life":
            raise StoryError("real_life artifacts cannot be marked audience_safe")
        self._validate_source(row["source_id"], require_active=True)
        if row["source_id"] is not None:
            src = self._validate_source(row["source_id"])
            if src["permission"] == "private":
                raise StoryError(f"cannot approve draft backed by private source #{row['source_id']}")
        self.db.execute(
            "UPDATE artifacts SET status='approved', permission=?, approved_at=? WHERE id=?",
            (permission, _now(), int(draft_id)),
        )
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM artifacts WHERE id=?", (int(draft_id),)).fetchone())

    def reject_draft(self, draft_id: int, note: str = "") -> dict:
        row = self.db.execute("SELECT * FROM artifacts WHERE id=?", (int(draft_id),)).fetchone()
        if not row:
            raise StoryError(f"no draft #{draft_id}")
        self.db.execute(
            "UPDATE artifacts SET status='rejected', permission='private', review_note=? WHERE id=?",
            (_clean(note, "note", MAX_TEXT), int(draft_id)),
        )
        self.db.commit()
        return dict(self.db.execute("SELECT * FROM artifacts WHERE id=?", (int(draft_id),)).fetchone())

    def list_drafts(
        self,
        episode: int | None = None,
        status: str | None = None,
        scope: str = "creator",
    ) -> list[dict]:
        _check_choice(scope, SCOPES, "scope")
        if status is not None:
            _check_choice(status, ARTIFACT_STATUS, "status")
        q, args = "SELECT * FROM artifacts WHERE 1=1", []
        if episode is not None:
            q += " AND episode=?"
            args.append(int(episode))
        if status is not None:
            q += " AND status=?"
            args.append(status)
        rows = [dict(r) for r in self.db.execute(q + " ORDER BY id", tuple(args))]
        return [
            r for r in rows
            if self._visible(r["permission"], r["layer"], scope, r["source_id"])
        ]

    # ------------------------------------------------------------------ export approved package
    def export_package(self, episode: int | None = None, audience_only: bool = False) -> dict:
        scope = "audience" if audience_only else "studio"
        allowed_perm = ("audience_safe",) if audience_only else ("approved_canon", "audience_safe")

        if episode is None:
            eps = self.episode_list()
            if not eps:
                raise StoryError("no episodes to export")
            ep = eps[-1]
            episode = ep["number"]
        else:
            row = self.db.execute("SELECT * FROM episodes WHERE number=?", (int(episode),)).fetchone()
            if not row:
                raise StoryError(f"no episode #{episode}")
            ep = dict(row)

        cmeta = self._char_meta_map()
        chars = []
        for c in self.characters():
            cm = cmeta.get(c["name"].lower(), {"layer": "real_life", "permission": "private", "source_id": None})
            if cm["permission"] in allowed_perm and self._visible(cm["permission"], cm["layer"], scope, cm["source_id"]):
                chars.append({**c, "layer": cm["layer"], "permission": cm["permission"], "source_id": cm["source_id"]})

        rules = [
            r for r in self.list_rules(scope=scope)
            if r["permission"] in allowed_perm
        ]

        emeta = self._event_meta_map()
        raw_evs = [dict(r) for r in self.db.execute("SELECT * FROM events WHERE episode=? ORDER BY id", (int(episode),))]
        events = []
        for e in raw_evs:
            em = emeta.get(int(e["id"]), {"layer": "real_life", "permission": "private", "source_id": None})
            if em["permission"] in allowed_perm and self._visible(em["permission"], em["layer"], scope, em["source_id"]):
                events.append({**e, "layer": em["layer"], "permission": em["permission"], "source_id": em["source_id"]})

        approved_raw = [
            a for a in self.list_drafts(episode=int(episode), status="approved", scope=scope)
            if a["permission"] in allowed_perm
        ]
        superseded_ids = {a["parent_id"] for a in approved_raw if a.get("parent_id") is not None}
        artifacts = [a for a in approved_raw if a["id"] not in superseded_ids]

        ep_out = {**ep, "summary": ""} if audience_only else ep
        series_out = {"title": self.meta("title"), "premise": "" if audience_only else self.meta("premise")}

        return {
            "series": series_out,
            "episode": ep_out,
            "audience_only": audience_only,
            "characters": chars,
            "world_rules": rules,
            "events": events,
            "artifacts": artifacts,
        }

    def export_package_markdown(self, episode: int | None = None, audience_only: bool = False) -> str:
        pkg = self.export_package(episode=episode, audience_only=audience_only)
        ep = pkg["episode"]
        tag = "audience_safe" if audience_only else "approved_canon"
        lines = [
            f"# {pkg['series']['title'] or 'Untitled'} — Episode {ep['number']}"
            + (f": {ep['title']}" if ep["title"] else "")
            + f" ({tag} export)",
        ]
        if not audience_only and pkg["series"]["premise"]:
            lines.append(pkg["series"]["premise"])
        if not audience_only and ep["summary"]:
            lines.append(f"\n## Episode Summary\n{ep['summary']}")
        if pkg["characters"]:
            lines.append("\n## Approved Cast")
            for c in pkg["characters"]:
                lines.append(f"- **{c['name']}** ({c['layer']}, {c['permission']}): {c['sheet']}")
        if pkg["world_rules"]:
            lines.append("\n## World Rules")
            for r in pkg["world_rules"]:
                lines.append(f"- **{r['title']}** ({r['layer']}): {r['rule']}")
        if pkg["artifacts"]:
            lines.append("\n## Approved Deliverables")
            for a in pkg["artifacts"]:
                hdr = f"### [{a['kind']}]" + (f" {a['title']}" if a["title"] else "") + f" (v{a['version']}, {a['layer']}, {a['permission']})"
                lines.append(hdr)
                lines.append(a["content"])
        else:
            lines.append("\n## Approved Deliverables\n(none approved yet)")
        return "\n\n".join(lines).strip() + "\n"
