import unittest
import sys
from unittest.mock import patch

from dicomforge import AnonymizationAction, AnonymizationPlan, DicomDataset, Tag, TransferSyntax
from dicomforge import generate_uid, is_valid_uid
from dicomforge.codecs import default_registry, pydicom_pixel_codec, pydicom_pixel_registry
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

    def test_copy_shallow_shares_nested_datasets(self):
        child = DicomDataset({"PatientName": "Original"})
        dataset = DicomDataset({"PatientName": "Top", (0x0008, 0x1115): [child]})

        shallow = dataset.copy()
        shallow.get((0x0008, 0x1115))[0].set("PatientName", "Mutated")

        # shallow copy: mutation visible in original
        self.assertEqual(child.get("PatientName"), "Mutated")

    def test_copy_deep_isolates_nested_datasets(self):
        child = DicomDataset({"PatientName": "Original"})
        dataset = DicomDataset({"PatientName": "Top", (0x0008, 0x1115): [child]})

        deep = dataset.copy(deep=True)
        deep.get((0x0008, 0x1115))[0].set("PatientName", "Mutated")

        # deep copy: original is unaffected
        self.assertEqual(child.get("PatientName"), "Original")
        self.assertEqual(deep.get((0x0008, 0x1115))[0].get("PatientName"), "Mutated")

    def test_copy_deep_top_level_tags_are_independent(self):
        dataset = DicomDataset({"PatientName": "Ada", "Modality": "CT"})

        deep = dataset.copy(deep=True)
        deep.set("PatientName", "Changed")

        self.assertEqual(dataset.get("PatientName"), "Ada")

    def test_basic_profile_remains_compatibility_alias(self):
        dataset = DicomDataset({"PatientName": "Ada"})

        AnonymizationPlan.basic_profile().apply(dataset)

        self.assertEqual(dataset.get("PatientName"), "Anonymous")


class UidHelpersTests(unittest.TestCase):

    # ------------------------------------------------------------------
    # is_valid_uid
    # ------------------------------------------------------------------

    def test_well_formed_uid_is_valid(self):
        self.assertTrue(is_valid_uid("1.2.840.10008.5.1.4.1.1.2"))

    def test_uid_at_exact_64_chars_is_valid(self):
        # Construct a UID that is exactly 64 characters long
        uid = "1.2." + "3" * 60  # 4 + 60 = 64 chars
        self.assertEqual(len(uid), 64)
        self.assertTrue(is_valid_uid(uid))

    def test_uid_exceeding_64_chars_is_invalid(self):
        uid = "1.2." + "3" * 61  # 65 chars
        self.assertFalse(is_valid_uid(uid))

    def test_empty_string_is_invalid(self):
        self.assertFalse(is_valid_uid(""))

    def test_non_string_is_invalid(self):
        for bad in [None, 123, 1.2, b"1.2.3", ["1", "2"]]:
            with self.subTest(value=bad):
                self.assertFalse(is_valid_uid(bad))

    def test_leading_zero_in_component_is_invalid(self):
        self.assertFalse(is_valid_uid("1.2.03.4"))   # "03" has leading zero
        self.assertFalse(is_valid_uid("1.02.3"))      # "02" has leading zero

    def test_single_zero_component_is_valid(self):
        # "0" on its own is the one allowed exception to the no-leading-zero rule
        self.assertTrue(is_valid_uid("1.0.2"))
        self.assertTrue(is_valid_uid("0"))

    def test_trailing_dot_is_invalid(self):
        self.assertFalse(is_valid_uid("1.2.3."))

    def test_leading_dot_is_invalid(self):
        self.assertFalse(is_valid_uid(".1.2.3"))

    def test_consecutive_dots_are_invalid(self):
        self.assertFalse(is_valid_uid("1..2.3"))

    def test_non_digit_characters_are_invalid(self):
        for bad in ["1.2.a", "1.2.3-4", "1.2.3/4", "1.2.3 4"]:
            with self.subTest(uid=bad):
                self.assertFalse(is_valid_uid(bad))

    def test_well_known_transfer_syntax_uid_is_valid(self):
        self.assertTrue(is_valid_uid(TransferSyntaxUID.ExplicitVRLittleEndian))

    # ------------------------------------------------------------------
    # generate_uid
    # ------------------------------------------------------------------

    def test_generated_uid_is_valid(self):
        uid = generate_uid()
        self.assertTrue(is_valid_uid(uid), f"Generated UID is not valid: {uid!r}")

    def test_generated_uid_uses_2_25_root_by_default(self):
        uid = generate_uid()
        self.assertTrue(uid.startswith("2.25."))

    def test_generated_uid_length_within_64(self):
        for _ in range(20):  # run several times to catch probabilistic edge cases
            self.assertLessEqual(len(generate_uid()), 64)

    def test_generated_uids_are_unique(self):
        uids = {generate_uid() for _ in range(100)}
        self.assertEqual(len(uids), 100)

    def test_custom_root_is_used(self):
        uid = generate_uid(root="1.2.840.99999")
        self.assertTrue(uid.startswith("1.2.840.99999."))
        self.assertTrue(is_valid_uid(uid))

    def test_custom_root_with_trailing_dot_is_normalised(self):
        uid = generate_uid(root="1.2.3.")
        self.assertTrue(uid.startswith("1.2.3."))
        self.assertFalse(uid.startswith("1.2.3.."))

    def test_invalid_root_raises_value_error(self):
        for bad_root in ["not-a-uid", "1.2.abc", "1.2. 3"]:
            with self.subTest(root=bad_root):
                with self.assertRaises(ValueError):
                    generate_uid(root=bad_root)

    def test_root_too_long_raises_value_error(self):
        # A root that fills all 64 characters leaves no room for a suffix
        too_long = "1." + "2" * 62  # 64 chars — no room for ".suffix"
        with self.assertRaises(ValueError):
            generate_uid(root=too_long)


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

    def test_pydicom_pixel_codec_is_absent_without_backend(self):
        with patch.dict(sys.modules, {"pydicom": None}):
            self.assertIsNone(pydicom_pixel_codec())
            registry = pydicom_pixel_registry()
            syntax = TransferSyntax.from_uid(TransferSyntaxUID.JPEG2000Lossless)
            self.assertFalse(registry.supports(syntax))

    def test_default_registry_registers_pydicom_bridge_when_backend_is_detected(self):
        import dicomforge.codecs as codecs

        old_registry = codecs._DEFAULT_REGISTRY
        codecs._DEFAULT_REGISTRY = None
        try:
            with patch.dict(sys.modules, {"pydicom": object()}):
                registry = default_registry()
            syntax = TransferSyntax.from_uid(TransferSyntaxUID.JPEG2000Lossless)
            codec = registry.find(syntax)
            self.assertEqual(codec.name, "pydicom-pixels")
        finally:
            codecs._DEFAULT_REGISTRY = old_registry


if __name__ == "__main__":
    unittest.main()
