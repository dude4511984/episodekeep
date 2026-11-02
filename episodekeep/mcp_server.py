"""Minimal MCP server (stdio, JSON-RPC 2.0) so an AI app can keep the story itself. Standard library only.
Text a tool returns is story data, not instructions; the AI app decides what to do with it."""
import json, sys
from .db import Story, StoryError, KINDS, QUEST_STATUS

S = lambda **p: {"type": "object", "properties": p, "additionalProperties": False}
STR = {"type": "string"}
TOOLS = {
    "recap": ("The story so far, ready to read. Pass 'as' to get it from one character's point of view (hides secrets they don't know).",
              S(**{"as": STR, "episodes": {"type": "integer"}})),
    "start_episode": ("Start a new episode.", dict(S(title=STR), required=[])),
    "end_episode": ("End the open episode with a summary of what happened.", dict(S(summary=STR), required=["summary"])),
    "log": ("Write down something that happened or became true. kind: " + ", ".join(KINDS) + ". For a secret, set known_by to a comma list.",
            dict(S(text=STR, kind={"type": "string", "enum": list(KINDS)}, quest=STR, known_by=STR), required=["text"])),
    "add_quest": ("Add a quest.", dict(S(title=STR, description=STR), required=["title"])),
    "update_quest": ("Change a quest's status (" + ", ".join(QUEST_STATUS) + ") or description.",
                     dict(S(title=STR, status={"type": "string", "enum": list(QUEST_STATUS)}, description=STR), required=["title"])),
    "character": ("Add or change a character. kind pc = the one the AI plays.",
                  dict(S(name=STR, kind={"type": "string", "enum": ["pc", "npc"]}, sheet=STR, voice=STR), required=["name"])),
    "draft_summary": ("Get the open episode's logged events with instructions for writing its end-of-episode summary. Then call end_episode with your summary.", S()),
    "search": ("Search what has been written down.", dict(S(query=STR), required=["query"])),
}


def call(st, name, a):
    if name == "recap": return st.recap(a.get("as"), int(a.get("episodes", 3)))
    if name == "start_episode": return f"episode {st.start_episode(a.get('title', ''))} started"
    if name == "end_episode": return f"episode {st.end_episode(a['summary'])} ended"
    if name == "log": st.log(a["text"], a.get("kind", "event"), a.get("quest", ""), a.get("known_by", "")); return "logged"
    if name == "add_quest": st.add_quest(a["title"], a.get("description", "")); return "quest added"
    if name == "update_quest": st.update_quest(a["title"], a.get("status"), a.get("description")); return "quest updated"
    if name == "character": st.upsert_character(a["name"], a.get("kind"), a.get("sheet"), a.get("voice")); return "saved"
    if name == "draft_summary": return st.draft_summary_prompt()
    if name == "search": return "\n".join(f"ep {e['episode']} [{e['kind']}] {e['text']}" for e in st.search(a["query"])) or "nothing found"
    raise StoryError("unknown tool " + name)


def handle(st, msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None                                   # notifications get no reply
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
               "serverInfo": {"name": "episodekeep", "version": "0.1.1"}}
    elif method == "tools/list":
        res = {"tools": [{"name": n, "description": d, "inputSchema": sch} for n, (d, sch) in TOOLS.items()]}
    elif method == "tools/call":
        try:
            text, err = call(st, params.get("name", ""), params.get("arguments") or {}), False
        except (StoryError, KeyError, ValueError, TypeError) as e:
            text, err = f"error: {e}", True
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def serve(path=None):
    st = Story(path)
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            out = handle(st, json.loads(line))
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
    return 0
