#!/usr/bin/env python3
"""Mutation suite for episodekeep/studio_db.py: break one consent/approval guard at a time."""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "episodekeep" / "studio_db.py"
TEST = ROOT / "tests" / "test_studio_db.py"

MUTATIONS = [
    ("private permission leaked into studio scope",
     [('return permission in ("studio_draft", "approved_canon", "audience_safe")',
       'return permission in ("private", "studio_draft", "approved_canon", "audience_safe")')],
     "test_private_entry_never_leaks_to_studio_or_audience"),
    ("audience scope no longer restricts to audience_safe",
     [('return permission == "audience_safe" and layer != "real_life"',
       'return layer != "real_life"')],
     "test_private_entry_never_leaks_to_studio_or_audience"),
    ("real_life layer allowed into audience scope",
     [('return permission == "audience_safe" and layer != "real_life"',
       'return permission == "audience_safe"')],
     "test_real_life_layer_blocked_from_audience_even_if_marked_audience_safe"),
    ("source revocation check removed",
     [('if src["revoked"]:\n            return False',
       'if False:\n            return False')],
     "test_revoking_source_cascades_to_rules_characters_events_and_artifacts"),
    ("private source allowed to pass studio source check",
     [('if scope == "studio" and src["permission"] == "private":\n            return False',
       'if False:\n            return False')],
     "test_private_source_cannot_be_used_in_studio_recap_even_if_draft_linked"),
    ("unapproved drafts exported in export_package",
     [('a for a in self.list_drafts(episode=int(episode), status="approved", scope=scope)',
       'a for a in self.list_drafts(episode=int(episode), status=None, scope=scope)')],
     "test_unapproved_and_rejected_drafts_never_export"),
    ("approve_draft allows approving private-source draft",
     [('if src["permission"] == "private":\n                raise StoryError(f"cannot approve draft backed by private source #{row[\'source_id\']}")',
       'if False:\n                raise StoryError("disabled")')],
     "test_unapproved_and_rejected_drafts_never_export"),
    ("audience recap leaks premise/Previously/quests",
     [('if scope != "audience" and self.meta("premise"):', 'if self.meta("premise"):'),
      ('if scope != "audience":', 'if True:')],
     "test_cross_review_fixes_fail_closed_audience_strip_lineage_and_entries_flag"),
    ("unmetered rows fail-open instead of private",
     [('{"layer": "real_life", "permission": "private", "source_id": None}',
       '{"layer": "live_action", "permission": "studio_draft", "source_id": None}')],
     "test_cross_review_fixes_fail_closed_audience_strip_lineage_and_entries_flag"),
    ("superseded parent draft exported alongside revised version",
     [('superseded_ids = {a["parent_id"] for a in approved_raw if a.get("parent_id") is not None}',
       'superseded_ids = set()')],
     "test_cross_review_fixes_fail_closed_audience_strip_lineage_and_entries_flag"),
    ("rejected draft can be approved",
     [('if row["status"] == "rejected":', 'if False:')],
     "test_cross_review_fixes_fail_closed_audience_strip_lineage_and_entries_flag"),
    ("log_studio allows private rows into base events/FTS",
     [('if permission == "private":\n            raise StoryError("private notes belong in import_entry (sources), not the shared episode event log")',
       'if False:\n            raise StoryError("disabled")')],
     "test_cross_review_fixes_fail_closed_audience_strip_lineage_and_entries_flag"),
]


def _run_tests(pkg_root: Path, test_name: str | None = None) -> subprocess.CompletedProcess:
    target = f"tests.test_studio_db.StudioConsentTests.{test_name}" if test_name else "tests.test_studio_db"
    return subprocess.run(
        [sys.executable, "-m", "unittest", target],
        cwd=pkg_root,
        env={"PATH": "/usr/bin:/bin", "HOME": str(Path.home())},
        capture_output=True,
        text=True,
    )


def main() -> int:
    base = _run_tests(ROOT)
    print("baseline:", "PASS" if base.returncode == 0 else "FAIL\n" + base.stderr[-1500:])
    if base.returncode != 0:
        return 1

    bad = 0
    for label, edits, test_name in MUTATIONS:
        orig = SRC.read_text(encoding="utf-8")
        mut = orig
        for old, new in edits:
            if old not in mut:
                print(f"MUTATION NOT APPLICABLE ({label}): {old[:60]!r}")
                bad += 1
                break
            mut = mut.replace(old, new)
        else:
            with tempfile.TemporaryDirectory() as td:
                w = Path(td)
                (w / "episodekeep").mkdir()
                for f in (ROOT / "episodekeep").glob("*.py"):
                    (w / "episodekeep" / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
                (w / "episodekeep" / "studio_db.py").write_text(mut, encoding="utf-8")
                (w / "tests").mkdir()
                (w / "tests" / "test_studio_db.py").write_text(TEST.read_text(encoding="utf-8"), encoding="utf-8")
                res = _run_tests(w, test_name)
            caught = res.returncode != 0
            print(("caught  " if caught else "MISSED  ") + label)
            if not caught:
                bad += 1

    print(f"{len(MUTATIONS) - bad}/{len(MUTATIONS)} mutations caught")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
