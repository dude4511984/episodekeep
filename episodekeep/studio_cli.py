"""studio command line: the creator's side of the Living Story Studio. Same story.db as episodekeep.

    python3 -m episodekeep.studio_cli [--db story.db] <command>

Structural commands (init, character, start, end, quest, quest-set, episodes, quests, characters) are handed to the
episodekeep CLI unchanged. The ungated episodekeep commands (log, search, recap, export, draft-summary) are NOT
available here: the studio versions below carry layer and permission. The plain `episodekeep` commands and `episodekeep mcp`
have no gate and can read everything in story.db, so use them only yourself, never hand them to an AI app. Standard library only; calls no AI."""
import argparse, json, sys
from .db import StoryError
from .studio_db import StudioStory, LAYERS, PERMISSIONS, SCOPES, ARTIFACT_KINDS, ARTIFACT_STATUS, MODES
from .db import KINDS

PASSTHROUGH = ("init", "character", "start", "end", "quest", "quest-set", "episodes", "quests", "characters")


def _text(a, what="text"):
    """Text from --text, --file, or stdin ('-'). Reading a file happens only because the creator named it."""
    if getattr(a, "file", None):
        with open(a.file, encoding="utf-8") as f:
            return f.read()
    t = getattr(a, "text", None)
    if t == "-":
        return sys.stdin.read()
    if t is None:
        raise StoryError(f"give the {what} with --text TEXT, --text - (stdin) or --file PATH")
    return t


def _entry_line(e):
    flag = " REVOKED" if e["revoked"] else ""
    return f"#{e['id']} [{e['permission']}{flag}] ({e['layer']}) {e['title']}" + (f"  <{e['source_label']}>" if e["source_label"] else "") + f"  sha256:{e['sha256'][:12]}"


def _draft_line(d):
    return f"#{d['id']} ep{d['episode']} {d['kind']} v{d['version']} [{d['status']}/{d['permission']}] ({d['layer']}, {d['mode']})" + (f" {d['title']}" if d["title"] else "")


def build_parser():
    p = argparse.ArgumentParser(prog="studio", description="Living Story Studio: one journal entry to one episode, with the creator approving every step.")
    p.add_argument("--db", help="story file (default: story.db, or $EPISODEKEEP_DB)")
    s = p.add_subparsers(dest="cmd", required=True, metavar="command")
    for n in PASSTHROUGH:
        s.add_parser(n, help="same as: episodekeep " + n, add_help=False)

    def src(a, req=True):
        a.add_argument("--text", help="the text, or - to read stdin"); a.add_argument("--file", help="read the text from this file")
    a = s.add_parser("import", help="import ONE creator-approved entry (private unless you say otherwise)"); a.add_argument("title"); src(a)
    a.add_argument("--layer", choices=LAYERS, default="real_life"); a.add_argument("--permission", choices=PERMISSIONS, default="private")
    a.add_argument("--label", default="", help="where it came from, e.g. My Journal")
    a = s.add_parser("entries", help="list imported entries"); a.add_argument("--scope", choices=SCOPES, default="creator")
    a = s.add_parser("entry", help="show one entry"); a.add_argument("id", type=int); a.add_argument("--scope", choices=SCOPES, default="creator")
    a = s.add_parser("permit", help="set an entry's permission (this is how you authorise it for the studio)"); a.add_argument("id", type=int); a.add_argument("permission", choices=PERMISSIONS)
    a = s.add_parser("revoke", help="withdraw an entry: everything linked to it disappears from studio and audience views"); a.add_argument("id", type=int)
    a = s.add_parser("rule", help="add or change a world rule"); a.add_argument("title"); a.add_argument("rule")
    a.add_argument("--layer", choices=LAYERS, default="live_action"); a.add_argument("--permission", choices=PERMISSIONS, default="studio_draft"); a.add_argument("--source", type=int)
    a = s.add_parser("rules", help="list world rules"); a.add_argument("--scope", choices=SCOPES, default="creator"); a.add_argument("--layer", choices=LAYERS)
    a = s.add_parser("tag", help="give a character a layer and permission"); a.add_argument("name")
    a.add_argument("--layer", choices=LAYERS, default="live_action"); a.add_argument("--permission", choices=PERMISSIONS, default="studio_draft"); a.add_argument("--source", type=int)
    a = s.add_parser("slog", help="write something down in the open episode, with layer and permission"); a.add_argument("text")
    a.add_argument("--kind", choices=KINDS, default="event"); a.add_argument("--quest", default=""); a.add_argument("--known-by", default="")
    a.add_argument("--layer", choices=LAYERS, default="live_action"); a.add_argument("--permission", choices=PERMISSIONS, default="studio_draft"); a.add_argument("--source", type=int)
    a = s.add_parser("recap", help="the consent-gated context block (default: studio view)"); a.add_argument("--scope", choices=SCOPES, default="studio")
    a.add_argument("--layer", choices=LAYERS); a.add_argument("--as", dest="who"); a.add_argument("--episodes", type=int, default=3)
    a = s.add_parser("prompt", help="print the prompt for a companion mode (calls no AI)"); a.add_argument("mode", choices=MODES)
    a.add_argument("--episode", type=int); a.add_argument("--source", type=int, help="entry id; must be authorised, never private or revoked")
    a.add_argument("--focus", default=""); a.add_argument("--layer", choices=LAYERS, default="live_action")
    a = s.add_parser("draft", help="save what the AI (or you) wrote as a draft"); a.add_argument("kind", choices=ARTIFACT_KINDS); src(a)
    a.add_argument("--episode", type=int); a.add_argument("--mode", choices=MODES, default="writer"); a.add_argument("--layer", choices=LAYERS, default="live_action")
    a.add_argument("--source", type=int); a.add_argument("--title", default="")
    a = s.add_parser("revise", help="save a new version of a draft"); a.add_argument("id", type=int); src(a)
    a = s.add_parser("approve", help="approve a draft (only you can)"); a.add_argument("id", type=int)
    a.add_argument("--permission", choices=("approved_canon", "audience_safe"), default="approved_canon")
    a = s.add_parser("reject", help="reject a draft"); a.add_argument("id", type=int); a.add_argument("--note", default="")
    a = s.add_parser("drafts", help="list drafts"); a.add_argument("--episode", type=int); a.add_argument("--status", choices=ARTIFACT_STATUS); a.add_argument("--scope", choices=SCOPES, default="creator")
    a = s.add_parser("draft-show", help="print one draft's text"); a.add_argument("id", type=int)
    a = s.add_parser("package", help="export the approved package"); a.add_argument("--episode", type=int)
    a.add_argument("--audience", action="store_true", help="audience_safe only"); a.add_argument("--json", action="store_true", help="JSON instead of Markdown")
    s.add_parser("mcp", help="run the Studio MCP server over stdio")
    return p


def run(st, a):
    c = a.cmd
    if c == "import":
        i = st.import_entry(a.title, _text(a), a.layer, a.permission, a.label); print(f"entry {i} imported ({a.permission}, {a.layer})")
    elif c == "entries":
        for e in st.list_entries(a.scope): print(_entry_line(e))
    elif c == "entry":
        e = st.get_entry(a.id, a.scope)
        if e is None: raise StoryError(f"no entry #{a.id} visible in {a.scope} scope")
        print(_entry_line(e)); print(e["text"])
    elif c == "permit":
        st.set_entry_permission(a.id, a.permission); print(f"entry {a.id} is now {a.permission}")
    elif c == "revoke":
        st.revoke_entry(a.id); print(f"entry {a.id} revoked")
    elif c == "rule":
        print("rule", st.add_rule(a.title, a.rule, a.layer, a.permission, a.source), "saved")
    elif c == "rules":
        for r in st.list_rules(a.scope, a.layer): print(f"#{r['id']} [{r['permission']}] ({r['layer']}) {r['title']}: {r['rule']}")
    elif c == "tag":
        st.tag_character(a.name, a.layer, a.permission, a.source); print(f"{a.name} tagged {a.layer}/{a.permission}")
    elif c == "slog":
        print("event", st.log_studio(a.text, a.kind, a.quest, a.known_by, a.layer, a.permission, a.source), "logged")
    elif c == "recap":
        sys.stdout.write(st.studio_recap(a.scope, a.layer, a.who, a.episodes))
    elif c == "prompt":
        from .studio_prompts import studio_prompt
        sys.stdout.write(studio_prompt(st, a.mode, a.episode, a.source, a.focus, a.layer))
    elif c == "draft":
        print("draft", st.save_draft(a.kind, _text(a, "content"), episode=a.episode, mode=a.mode, layer=a.layer, source_id=a.source, title=a.title), "saved")
    elif c == "revise":
        print("draft", st.revise_draft(a.id, _text(a, "content")), "saved (new version)")
    elif c == "approve":
        d = st.approve_draft(a.id, a.permission); print(f"draft {d['id']} approved as {d['permission']}")
    elif c == "reject":
        d = st.reject_draft(a.id, a.note); print(f"draft {d['id']} rejected")
    elif c == "drafts":
        for d in st.list_drafts(a.episode, a.status, a.scope): print(_draft_line(d))
    elif c == "draft-show":
        rows = [d for d in st.list_drafts() if d["id"] == a.id]
        if not rows: raise StoryError(f"no draft #{a.id}")
        print(_draft_line(rows[0])); print(rows[0]["content"])
    elif c == "package":
        if a.json: print(json.dumps(st.export_package(a.episode, a.audience), indent=2, ensure_ascii=False))
        else: sys.stdout.write(st.export_package_markdown(a.episode, a.audience))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # hand structural episodekeep commands to the original CLI, keeping --db
    db, rest, i = None, [], 0
    while i < len(argv):
        if argv[i] == "--db" and i + 1 < len(argv): db = argv[i + 1]; i += 2
        elif argv[i].startswith("--db="): db = argv[i][5:]; i += 1
        else: rest.append(argv[i]); i += 1
    if rest and rest[0] in PASSTHROUGH:
        from .cli import main as base
        return base((["--db", db] if db else []) + rest)
    a = build_parser().parse_args(argv)
    if a.cmd == "mcp":
        from .studio_mcp import serve
        return serve(a.db)
    st = StudioStory(a.db)
    try:
        run(st, a)
    except StoryError as e:
        print("studio:", e, file=sys.stderr); return 1
    except (OSError, UnicodeDecodeError) as e:
        print("studio:", e, file=sys.stderr); return 1
    finally:
        st.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
