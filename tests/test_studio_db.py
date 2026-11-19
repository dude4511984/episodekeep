import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from episodekeep.db import StoryError  # noqa: E402
from episodekeep.studio_db import StudioStory  # noqa: E402


def fresh() -> StudioStory:
    d = tempfile.mkdtemp()
    return StudioStory(os.path.join(d, "story.db"))


class StudioConsentTests(unittest.TestCase):
    def test_private_entry_never_leaks_to_studio_or_audience(self):
        st = fresh()
        st.set_meta("title", "The Ada Series")
        sid_priv = st.import_entry(
            "Private Therapy Reflection",
            "SECRET_REAL_LIFE_DETAIL_99",
            layer="real_life",
            permission="private",
            source_label="My Journal",
        )
        sid_ok = st.import_entry(
            "The Grocery Run",
            "Went out for sparkling water and turned an errand into a skit.",
            layer="real_life",
            permission="studio_draft",
            source_label="My Journal",
        )
        self.assertEqual(len(st.list_entries("creator")), 2)
        self.assertEqual([e["id"] for e in st.list_entries("studio")], [sid_ok])
        self.assertEqual(st.list_entries("audience"), [])
        self.assertIsNone(st.get_entry(sid_priv, "studio"))
        self.assertIsNone(st.get_entry(sid_priv, "audience"))

        st.add_rule("CanonOnlyRule", "APPROVED_CANON_NOT_AUDIENCE", layer="live_action", permission="approved_canon", source_id=sid_ok)
        studio_txt = st.studio_recap("studio")
        aud_txt = st.studio_recap("audience")
        self.assertNotIn("SECRET_REAL_LIFE_DETAIL_99", studio_txt)
        self.assertNotIn("SECRET_REAL_LIFE_DETAIL_99", aud_txt)
        self.assertIn("Grocery Run", studio_txt)
        self.assertIn("APPROVED_CANON_NOT_AUDIENCE", studio_txt)
        self.assertNotIn("Grocery Run", aud_txt)
        self.assertNotIn("APPROVED_CANON_NOT_AUDIENCE", aud_txt)
        self.assertIn("SECRET_REAL_LIFE_DETAIL_99", st.studio_recap("creator"))
        st.close()

    def test_real_life_layer_blocked_from_audience_even_if_marked_audience_safe(self):
        st = fresh()
        st.import_entry("Actual Diary", "REAL_DIARY_LINE", layer="real_life", permission="audience_safe")
        st.upsert_character("RealMe", "npc", "REAL_PERSON_BIO")
        st.tag_character("RealMe", layer="real_life", permission="audience_safe")
        st.add_rule("HomeAddress", "REAL_HOME_RULE", layer="real_life", permission="audience_safe")
        st.start_episode("Pilot")
        st.log_studio("REAL_LIFE_EVENT", layer="real_life", permission="audience_safe")

        aud = st.studio_recap("audience")
        self.assertNotIn("REAL_DIARY_LINE", aud)
        self.assertNotIn("REAL_PERSON_BIO", aud)
        self.assertNotIn("REAL_HOME_RULE", aud)
        self.assertNotIn("REAL_LIFE_EVENT", aud)
        st.close()

    def test_revoking_source_cascades_to_rules_characters_events_and_artifacts(self):
        st = fresh()
        sid = st.import_entry("Errand Note", "Inspiring errand moment", layer="real_life", permission="studio_draft")
        st.upsert_character("Ada Reed", "pc", "Witty creator protagonist", "Warm, fast-paced")
        st.tag_character("Ada Reed", layer="live_action", permission="audience_safe", source_id=sid)
        st.add_rule("Tone Rule", "Keep skits grounded and warm", layer="live_action", permission="audience_safe", source_id=sid)
        st.start_episode("The Grocery Run")
        st.log_studio("Aisle 4 comedy beat", layer="live_action", permission="audience_safe", source_id=sid)
        did = st.save_draft("script", "ADA: We came for oat milk.", mode="writer", layer="live_action", source_id=sid)
        st.approve_draft(did, permission="audience_safe")

        # Visible before revocation
        pkg_before = st.export_package(1, audience_only=True)
        self.assertEqual(len(pkg_before["artifacts"]), 1)
        self.assertEqual(len(pkg_before["characters"]), 1)
        self.assertEqual(len(pkg_before["world_rules"]), 1)
        self.assertEqual(len(pkg_before["events"]), 1)

        # Revoke source -> everything derived from sid disappears from studio & audience & export
        st.revoke_entry(sid)
        self.assertIsNone(st.get_entry(sid, "studio"))
        studio_recap = st.studio_recap("studio")
        self.assertNotIn("Keep skits grounded", studio_recap)
        self.assertNotIn("Aisle 4 comedy beat", studio_recap)
        self.assertNotIn("Ada Reed", studio_recap)

        pkg_after = st.export_package(1, audience_only=True)
        self.assertEqual(pkg_after["artifacts"], [])
        self.assertEqual(pkg_after["characters"], [])
        self.assertEqual(pkg_after["world_rules"], [])
        self.assertEqual(pkg_after["events"], [])
        with self.assertRaises(StoryError):
            st.save_draft("outline", "Should fail on revoked source", source_id=sid)
        st.close()

    def test_unapproved_and_rejected_drafts_never_export(self):
        st = fresh()
        st.set_meta("title", "The Ada Series")
        sid = st.import_entry("Entry 1", "Sparkling water quest", layer="real_life", permission="studio_draft")
        st.start_episode("Ep 1")
        d1 = st.save_draft("outline", "UNAPPROVED_OUTLINE_V1", mode="storyteller", layer="live_action", source_id=sid)
        d2 = st.revise_draft(d1, "APPROVED_OUTLINE_V2")
        d_rej = st.save_draft("script", "REJECTED_SCRIPT", mode="writer", layer="live_action", source_id=sid)
        st.reject_draft(d_rej, "too broad")

        # Before approval: nothing exported
        md0 = st.export_package_markdown(1, audience_only=False)
        self.assertNotIn("UNAPPROVED_OUTLINE_V1", md0)
        self.assertNotIn("APPROVED_OUTLINE_V2", md0)
        self.assertNotIn("REJECTED_SCRIPT", md0)

        # Approve d2 as approved_canon -> appears in canon export, NOT audience_only export
        st.approve_draft(d2, permission="approved_canon")
        md_canon = st.export_package_markdown(1, audience_only=False)
        md_aud = st.export_package_markdown(1, audience_only=True)
        self.assertIn("APPROVED_OUTLINE_V2", md_canon)
        self.assertNotIn("UNAPPROVED_OUTLINE_V1", md_canon)
        self.assertNotIn("REJECTED_SCRIPT", md_canon)
        self.assertNotIn("APPROVED_OUTLINE_V2", md_aud)

        # Cannot approve a draft backed by a private source
        priv_id = st.import_entry("Priv", "Secret", layer="real_life", permission="private")
        d_priv = st.save_draft("script", "DRAFT_FROM_PRIV", source_id=priv_id)
        with self.assertRaises(StoryError):
            st.approve_draft(d_priv, permission="audience_safe")

        # Even if a standalone draft row somehow carried approved_canon permission while status='draft', export must exclude it
        d_standalone = st.save_draft("themes", "UNAPPROVED_STANDALONE_THEMES", source_id=sid)
        st.db.execute("UPDATE artifacts SET permission='approved_canon' WHERE id=?", (d_standalone,))
        st.db.commit()
        self.assertNotIn("UNAPPROVED_STANDALONE_THEMES", st.export_package_markdown(1, audience_only=False))
        st.close()

    def test_cross_review_fixes_fail_closed_audience_strip_lineage_and_entries_flag(self):
        st = fresh()
        st.set_meta("title", "The Ada Series")
        st.set_meta("premise", "CREATOR_ONLY_PREMISE")
        st.upsert_character("UnmeteredChar", "npc", "UNMETERED_SHEET")
        st.start_episode("Ep 1")
        st.add_quest("SECRET_CREATOR_QUEST", "Keep off audience")
        st.log("UNMETERED_BASE_EVENT")
        st.end_episode("CREATOR_EP1_SUMMARY")

        # 1) Unmetered base character/event must default to private (absent from studio & audience)
        studio_txt = st.studio_recap("studio")
        self.assertNotIn("UnmeteredChar", studio_txt)
        self.assertNotIn("UNMETERED_BASE_EVENT", studio_txt)

        # 2) Audience recap & export omit premise, Previously summaries, and Open quests
        st.start_episode("Ep 2")
        st.add_quest("OPEN_STUDIO_QUEST", "Internal arc")
        aud_recap = st.studio_recap("audience")
        self.assertNotIn("CREATOR_ONLY_PREMISE", aud_recap)
        self.assertNotIn("CREATOR_EP1_SUMMARY", aud_recap)
        self.assertNotIn("OPEN_STUDIO_QUEST", aud_recap)

        pkg_aud = st.export_package(1, audience_only=True)
        self.assertEqual(pkg_aud["series"]["premise"], "")
        self.assertEqual(pkg_aud["episode"]["summary"], "")
        self.assertNotIn("CREATOR_EP1_SUMMARY", st.export_package_markdown(1, audience_only=True))

        # 3) entries=False omits Approved source entries section
        sid = st.import_entry("Allowed", "ENTRY_BODY_MARKER", layer="real_life", permission="studio_draft")
        self.assertIn("ENTRY_BODY_MARKER", st.studio_recap("studio", entries=True))
        self.assertNotIn("ENTRY_BODY_MARKER", st.studio_recap("studio", entries=False))

        # 4) Lineage: approving v2 supersedes v1 in export; rejected draft cannot be approved
        v1 = st.save_draft("outline", "OUTLINE_V1", source_id=sid)
        st.approve_draft(v1, permission="approved_canon")
        v2 = st.revise_draft(v1, "OUTLINE_V2")
        st.approve_draft(v2, permission="approved_canon")
        md_exp = st.export_package_markdown(2, audience_only=False)
        self.assertIn("OUTLINE_V2", md_exp)
        self.assertNotIn("OUTLINE_V1", md_exp)

        d_bad = st.save_draft("script", "BAD_DRAFT", source_id=sid)
        st.reject_draft(d_bad, "nope")
        with self.assertRaises(StoryError):
            st.approve_draft(d_bad, permission="approved_canon")

        # 5) log_studio refuses permission="private" so private text never enters base events/FTS
        with self.assertRaises(StoryError):
            st.log_studio("NEVER_IN_BASE_EVENTS", permission="private")
        self.assertEqual(st.search("NEVER_IN_BASE_EVENTS"), [])
        st.close()

    def test_private_source_cannot_be_used_in_studio_recap_even_if_draft_linked(self):
        st = fresh()
        priv_id = st.import_entry("Private Note", "PRIVATE_MOTHER_STORY", layer="real_life", permission="private")
        st.start_episode("Ep 1")
        d_priv = st.save_draft("themes", "DRAFT_USING_PRIV", source_id=priv_id)
        self.assertEqual(st.list_drafts(scope="studio"), [])
        self.assertEqual(len(st.list_drafts(scope="creator")), 1)
        self.assertEqual(d_priv, st.list_drafts(scope="creator")[0]["id"])
        st.close()


if __name__ == "__main__":
    unittest.main()
