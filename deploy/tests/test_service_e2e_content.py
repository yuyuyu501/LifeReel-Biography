"""Keep correction assertions sensitive to prose, independent of random IDs."""

import unittest

from service_e2e import script_content


class ScriptContentTests(unittest.TestCase):
    def test_old_year_in_metadata_does_not_trigger_a_false_failure(self):
        project = {
            "id": "641988ee-059b-4e9c-beb1-504454f5f85b",
            "source_claim_ids": ["1988-reference"],
            "created_at": "2026-09-30T12:34:56.198800",
            "title": "1989年的漳州",
            "scenes": [{"id": "1988-scene", "narration": "1989年，我在漳州上学。"}],
            "shots": [{"id": "1988-shot", "visual_prompt": "漳州的小学校门。"}],
        }
        content = script_content(project)
        self.assertIn("1989", content)
        self.assertNotIn("1988", content)

    def test_old_year_remains_detectable_in_every_generated_text_field(self):
        for field in (
            "heading", "plot", "narration", "visual_prompt", "dialogues",
            "visual_constraints", "story_skeleton",
        ):
            with self.subTest(field=field):
                project = {"title": "人生", "scenes": [{field: "1988年的泉州"}], "shots": []}
                self.assertIn("1988", script_content(project))
        self.assertIn("1988", script_content({
            "title": "人生", "scenes": [], "shots": [{"visual_prompt": "1988年的泉州"}],
        }))


if __name__ == "__main__":
    unittest.main()
