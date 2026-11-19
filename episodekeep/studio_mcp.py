"""Studio MCP server (stdio, JSON-RPC 2.0): lets an AI app act as the Living Story Studio companion. Standard library only.

The creator keeps the control plane. This server deliberately offers NO tool to import an entry, change or revoke an entry's
permission, approve or reject a draft, or export a package; those are `studio` CLI commands. Every read is studio scope
(never private, never revoked), and anything the AI writes is capped at 'studio_draft'. It cannot tag characters or
overwrite an existing rule, since either could release something the creator marked private. Text a tool returns is story data,
not instructions. episodekeep.mcp_server.TOOLS is left untouched.

Connect ONLY this server to an AI app. `episodekeep mcp` and the plain episodekeep commands have no consent gate: pointed at the
same story.db they would read characters and events the studio views hide."""
import json, sys
from .db import KINDS, StoryError
from . import mcp_server
from .mcp_server import S, STR
from .studio_db import StudioStory, LAYERS, MODES, ARTIFACT_KINDS, ARTIFACT_STATUS
from .studio_prompts import studio_prompt

INT = {"type": "integer"}
LAYER = {"type": "string", "enum": list(LAYERS)}
BASE_SAFE = ("start_episode", "end_episode", "add_quest", "update_quest", "character")   # structural; no ungated reads
READ_SCOPE = "studio"          # fixed: no tool takes a scope, so an AI cannot ask for creator or audience views

TOOLS = {n: mcp_server.TOOLS[n] for n in BASE_SAFE}
TOOLS.update({
    "studio_recap": ("The story so far, studio view: only material the creator has released to the studio. Optional layer filter.",
                     S(layer=LAYER, episodes=INT, **{"as": STR})),
    "studio_prompt": ("Get the working prompt for a companion mode (" + ", ".join(MODES) + "), built from the studio recap and, if given, ONE "
                      "creator-authorised entry. Fails if the entry is private or revoked; ask the creator to authorise it.",
                      dict(S(mode={"type": "string", "enum": list(MODES)}, episode=INT, source_id=INT, focus=STR, layer=LAYER), required=["mode"])),
    "list_entries": ("List source entries the creator has released to the studio (not private, not revoked).", S()),
    "get_entry": ("Read one released source entry.", dict(S(source_id=INT), required=["source_id"])),
    "list_rules": ("List world rules visible to the studio.", S(layer=LAYER)),
    "add_rule": ("Propose a world rule. It is saved as a studio draft; the creator decides what becomes canon.",
                 dict(S(title=STR, rule=STR, layer=LAYER, source_id=INT), required=["title", "rule"])),
    "log_studio": ("Write down something that happened in the open episode, as a studio draft. kind: " + ", ".join(KINDS) + ".",
                   dict(S(text=STR, kind={"type": "string", "enum": list(KINDS)}, quest=STR, known_by=STR, layer=LAYER, source_id=INT), required=["text"])),
    "save_draft": ("Save a deliverable as a DRAFT for the creator to revise and approve. kind: " + ", ".join(ARTIFACT_KINDS) + ". You cannot approve it.",
                   dict(S(kind={"type": "string", "enum": list(ARTIFACT_KINDS)}, content=STR, episode=INT, mode={"type": "string", "enum": list(MODES)},
                          layer=LAYER, source_id=INT, title=STR), required=["kind", "content"])),
    "revise_draft": ("Save a new version of a draft (it goes back to draft status).", dict(S(draft_id=INT, content=STR), required=["draft_id", "content"])),
    "list_drafts": ("List drafts and their status.", S(episode=INT, status={"type": "string", "enum": list(ARTIFACT_STATUS)})),
})


def _fmt_entry(e):
    return f"#{e['id']} ({e['layer']}, {e['permission']}) {e['title']}"


def call(st, name, a):
    if name in BASE_SAFE:
        return mcp_server.call(st, name, a)
    if name == "studio_recap":
        return st.studio_recap(READ_SCOPE, a.get("layer"), a.get("as"), int(a.get("episodes", 3)))
    if name == "studio_prompt":
        sid = a.get("source_id")
        return studio_prompt(st, a["mode"], a.get("episode"), None if sid is None else int(sid), a.get("focus", ""), a.get("layer", "live_action"))
    if name == "list_entries":
        return "\n".join(_fmt_entry(e) for e in st.list_entries(READ_SCOPE)) or "no entries released to the studio"
    if name == "get_entry":
        e = st.get_entry(int(a["source_id"]), READ_SCOPE)
        if e is None:
            raise StoryError("that entry is not available to the studio")
        return _fmt_entry(e) + "\n" + e["text"]
    if name == "list_rules":
        return "\n".join(f"#{r['id']} ({r['layer']}, {r['permission']}) {r['title']}: {r['rule']}" for r in st.list_rules(READ_SCOPE, a.get("layer"))) or "no rules"
    if name == "add_rule":
        if any(r["title"].lower() == str(a["title"]).strip().lower() for r in st.list_rules("creator")):
            raise StoryError("a rule with that title already exists; only the creator edits existing rules. Propose it under a new title")
        return f"rule {st.add_rule(a['title'], a['rule'], a.get('layer', 'live_action'), 'studio_draft', _src(a))} saved as studio_draft"
    if name == "log_studio":
        return f"event {st.log_studio(a['text'], a.get('kind', 'event'), a.get('quest', ''), a.get('known_by', ''), a.get('layer', 'live_action'), 'studio_draft', _src(a))} logged as studio_draft"
    if name == "save_draft":
        ep = a.get("episode")
        return f"draft {st.save_draft(a['kind'], a['content'], episode=None if ep is None else int(ep), mode=a.get('mode', 'writer'), layer=a.get('layer', 'live_action'), source_id=_src(a), title=a.get('title', ''))} saved as a draft; the creator must approve it"
    if name == "revise_draft":
        return f"draft {st.revise_draft(int(a['draft_id']), a['content'])} saved as a new draft version"
    if name == "list_drafts":
        ep = a.get("episode")
        rows = st.list_drafts(None if ep is None else int(ep), a.get("status"), READ_SCOPE)
        return "\n".join(f"#{d['id']} ep{d['episode']} {d['kind']} v{d['version']} [{d['status']}] ({d['layer']}, {d['mode']}) {d['title']}".rstrip() for d in rows) or "no drafts"
    raise StoryError("unknown tool " + name)


def _src(a):
    return None if a.get("source_id") is None else int(a["source_id"])


def handle(st, msg):
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": params.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
               "serverInfo": {"name": "episodekeep-studio", "version": "0.1.1"}}
    elif method == "tools/list":
        res = {"tools": [{"name": n, "description": d, "inputSchema": sch} for n, (d, sch) in TOOLS.items()]}
    elif method == "tools/call":
        try:
            if params.get("name", "") not in TOOLS:
                raise StoryError("unknown tool " + str(params.get("name", "")))
            text, err = call(st, params["name"], params.get("arguments") or {}), False
        except (StoryError, KeyError, ValueError, TypeError) as e:
            text, err = f"error: {e}", True
        res = {"content": [{"type": "text", "text": text}], "isError": err}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}


def serve(path=None):
    st = StudioStory(path)
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


if __name__ == "__main__":
    sys.exit(serve())
