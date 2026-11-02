"""episodekeep command line. The story lives in one file (story.db in the current folder, or $EPISODEKEEP_DB or --db)."""
import argparse, sys
from . import __version__
from .db import Story, StoryError, KINDS, QUEST_STATUS


def main(argv=None):
    p = argparse.ArgumentParser(prog="episodekeep", description="Keep a multi-episode story straight for the AI that plays your character.")
    p.add_argument("--version", action="version", version="episodekeep " + __version__)
    p.add_argument("--db", help="story file (default: story.db, or $EPISODEKEEP_DB)")
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("init", help="start a new series"); a.add_argument("title"); a.add_argument("--premise", default="")
    a = s.add_parser("character", help="add or change a character"); a.add_argument("name"); a.add_argument("--pc", action="store_true", help="the one you play")
    a.add_argument("--sheet"); a.add_argument("--voice")
    a = s.add_parser("start", help="start an episode"); a.add_argument("title", nargs="?", default="")
    a = s.add_parser("end", help="end the open episode with a summary"); a.add_argument("summary")
    a = s.add_parser("quest", help="add a quest"); a.add_argument("title"); a.add_argument("--description", default="")
    a = s.add_parser("quest-set", help="change a quest"); a.add_argument("title"); a.add_argument("--status", choices=QUEST_STATUS); a.add_argument("--description")
    a = s.add_parser("log", help="write something down"); a.add_argument("text"); a.add_argument("--kind", choices=KINDS, default="event")
    a.add_argument("--quest", default=""); a.add_argument("--known-by", default="", help="comma list; only they know (secrets)")
    a = s.add_parser("search"); a.add_argument("query")
    a = s.add_parser("recap", help="print the context block to paste into an AI"); a.add_argument("--as", dest="who"); a.add_argument("--episodes", type=int, default=3)
    s.add_parser("episodes", help="list episodes"); s.add_parser("quests", help="list quests"); s.add_parser("characters", help="list the cast")
    s.add_parser("draft-summary", help="print a prompt that asks an AI to draft the end-of-episode summary (calls no AI itself)")
    s.add_parser("export", help="the whole story as markdown")
    s.add_parser("mcp", help="run as an MCP server over stdio (for Claude Desktop and other AI apps)")
    a = p.parse_args(argv)
    if a.cmd == "mcp":
        from .mcp_server import serve
        return serve(a.db)
    st = Story(a.db)
    try:
        if a.cmd == "init":
            st.set_meta("title", a.title); st.set_meta("premise", a.premise); print("started:", a.title)
        elif a.cmd == "character":
            st.upsert_character(a.name, "pc" if a.pc else None, a.sheet, a.voice); print("saved", a.name)
        elif a.cmd == "start":
            print("episode", st.start_episode(a.title), "started")
        elif a.cmd == "end":
            print("episode", st.end_episode(a.summary), "ended")
        elif a.cmd == "quest":
            st.add_quest(a.title, a.description); print("quest added")
        elif a.cmd == "quest-set":
            st.update_quest(a.title, a.status, a.description); print("quest updated")
        elif a.cmd == "log":
            st.log(a.text, a.kind, a.quest, a.known_by); print("logged")
        elif a.cmd == "search":
            for e in st.search(a.query): print(f"ep {e['episode']} [{e['kind']}] {e['text']}")
        elif a.cmd == "recap":
            sys.stdout.write(st.recap(a.who, a.episodes))
        elif a.cmd == "episodes":
            for e in st.episode_list(): print(f"{e['number']}. {e['title'] or '(untitled)'} [{e['status']}]" + (f": {e['summary']}" if e["summary"] else ""))
        elif a.cmd == "quests":
            for q in st.quests(): print(f"[{q['status']}] {q['title']}" + (f": {q['description']}" if q["description"] else ""))
        elif a.cmd == "characters":
            for c in st.characters(): print(f"{c['name']} ({c['kind']}): {c['sheet']}")
        elif a.cmd == "draft-summary":
            sys.stdout.write(st.draft_summary_prompt())
        elif a.cmd == "export":
            sys.stdout.write(st.export_markdown())
    except StoryError as e:
        print("episodekeep:", e, file=sys.stderr); return 1
    finally:
        st.close()
    return 0
