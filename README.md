# Episodekeep

Keeps a story that runs across many episodes and quests straight, so an AI playing your character
remembers what happened, what it promised, and (just as important) what it does not know.

One file, `story.db`, holds everything. It lives on your computer. No account, no server, no internet.
Python 3.9+, standard library only.

## Use it with any AI (copy and paste)

    pip install .                                  # or just run: python -m episodekeep ...
    episodekeep init "The Salt Road" --premise "A caravan crosses the dry sea."
    episodekeep character Mara --pc --sheet "Scarred caravan guard, 40." --voice "Dry, short sentences."
    episodekeep character Vell --sheet "Merchant who owes Mara."
    episodekeep start "The Crossing"
    episodekeep quest "Find the well" --description "Somewhere past the dunes"
    episodekeep log "The caravan reached the dunes"
    episodekeep log "Vell lied about the cargo" --kind secret --known-by "Vell"
    episodekeep log "Mara promised to bring the child home" --kind promise --quest "Find the well"
    episodekeep end "They crossed the salt flats and lost two wagons."
    episodekeep recap --as Mara                    # paste this at the start of the next session

`recap --as Mara` prints a block telling the AI who it is, how it speaks, the cast, what happened
in recent episodes, open quests, promises made, and what Mara knows. A secret marked `--known-by Vell`
is left out of Mara's recap, so the AI can't use knowledge its character couldn't have.
`recap` with no name is the narrator's view and shows everything.

## Let the AI keep the notes itself (MCP)

Claude Desktop and other MCP apps can run it as a tool server. In the app's MCP config:

    {"mcpServers": {"episodekeep": {"command": "episodekeep", "args": ["--db", "/full/path/story.db", "mcp"]}}}

Tools: recap, start_episode, end_episode, log, add_quest, update_quest, character, search.
The AI can write things down as it plays and ask for the recap when a session starts.

## Commands
init, character, start, end, quest, quest-set (open, done, failed, dormant), log (event, fact, promise, secret, relationship),
search, recap, export (the whole story as markdown), mcp.

## What it is not
It stores what you or the AI write down; it does not read your chat and it does not decide what matters.
Summaries (`end`) are the memory that matters most: write them well. Nothing leaves your computer.
Keep `story.db` somewhere you back up. Tests: `python3 -m unittest discover -s tests`.

License: Apache-2.0. Made by Every Synthetic, Mena, Arkansas.
