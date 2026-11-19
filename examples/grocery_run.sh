#!/bin/sh
# The Grocery Run: ONE journal entry -> ONE episode, with the creator approving every step (Living Story Studio).
# Calls no AI: where an AI would write, a canned draft stands in so you can see the gates work.
#   sh examples/grocery_run.sh
set -e
export EPISODEKEEP_DB="${TMPDIR:-/tmp}/grocery_demo.db"; rm -f "$EPISODEKEEP_DB"
st="python3 -m episodekeep.studio_cli"
step() { echo; echo "=== $* ==="; }

step "1. the series and its fictional layer (live action: Ada Reed, not the creator)"
$st init "The Ada Series" --premise "A live-action series inspired by, and separate from, the creator's real life."
$st character Ada --pc --sheet "Ada Reed, hopeful, always late, keeps a lucky receipt." --voice "Warm, quick, self-teasing."
$st character Gus --sheet "The corner-store owner who knows everyone's order."
$st tag Ada --layer live_action --permission studio_draft
$st tag Gus --layer live_action --permission studio_draft
$st rule "Receipts are luck" "In the Ada universe a kept receipt brings small luck; a thrown-away one costs it." --layer live_action

step "2. import ONE entry by hand. It starts PRIVATE and real_life"
$st import "The Grocery Run" --label "My Journal" --text "Tuesday. Ran out of oat milk, walked to the grocery in the rain. Real name: Dana Whitfield, 14 Elm St. Cried a little in the car about Mum's diagnosis. The cashier gave me a free banana and I kept the receipt." 
$st entries

step "3. the gate: a private entry cannot feed the studio"
$st prompt writer --source 1 && echo "UNEXPECTED: private entry was accepted" && exit 1 || echo "(refused, as it should be)"
echo; echo "-- studio recap shows nothing from it:"; $st recap

step "4. creator authorises the entry for studio drafts, then starts the episode"
$st permit 1 studio_draft
$st start "The Grocery Run"
$st slog "Ada runs out of oat milk and walks to Gus's store in the rain." --kind event --source 1
$st slog "Gus hands Ada a free banana; she keeps the receipt." --kind fact --source 1

step "5. companion modes: print the prompts you would paste into an AI (storyteller + writer)"
$st prompt storyteller --episode 1 --source 1 --focus "what is this errand really about?"
echo "   (writer, worldbuilder and producer prompts work the same way: studio prompt writer --source 1)"

step "6. drafts come back; the creator revises, then approves"
$st draft themes --mode storyteller --source 1 --title "Themes" --text "Small kindnesses survive a hard week. A kept receipt is proof the day happened."
$st draft outline --mode writer --source 1 --title "Outline" --text "1. Ada, out of oat milk, braves the rain. 2. Gus's store: a free banana. 3. Ada keeps the receipt."
$st draft script --mode writer --source 1 --title "Script" --text "INT. GUS'S STORE - DAY. ADA: Rain's a free shower. GUS: Banana's free too."
$st revise 3 --text "INT. GUS'S STORE - DAY. ADA (shaking out her umbrella): Rain's a free shower. GUS: Banana's free too. ADA (pocketing the receipt): Lucky."
$st drafts
$st approve 1; $st approve 2; $st reject 3 --note "superseded by v2"; $st approve 4 --permission audience_safe

step "7. export package: approved work only (the real-life entry itself is never in it)"
$st end "Ada braved the rain for oat milk and left with a free banana and a lucky receipt."
$st package
echo; echo "-- audience-only version (audience_safe only):"; $st package --audience

step "8. the creator revokes the entry: everything linked to it leaves the studio and the audience views"
$st revoke 1
$st entries
echo "-- drafts the studio can still see:"; $st drafts --scope studio || true
echo "-- package after revoke:"; $st package
echo; echo "database kept at $EPISODEKEEP_DB"
