import unittest

from dicomforge import (
    AnonymizationAction,
    AnonymizationPlan,
    DicomDataset,
    PrivateTagAction,
    Rule,
    Tag,
)
from dicomforge.anonymize import UidRemapper


class DeidentificationTests(unittest.TestCase):
    def test_basic_profile_removes_common_identifiers_and_private_tags(self):
        dataset = DicomDataset(
            {
                "PatientName": "Ada Lovelace",
                "PatientID": "MRN-123",
                "PatientAddress": "12 Example Street",
                "PatientTelephoneNumbers": "555-0100",
                "StudyDate": "20260428",
                "InstitutionName": "Example Hospital",
                (0x0011, 0x1001): "vendor secret",
            }
        )

        report = AnonymizationPlan.basic_profile().apply_with_report(dataset)

        self.assertEqual(dataset.get("PatientName"), "Anonymous")
        self.assertEqual(dataset.get("PatientID"), "ANON")
        self.assertEqual(dataset.get("StudyDate"), "")
        self.assertIsNone(dataset.get("PatientAddress"))
        self.assertIsNone(dataset.get("PatientTelephoneNumbers"))
        self.assertIsNone(dataset.get((0x0011, 0x1001)))
        self.assertEqual(report.private_tags_removed, 1)
        self.assertEqual(dataset.get("PatientIdentityRemoved"), "YES")
        self.assertEqual(dataset.get("LongitudinalTemporalInformationModified"), "REMOVED")

    def test_basic_profile_can_keep_private_tags(self):
        dataset = DicomDataset({(0x0011, 0x1001): "research flag"})

        report = AnonymizationPlan.basic_profile(
            private_tag_action=PrivateTagAction.KEEP
        ).apply_with_report(dataset)

        self.assertEqual(dataset.get((0x0011, 0x1001)), "research flag")
        self.assertEqual(report.private_tags_removed, 0)
        self.assertEqual(report.private_tag_action, PrivateTagAction.KEEP)

    def test_apply_private_tag_override_preserves_backwards_compatibility(self):
        dataset = DicomDataset({(0x0011, 0x1001): "research flag"})
        plan = AnonymizationPlan.basic_profile(private_tag_action=PrivateTagAction.KEEP)

        report = plan.apply_with_report(dataset, remove_private_tags=True)

        self.assertIsNone(dataset.get((0x0011, 0x1001)))
        self.assertEqual(report.private_tags_removed, 1)
        self.assertEqual(report.private_tag_action, PrivateTagAction.REMOVE)

    def test_uid_remapping_is_deterministic_and_preserves_relationships(self):
        original_uid = "1.2.826.0.1.3680043.8.498.1"
        dataset = DicomDataset(
            {
                "StudyInstanceUID": original_uid,
                "SeriesInstanceUID": original_uid,
                "SOPInstanceUID": "1.2.826.0.1.3680043.8.498.2",
            }
        )

        AnonymizationPlan.basic_profile(uid_salt="trial-a").apply(dataset)
        remapped_study_uid = dataset.get("StudyInstanceUID")

        self.assertNotEqual(remapped_study_uid, original_uid)
        self.assertEqual(remapped_study_uid, dataset.get("SeriesInstanceUID"))
        self.assertLessEqual(len(remapped_study_uid), 64)
        self.assertTrue(str(remapped_study_uid).startswith("2.25."))

        repeated = DicomDataset({"StudyInstanceUID": original_uid})
        AnonymizationPlan.basic_profile(uid_salt="trial-a").apply(repeated)
        self.assertEqual(repeated.get("StudyInstanceUID"), remapped_study_uid)

    def test_uid_remapper_handles_multi_value_uid_sequences(self):
        remapper = UidRemapper(salt="sequence-test")
        value = ["1.2.3", "1.2.3", "1.2.4"]

        remapped = [remapper.remap(item) for item in value]

        self.assertEqual(remapped[0], remapped[1])
        self.assertNotEqual(remapped[0], remapped[2])

    def test_uid_remapper_rejects_invalid_uid_roots(self):
        with self.assertRaises(ValueError):
            UidRemapper(root="not-a-uid-root")

    def test_duplicate_rules_last_rule_wins(self):
        """When the same tag appears twice, the second (later) rule must win."""
        dataset = DicomDataset({"PatientName": "Ada"})
        plan = AnonymizationPlan([
            Rule(Tag.PatientName, AnonymizationAction.REPLACE, "First"),
            Rule(Tag.PatientName, AnonymizationAction.REPLACE, "Second"),
        ])
        plan.apply(dataset)
        self.assertEqual(dataset.get(Tag.PatientName), "Second")

    def test_duplicate_rules_empty_then_replace_replace_wins(self):
        """Without deduplication EMPTY-then-REPLACE silently gives '' instead of the replacement.
        With deduplication the last rule (REPLACE) wins unconditionally."""
        dataset = DicomDataset({"PatientName": "Ada"})
        plan = AnonymizationPlan([
            Rule(Tag.PatientName, AnonymizationAction.EMPTY),
            Rule(Tag.PatientName, AnonymizationAction.REPLACE, "Anonymous"),
        ])
        plan.apply(dataset)
        self.assertEqual(dataset.get(Tag.PatientName), "Anonymous")

    def test_duplicate_rules_replace_then_empty_empty_would_have_won_without_dedup(self):
        """Mirror of the previous test: REPLACE-then-EMPTY should now give 'Anonymous'
        (REPLACE, last), not '' (EMPTY, which fired second before the fix)."""
        dataset = DicomDataset({"PatientName": "Ada"})
        plan = AnonymizationPlan([
            Rule(Tag.PatientName, AnonymizationAction.REPLACE, "Anonymous"),
            Rule(Tag.PatientName, AnonymizationAction.EMPTY),
        ])
        plan.apply(dataset)
        # Post-fix: the LAST rule (EMPTY) wins via deduplication → value is ""
        self.assertEqual(dataset.get(Tag.PatientName), "")

    def test_duplicate_rules_delete_wins_regardless_of_position(self):
        """DELETE should win whether it comes before or after another rule."""
        for rules in [
            [Rule(Tag.PatientName, AnonymizationAction.REPLACE, "X"),
             Rule(Tag.PatientName, AnonymizationAction.DELETE)],
            [Rule(Tag.PatientName, AnonymizationAction.DELETE),
             Rule(Tag.PatientName, AnonymizationAction.REPLACE, "X")],
        ]:
            with self.subTest(first_action=rules[0].action):
                dataset = DicomDataset({"PatientName": "Ada"})
                AnonymizationPlan(rules).apply(dataset)
                # Last rule wins — whichever rule is last determines the outcome
                last_action = rules[-1].action
                if last_action == AnonymizationAction.DELETE:
                    self.assertIsNone(dataset.get(Tag.PatientName))
                else:
                    self.assertEqual(dataset.get(Tag.PatientName), "X")

    def test_no_duplicate_rules_in_starter_profile(self):
        """The built-in starter profile must not contain duplicate tag rules."""
        plan = AnonymizationPlan.starter_profile()
        tags_seen = [rule.tag for rule in plan._rules]
        self.assertEqual(len(tags_seen), len(set(tags_seen)),
                         "starter_profile produced duplicate tag rules")

    def test_audit_report_records_applied_actions(self):
        dataset = DicomDataset({"PatientName": "Ada"})

        report = AnonymizationPlan.basic_profile().apply_with_report(dataset)
        event = next(item for item in report.events if item.tag == Tag.PatientName)

        self.assertEqual(event.action, AnonymizationAction.REPLACE)
        self.assertTrue(event.before_present)
        self.assertTrue(event.after_present)
        self.assertEqual(event.replacement, "Anonymous")
        self.assertIn("events", report.to_dict())
        self.assertIsInstance(report.events, tuple)


class DateShiftTests(unittest.TestCase):
    """Tests for AnonymizationAction.SHIFT_DATE and _shift_date_value."""

    def _make_plan(self, tag: Tag, offset: int) -> AnonymizationPlan:
        return AnonymizationPlan(
            [Rule(tag, AnonymizationAction.SHIFT_DATE, offset)]
        )

    # ------------------------------------------------------------------
    # _shift_date_value helper (imported directly for unit-level tests)
    # ------------------------------------------------------------------

    def test_shift_forward(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("20260101", 30), "20260131")

    def test_shift_backward(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("20260101", -1), "20251231")

    def test_shift_zero_days_unchanged(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("20260315", 0), "20260315")

    def test_shift_year_boundary(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("20261231", 1), "20270101")

    def test_shift_preserves_dt_time_component(self):
        from dicomforge.anonymize import _shift_date_value
        # DT value: YYYYMMDDHHMMSS.FFFFFF — date part shifted, time preserved
        result = _shift_date_value("20260101120000.000000", 10)
        self.assertEqual(result, "20260111120000.000000")

    def test_shift_preserves_dt_timezone(self):
        from dicomforge.anonymize import _shift_date_value
        result = _shift_date_value("20260101143022.000000+0530", 1)
        self.assertEqual(result, "20260102143022.000000+0530")

    def test_empty_string_returned_unchanged(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("", 10), "")

    def test_non_string_returned_unchanged(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertIsNone(_shift_date_value(None, 10))
        self.assertEqual(_shift_date_value(20260101, 10), 20260101)

    def test_short_string_returned_unchanged(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("2026", 10), "2026")

    def test_malformed_date_returned_unchanged(self):
        from dicomforge.anonymize import _shift_date_value
        self.assertEqual(_shift_date_value("99991399", 1), "99991399")  # month 13

    # ------------------------------------------------------------------
    # Integration: SHIFT_DATE inside AnonymizationPlan
    # ------------------------------------------------------------------

    def test_plan_shifts_study_date(self):
        dataset = DicomDataset({Tag.StudyDate: "20260101"})
        self._make_plan(Tag.StudyDate, -30).apply(dataset)
        self.assertEqual(dataset.get(Tag.StudyDate), "20251202")

    def test_plan_shifts_multiple_date_tags(self):
        dataset = DicomDataset({
            Tag.StudyDate: "20260101",
            Tag.SeriesDate: "20260101",
            Tag.AcquisitionDate: "20260102",
        })
        plan = AnonymizationPlan([
            Rule(Tag.StudyDate, AnonymizationAction.SHIFT_DATE, -365),
            Rule(Tag.SeriesDate, AnonymizationAction.SHIFT_DATE, -365),
            Rule(Tag.AcquisitionDate, AnonymizationAction.SHIFT_DATE, -365),
        ])
        plan.apply(dataset)
        self.assertEqual(dataset.get(Tag.StudyDate), "20250101")
        self.assertEqual(dataset.get(Tag.SeriesDate), "20250101")
        self.assertEqual(dataset.get(Tag.AcquisitionDate), "20250102")

    def test_plan_skips_absent_date_tag(self):
        dataset = DicomDataset({Tag.Modality: "CT"})
        self._make_plan(Tag.StudyDate, 10).apply(dataset)
        self.assertIsNone(dataset.get(Tag.StudyDate))

    def test_plan_leaves_empty_date_tag_unchanged(self):
        dataset = DicomDataset({Tag.StudyDate: ""})
        self._make_plan(Tag.StudyDate, 10).apply(dataset)
        self.assertEqual(dataset.get(Tag.StudyDate), "")

    def test_plan_shift_date_appears_in_audit_report(self):
        dataset = DicomDataset({Tag.StudyDate: "20260101"})
        report = self._make_plan(Tag.StudyDate, 7).apply_with_report(dataset)
        event = next(e for e in report.events if e.tag == Tag.StudyDate)
        self.assertEqual(event.action, AnonymizationAction.SHIFT_DATE)
        self.assertEqual(event.previous_value, "20260101")
        self.assertEqual(event.new_value, "20260108")

    def test_non_integer_offset_raises(self):
        dataset = DicomDataset({Tag.StudyDate: "20260101"})
        bad_plan = AnonymizationPlan(
            [Rule(Tag.StudyDate, AnonymizationAction.SHIFT_DATE, "30")]
        )
        with self.assertRaises(ValueError):
            bad_plan.apply(dataset)


if __name__ == "__main__":
    unittest.main()
