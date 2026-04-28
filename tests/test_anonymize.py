import unittest

from dicomforge import (
    AnonymizationAction,
    AnonymizationPlan,
    DicomDataset,
    PrivateTagAction,
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


if __name__ == "__main__":
    unittest.main()
