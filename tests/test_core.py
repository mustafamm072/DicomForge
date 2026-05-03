import unittest

from dicomforge import AnonymizationAction, AnonymizationPlan, DicomDataset, Tag, TransferSyntax
from dicomforge.codecs import default_registry
from dicomforge.errors import UnsupportedTransferSyntaxError
from dicomforge.uids import TransferSyntaxUID


class TagTests(unittest.TestCase):
    def test_parse_keyword_and_hex(self):
        self.assertEqual(Tag.parse("PatientName"), Tag.PatientName)
        self.assertEqual(Tag.parse("(0010,0010)"), Tag.PatientName)
        self.assertEqual(Tag.parse("00100010"), Tag.PatientName)

    def test_private_tag_detection(self):
        self.assertTrue(Tag(0x0011, 0x1001).is_private)
        self.assertFalse(Tag.PatientName.is_private)


class DatasetTests(unittest.TestCase):
    def test_dataset_normalizes_tags(self):
        dataset = DicomDataset({"PatientName": "Ada"})
        self.assertEqual(dataset.get(Tag.PatientName), "Ada")
        dataset[(0x0008, 0x0060)] = "MR"
        self.assertEqual(dataset.get("Modality"), "MR")

    def test_dataset_removes_private_tags_recursively(self):
        child = DicomDataset({"PatientName": "Nested", (0x0011, 0x1001): "secret"})
        dataset = DicomDataset({"PatientName": "Ada", (0x0008, 0x1115): [child]})

        removed = dataset.remove_private_tags()

        self.assertEqual(removed, 1)
        self.assertIsNone(child.get((0x0011, 0x1001)))

    def test_dataset_iter_nested_reports_sequence_path(self):
        child = DicomDataset({"SOPInstanceUID": "1.2.3"})
        sequence_tag = Tag(0x0008, 0x1115)
        dataset = DicomDataset({sequence_tag: [child]})

        nested = list(dataset.iter_nested())

        self.assertIn(((sequence_tag,), Tag.SOPInstanceUID, "1.2.3"), nested)

    def test_anonymization_plan(self):
        dataset = DicomDataset(
            {
                "PatientName": "Ada",
                "PatientID": "123",
                "StudyInstanceUID": "1.2.3",
                (0x0011, 0x1001): "secret",
            }
        )
        report = AnonymizationPlan.starter_profile(uid_salt="test").apply_with_report(dataset)
        self.assertEqual(dataset.get("PatientName"), "Anonymous")
        self.assertEqual(dataset.get("PatientID"), "ANON")
        self.assertTrue(str(dataset.get("StudyInstanceUID")).startswith("2.25."))
        self.assertIsNone(dataset.get((0x0011, 0x1001)))
        self.assertEqual(report.private_tags_removed, 1)
        self.assertTrue(
            any(event.action == AnonymizationAction.REMAP_UID for event in report.events)
        )

    def test_anonymization_recurses_into_sequence_items(self):
        child = DicomDataset({"PatientName": "Nested", "SOPInstanceUID": "1.2.3.4"})
        dataset = DicomDataset({"PatientName": "Top", (0x0008, 0x1115): [child]})

        report = AnonymizationPlan.starter_profile(uid_salt="test").apply_with_report(dataset)

        self.assertEqual(dataset.get("PatientName"), "Anonymous")
        self.assertEqual(child.get("PatientName"), "Anonymous")
        self.assertTrue(str(child.get("SOPInstanceUID")).startswith("2.25."))
        self.assertTrue(any(event.path for event in report.events))

    def test_basic_profile_remains_compatibility_alias(self):
        dataset = DicomDataset({"PatientName": "Ada"})

        AnonymizationPlan.basic_profile().apply(dataset)

        self.assertEqual(dataset.get("PatientName"), "Anonymous")


class TransferSyntaxTests(unittest.TestCase):
    def test_known_transfer_syntax(self):
        syntax = TransferSyntax.from_uid(TransferSyntaxUID.ExplicitVRLittleEndian)
        self.assertTrue(syntax.is_little_endian)
        self.assertTrue(syntax.is_explicit_vr)
        self.assertFalse(syntax.is_compressed)

    def test_unknown_transfer_syntax_is_safe_default(self):
        syntax = TransferSyntax.from_uid("1.2.3")
        self.assertTrue(syntax.is_encapsulated)
        self.assertIn("Unknown", syntax.name)


class CodecRegistryTests(unittest.TestCase):
    def test_default_registry_supports_uncompressed(self):
        registry = default_registry()
        syntax = TransferSyntax.from_uid(TransferSyntaxUID.ExplicitVRLittleEndian)
        self.assertTrue(registry.supports(syntax))

    def test_default_registry_rejects_jpeg2000(self):
        registry = default_registry()
        syntax = TransferSyntax.from_uid(TransferSyntaxUID.JPEG2000Lossless)
        with self.assertRaises(UnsupportedTransferSyntaxError):
            registry.find(syntax)


if __name__ == "__main__":
    unittest.main()
