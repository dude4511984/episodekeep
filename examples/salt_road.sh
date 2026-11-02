#!/bin/sh
# A tiny two-episode story. Run it, then read the recap as Mara and as the narrator.
#   sh examples/salt_road.sh
set -e
export EPISODEKEEP_DB="${TMPDIR:-/tmp}/salt_road_demo.db"; rm -f "$EPISODEKEEP_DB"
ek="python3 -m episodekeep"
$ek init "The Salt Road" --premise "A caravan crosses the dry sea."
$ek character Mara --pc --sheet "Scarred caravan guard, 40. Distrusts merchants." --voice "Dry, short sentences."
$ek character Vell --sheet "Merchant who owes Mara a debt."
$ek start "The Crossing"
$ek quest "Find the well" --description "Somewhere past the dunes"
$ek log "Vell lied about the cargo" --kind secret --known-by "Vell"
$ek log "Mara promised to bring the child home" --kind promise --quest "Find the well"
$ek log "The caravan lost two wagons on the salt flats"
$ek draft-summary            # paste this into an AI, then:
$ek end "They crossed the salt flats and lost two wagons. Mara promised to bring the child home."
$ek start "The Dunes"
$ek log "A storm pinned the caravan for a night"
echo; echo "=== what Mara is told (no secret) ==="; $ek recap --as Mara
echo; echo "=== the narrator's view (sees Vell's secret) ==="; $ek recap
echo; echo "database kept at $EPISODEKEEP_DB"
