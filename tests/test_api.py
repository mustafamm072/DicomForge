"""Tests for the high-level api.py convenience layer."""

import unittest

from dicomforge.api import DicomFile, validate_dataset, validate_for_sop_class
from dicomforge.dataset import DicomDataset
from dicomforge.tags import Tag
from dicomforge.uids import TransferSyntaxUID


def _minimal_dataset(**overrides) -> DicomDataset:
    """Return a dataset with all required storage tags present."""
    base = {
        Tag.SOPClassUID: "1.2.840.10008.5.1.4.1.1.2",
        Tag.SOPInstanceUID: "1.2.3.4.5.6",
        Tag.Modality: "CT",
        Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
        Tag.PatientName: "Ada Lovelace",
        Tag.PatientID: "MRN-001",
        Tag.StudyInstanceUID: "1.2.826.0.1.3680043.8.498.1",
        Tag.SeriesInstanceUID: "1.2.826.0.1.3680043.8.498.2",
        Tag.StudyDescription: "Brain MRI",
        Tag.SeriesDescription: "Axial T1",
        Tag.SeriesNumber: 1,
        Tag.InstanceNumber: 5,
        Tag.Manufacturer: "Acme Corp",
        Tag.ManufacturerModelName: "Scanner 3000",
        Tag.StationName: "SCANNER01",
        Tag.InstitutionName: "General Hospital",
    }
    base.update(overrides)
    return DicomDataset(base)


class ValidateDatasetTests(unittest.TestCase):
    def test_no_issues_for_complete_dataset(self):
        ds = _minimal_dataset()
        issues = validate_dataset(ds)
        self.assertEqual(issues, [])

    def test_missing_sop_class_uid(self):
        ds = _minimal_dataset()
        del ds[Tag.SOPClassUID]
        issues = validate_dataset(ds)
        self.assertTrue(any("SOPClassUID" in issue for issue in issues))

    def test_missing_modality(self):
        ds = _minimal_dataset()
        del ds[Tag.Modality]
        issues = validate_dataset(ds)
        self.assertTrue(any("Modality" in issue for issue in issues))

    def test_missing_transfer_syntax(self):
        ds = _minimal_dataset()
        del ds[Tag.TransferSyntaxUID]
        issues = validate_dataset(ds)
        self.assertTrue(any("TransferSyntaxUID" in issue for issue in issues))

    def test_burned_in_annotation_warning(self):
        ds = _minimal_dataset()
        ds.set(Tag.BurnedInAnnotation, "YES")
        issues = validate_dataset(ds)
        self.assertTrue(any("BurnedInAnnotation" in issue for issue in issues))

    def test_burned_in_annotation_no_warning(self):
        ds = _minimal_dataset()
        ds.set(Tag.BurnedInAnnotation, "NO")
        issues = validate_dataset(ds)
        self.assertFalse(any("BurnedInAnnotation" in issue for issue in issues))

    def test_pixel_metadata_inconsistency(self):
        ds = _minimal_dataset()
        ds.set(Tag.Rows, 64)
        ds.set(Tag.Columns, 64)
        ds.set(Tag.SamplesPerPixel, 1)
        ds.set(Tag.BitsAllocated, 16)
        ds.set(Tag.BitsStored, 20)  # > BitsAllocated — invalid
        ds.set(Tag.HighBit, 19)
        ds.set(Tag.PixelRepresentation, 0)
        ds.set(Tag.PhotometricInterpretation, "MONOCHROME2")
        issues = validate_dataset(ds)
        self.assertTrue(any("inconsistency" in issue.lower() for issue in issues))

    def test_valid_pixel_metadata_no_issues(self):
        ds = _minimal_dataset()
        ds.set(Tag.Rows, 64)
        ds.set(Tag.Columns, 64)
        ds.set(Tag.SamplesPerPixel, 1)
        ds.set(Tag.BitsAllocated, 16)
        ds.set(Tag.BitsStored, 16)
        ds.set(Tag.HighBit, 15)
        ds.set(Tag.PixelRepresentation, 0)
        ds.set(Tag.PhotometricInterpretation, "MONOCHROME2")
        issues = validate_dataset(ds)
        self.assertEqual(issues, [])


class DicomFilePropertiesTests(unittest.TestCase):
    def _make_file_with_dataset(self, dataset: DicomDataset) -> DicomFile:
        f = DicomFile.__new__(DicomFile)
        from pathlib import Path

        f._path = Path("dummy.dcm")
        f._stop_before_pixels = False
        f._dataset = dataset
        return f

    def test_named_properties(self):
        ds = _minimal_dataset()
        f = self._make_file_with_dataset(ds)
        self.assertEqual(f.patient_name, "Ada Lovelace")
        self.assertEqual(f.patient_id, "MRN-001")
        self.assertEqual(f.modality, "CT")
        self.assertEqual(f.study_instance_uid, "1.2.826.0.1.3680043.8.498.1")
        self.assertEqual(f.series_instance_uid, "1.2.826.0.1.3680043.8.498.2")
        self.assertEqual(f.sop_instance_uid, "1.2.3.4.5.6")
        self.assertEqual(f.sop_class_uid, "1.2.840.10008.5.1.4.1.1.2")
        self.assertEqual(f.study_description, "Brain MRI")
        self.assertEqual(f.series_description, "Axial T1")
        self.assertEqual(f.series_number, 1)
        self.assertEqual(f.instance_number, 5)
        self.assertEqual(f.manufacturer, "Acme Corp")
        self.assertEqual(f.station_name, "SCANNER01")
        self.assertEqual(f.institution_name, "General Hospital")

    def test_transfer_syntax_property(self):
        ds = _minimal_dataset()
        f = self._make_file_with_dataset(ds)
        ts = f.transfer_syntax
        self.assertTrue(ts.is_explicit_vr)
        self.assertTrue(ts.is_little_endian)
        self.assertFalse(ts.is_compressed)

    def test_missing_optional_property_returns_empty(self):
        ds = DicomDataset({Tag.SOPInstanceUID: "1.2.3"})
        f = self._make_file_with_dataset(ds)
        self.assertEqual(f.patient_name, "")
        self.assertEqual(f.modality, "")
        self.assertIsNone(f.series_number)
        self.assertIsNone(f.rows)
        self.assertIsNone(f.columns)

    def test_number_of_frames_defaults_to_one(self):
        ds = DicomDataset({Tag.SOPInstanceUID: "1.2.3"})
        f = self._make_file_with_dataset(ds)
        self.assertEqual(f.number_of_frames, 1)

    def test_anonymize_modifies_dataset(self):
        ds = _minimal_dataset()
        f = self._make_file_with_dataset(ds)
        report = f.anonymize(uid_salt="test-salt")
        self.assertEqual(ds.get(Tag.PatientName), "Anonymous")
        self.assertEqual(ds.get(Tag.PatientID), "ANON")
        self.assertIsNotNone(report)
        self.assertGreater(len(report.events), 0)

    def test_tags_returns_plain_dict(self):
        ds = _minimal_dataset()
        f = self._make_file_with_dataset(ds)
        tags = f.tags()
        self.assertIsInstance(tags, dict)
        self.assertIn("(0008,0060)", tags)

    def test_repr_contains_key_info(self):
        ds = _minimal_dataset()
        f = self._make_file_with_dataset(ds)
        r = repr(f)
        self.assertIn("CT", r)
        self.assertIn("Ada Lovelace", r)


class DicomFileLoadTests(unittest.TestCase):
    def _skip_if_no_pydicom(self):
        try:
            import pydicom  # noqa: F401
        except ImportError:
            self.skipTest("pydicom not installed")

    def test_load_raises_missing_backend_without_pydicom(self):
        import sys
        from unittest.mock import patch

        from dicomforge.errors import MissingBackendError

        with patch.dict(sys.modules, {"pydicom": None}):
            f = DicomFile("nonexistent.dcm")
            with self.assertRaises((MissingBackendError, Exception)):
                _ = f.dataset


class TagExtensionsTests(unittest.TestCase):
    """Verify the new tags added in v0.6.0 are accessible and parse correctly."""

    def test_new_clinical_tags_accessible(self):
        from dicomforge.tags import Tag

        self.assertIsNotNone(Tag.SeriesNumber)
        self.assertIsNotNone(Tag.InstanceNumber)
        self.assertIsNotNone(Tag.StudyDescription)
        self.assertIsNotNone(Tag.SeriesDescription)
        self.assertIsNotNone(Tag.Manufacturer)
        self.assertIsNotNone(Tag.ManufacturerModelName)
        self.assertIsNotNone(Tag.DeviceSerialNumber)
        self.assertIsNotNone(Tag.BodyPartExamined)
        self.assertIsNotNone(Tag.PixelSpacing)
        self.assertIsNotNone(Tag.SliceLocation)
        self.assertIsNotNone(Tag.ImagePositionPatient)
        self.assertIsNotNone(Tag.ImageOrientationPatient)
        self.assertIsNotNone(Tag.BurnedInAnnotation)

    def test_new_tags_parseable_by_keyword(self):
        from dicomforge.tags import Tag

        self.assertEqual(Tag.parse("SeriesNumber"), Tag.SeriesNumber)
        self.assertEqual(Tag.parse("BodyPartExamined"), Tag.BodyPartExamined)
        self.assertEqual(Tag.parse("PixelSpacing"), Tag.PixelSpacing)

    def test_tag_repr_uses_keyword_when_known(self):
        from dicomforge.tags import Tag

        self.assertEqual(repr(Tag.PatientName), "Tag.PatientName")
        self.assertEqual(repr(Tag.Modality), "Tag.Modality")

    def test_tag_repr_for_private_tag(self):
        from dicomforge.tags import Tag

        private = Tag(0x0011, 0x1001)
        self.assertIn("0011", repr(private))


class SopClassUidExtensionsTests(unittest.TestCase):
    def test_new_sop_class_uids_accessible(self):
        from dicomforge.uids import SopClassUID

        self.assertIsNotNone(SopClassUID.PositronEmissionTomographyImageStorage)
        self.assertIsNotNone(SopClassUID.UltrasoundImageStorage)
        self.assertIsNotNone(SopClassUID.RTDoseStorage)
        self.assertIsNotNone(SopClassUID.BasicTextSRStorage)
        self.assertIsNotNone(SopClassUID.EnhancedCTImageStorage)

    def test_new_transfer_syntax_uids_accessible(self):
        from dicomforge.uids import TransferSyntaxUID

        self.assertIsNotNone(TransferSyntaxUID.JPEGLSNearLossless)
        self.assertIsNotNone(TransferSyntaxUID.JPEG2000)
        self.assertIsNotNone(TransferSyntaxUID.HighThroughputJPEG2000)


class TransferSyntaxExtensionsTests(unittest.TestCase):
    def test_jpeg2000_lossy_registered(self):
        from dicomforge.transfer_syntax import TransferSyntax
        from dicomforge.uids import TransferSyntaxUID

        ts = TransferSyntax.from_uid(TransferSyntaxUID.JPEG2000)
        self.assertTrue(ts.is_compressed)
        self.assertNotIn("Unknown", ts.name)

    def test_jpeg_ls_near_lossless_registered(self):
        from dicomforge.transfer_syntax import TransferSyntax
        from dicomforge.uids import TransferSyntaxUID

        ts = TransferSyntax.from_uid(TransferSyntaxUID.JPEGLSNearLossless)
        self.assertTrue(ts.is_compressed)


class DatasetEnhancementsTests(unittest.TestCase):
    def test_copy_produces_independent_dataset(self):
        ds = DicomDataset({Tag.PatientName: "Ada", Tag.Modality: "CT"})
        copy = ds.copy()
        copy.set(Tag.PatientName, "Eve")
        self.assertEqual(ds.get(Tag.PatientName), "Ada")
        self.assertEqual(copy.get(Tag.PatientName), "Eve")

    def test_repr_shows_tag_count(self):
        ds = DicomDataset({Tag.PatientName: "Ada", Tag.Modality: "CT"})
        r = repr(ds)
        self.assertIn("count=2", r)

    def test_repr_empty_dataset(self):
        ds = DicomDataset()
        r = repr(ds)
        self.assertIn("count=0", r)


class AnonymizationEnhancementsTests(unittest.TestCase):
    def test_new_ps315_tags_are_removed(self):
        ds = DicomDataset(
            {
                Tag.PatientName: "Ada",
                Tag.PatientID: "MRN-001",
                Tag.PatientWeight: "70",
                Tag.PatientComments: "Healthy volunteer",
                Tag.EthnicGroup: "X",
                Tag.AttendingPhysicianName: "Dr Smith",
                Tag.DeviceSerialNumber: "SN-12345",
                Tag.InstitutionalDepartmentName: "Radiology",
                Tag.StudyInstanceUID: "1.2.3",
            }
        )
        from dicomforge.anonymize import AnonymizationPlan

        AnonymizationPlan.starter_profile().apply(ds)

        # These are DELETE rules — tag must be absent
        self.assertIsNone(ds.get(Tag.PatientWeight))
        self.assertIsNone(ds.get(Tag.PatientComments))
        self.assertIsNone(ds.get(Tag.EthnicGroup))
        self.assertIsNone(ds.get(Tag.DeviceSerialNumber))
        self.assertIsNone(ds.get(Tag.InstitutionalDepartmentName))
        # This is an EMPTY rule — tag present but blank
        attending = ds.get(Tag.AttendingPhysicianName)
        self.assertTrue(
            attending is None or str(attending).strip() == "",
            f"AttendingPhysicianName should be absent or empty, got {attending!r}",
        )

    def test_uid_remapper_is_thread_safe(self):
        import threading

        from dicomforge.anonymize import UidRemapper

        remapper = UidRemapper(salt="thread-test")
        results = []

        def do_remap():
            results.append(remapper.remap("1.2.3.4.5"))

        threads = [threading.Thread(target=do_remap) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(set(results)), 1, "All threads should produce the same UID")

    def test_media_storage_sop_instance_uid_remapped(self):
        ds = DicomDataset(
            {
                Tag.SOPInstanceUID: "1.2.3",
                Tag.MediaStorageSOPInstanceUID: "1.2.3",
            }
        )
        from dicomforge.anonymize import AnonymizationPlan

        AnonymizationPlan.starter_profile().apply(ds)
        remapped_sop = str(ds.get(Tag.SOPInstanceUID) or "")
        remapped_media = str(ds.get(Tag.MediaStorageSOPInstanceUID) or "")
        self.assertTrue(remapped_sop.startswith("2.25."))
        self.assertTrue(remapped_media.startswith("2.25."))
        self.assertEqual(
            remapped_sop,
            remapped_media,
            "SOPInstanceUID and MediaStorageSOPInstanceUID should remap to the same value",
        )


class ValidateForSopClassTests(unittest.TestCase):
    """Tests for validate_for_sop_class() IOD profile checks."""

    def _ct_dataset(self, **overrides) -> DicomDataset:
        """Minimal complete CT Image Storage dataset."""
        import numpy as np
        base = {
            # SOP Common
            Tag.SOPClassUID: "1.2.840.10008.5.1.4.1.1.2",
            Tag.SOPInstanceUID: "1.2.3.4.5",
            Tag.StudyInstanceUID: "1.2.3",
            Tag.SeriesInstanceUID: "1.2.3.4",
            # Patient
            Tag.PatientName: "Test",
            Tag.PatientID: "001",
            Tag.StudyDate: "20260101",
            Tag.StudyTime: "120000",
            Tag.StudyID: "1",
            Tag.AccessionNumber: "ACC001",
            Tag.SeriesNumber: 1,
            Tag.InstanceNumber: 1,
            # Series
            Tag.Modality: "CT",
            # Image Pixel
            Tag.SamplesPerPixel: 1,
            Tag.PhotometricInterpretation: "MONOCHROME2",
            Tag.Rows: 4,
            Tag.Columns: 4,
            Tag.BitsAllocated: 16,
            Tag.BitsStored: 16,
            Tag.HighBit: 15,
            Tag.PixelRepresentation: 0,
            Tag.PixelData: b"\x00" * 32,
            # CT Image Module
            Tag.ImageType: "ORIGINAL\\PRIMARY\\AXIAL",
            Tag.RescaleIntercept: -1024.0,
            Tag.RescaleSlope: 1.0,
            Tag.KVP: "120",
            Tag.AcquisitionNumber: 1,
        }
        base.update(overrides)
        return DicomDataset(base)

    def _mr_dataset(self, **overrides) -> DicomDataset:
        """Minimal complete MR Image Storage dataset."""
        base = {
            Tag.SOPClassUID: "1.2.840.10008.5.1.4.1.1.4",
            Tag.SOPInstanceUID: "1.2.3.4.5",
            Tag.StudyInstanceUID: "1.2.3",
            Tag.SeriesInstanceUID: "1.2.3.4",
            Tag.PatientName: "Test",
            Tag.PatientID: "001",
            Tag.StudyDate: "20260101",
            Tag.StudyTime: "120000",
            Tag.StudyID: "1",
            Tag.AccessionNumber: "ACC001",
            Tag.SeriesNumber: 1,
            Tag.InstanceNumber: 1,
            Tag.Modality: "MR",
            Tag.SamplesPerPixel: 1,
            Tag.PhotometricInterpretation: "MONOCHROME2",
            Tag.Rows: 4,
            Tag.Columns: 4,
            Tag.BitsAllocated: 16,
            Tag.BitsStored: 16,
            Tag.HighBit: 15,
            Tag.PixelRepresentation: 0,
            Tag.PixelData: b"\x00" * 32,
            Tag.ImageType: "ORIGINAL\\PRIMARY",
            Tag.ScanningSequence: "SE",
            Tag.SequenceVariant: "NONE",
        }
        base.update(overrides)
        return DicomDataset(base)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_complete_ct_dataset_has_no_issues(self):
        self.assertEqual(validate_for_sop_class(self._ct_dataset()), [])

    def test_complete_mr_dataset_has_no_issues(self):
        self.assertEqual(validate_for_sop_class(self._mr_dataset()), [])

    def test_sop_class_uid_can_be_overridden(self):
        # Pass CT UID explicitly; dataset already has it too
        issues = validate_for_sop_class(
            self._ct_dataset(),
            sop_class_uid="1.2.840.10008.5.1.4.1.1.2",
        )
        self.assertEqual(issues, [])

    # ------------------------------------------------------------------
    # Type 1 errors
    # ------------------------------------------------------------------

    def test_missing_type1_tag_reported_as_error(self):
        ds = self._ct_dataset()
        del ds[Tag.RescaleSlope]
        issues = validate_for_sop_class(ds)
        self.assertTrue(any("[error]" in i and "RescaleSlope" in i for i in issues))

    def test_empty_type1_tag_reported_as_error(self):
        ds = self._ct_dataset()
        ds.set(Tag.ImageType, "")
        issues = validate_for_sop_class(ds)
        self.assertTrue(any("[error]" in i and "ImageType" in i for i in issues))

    def test_missing_mr_scanning_sequence_is_error(self):
        ds = self._mr_dataset()
        del ds[Tag.ScanningSequence]
        issues = validate_for_sop_class(ds)
        self.assertTrue(any("[error]" in i and "ScanningSequence" in i for i in issues))

    def test_missing_mr_sequence_variant_is_error(self):
        ds = self._mr_dataset()
        del ds[Tag.SequenceVariant]
        issues = validate_for_sop_class(ds)
        self.assertTrue(any("[error]" in i and "SequenceVariant" in i for i in issues))

    # ------------------------------------------------------------------
    # Type 2 warnings
    # ------------------------------------------------------------------

    def test_absent_type2_tag_reported_as_warning(self):
        ds = self._ct_dataset()
        del ds[Tag.StudyDate]
        issues = validate_for_sop_class(ds)
        self.assertTrue(any("[warning]" in i and "StudyDate" in i for i in issues))

    def test_empty_type2_tag_is_not_a_warning(self):
        # Type 2 tags may be empty — only absence triggers a warning
        ds = self._ct_dataset()
        ds.set(Tag.StudyDate, "")
        issues = validate_for_sop_class(ds)
        self.assertFalse(any("StudyDate" in i for i in issues))

    # ------------------------------------------------------------------
    # Unknown / missing SOP class
    # ------------------------------------------------------------------

    def test_unknown_sop_class_returns_informational_warning(self):
        ds = self._ct_dataset()
        ds.set(Tag.SOPClassUID, "9.9.9.9.9")
        issues = validate_for_sop_class(ds)
        self.assertEqual(len(issues), 1)
        self.assertIn("[warning]", issues[0])

    def test_missing_sop_class_returns_error(self):
        ds = DicomDataset()
        issues = validate_for_sop_class(ds)
        self.assertEqual(len(issues), 1)
        self.assertIn("[error]", issues[0])
        self.assertIn("SOPClassUID", issues[0])

    def test_explicit_unknown_uid_override_returns_warning(self):
        issues = validate_for_sop_class(self._ct_dataset(), sop_class_uid="9.9.9.9")
        self.assertEqual(len(issues), 1)
        self.assertIn("[warning]", issues[0])

    # ------------------------------------------------------------------
    # Multiple issues at once
    # ------------------------------------------------------------------

    def test_multiple_missing_tags_all_reported(self):
        ds = self._ct_dataset()
        del ds[Tag.RescaleSlope]
        del ds[Tag.RescaleIntercept]
        del ds[Tag.StudyDate]
        issues = validate_for_sop_class(ds)
        labels = " ".join(issues)
        self.assertIn("RescaleSlope", labels)
        self.assertIn("RescaleIntercept", labels)
        self.assertIn("StudyDate", labels)

    # ------------------------------------------------------------------
    # Secondary Capture — no pixel requirements
    # ------------------------------------------------------------------

    def test_secondary_capture_no_pixel_requirement(self):
        ds = DicomDataset({
            Tag.SOPClassUID: "1.2.840.10008.5.1.4.1.1.7",
            Tag.SOPInstanceUID: "1.2.3.4.5",
            Tag.StudyInstanceUID: "1.2.3",
            Tag.SeriesInstanceUID: "1.2.3.4",
            Tag.PatientName: "Test",
            Tag.PatientID: "001",
            Tag.StudyDate: "20260101",
            Tag.StudyTime: "120000",
            Tag.StudyID: "1",
            Tag.AccessionNumber: "",
            Tag.SeriesNumber: 1,
            Tag.InstanceNumber: 1,
        })
        issues = validate_for_sop_class(ds)
        # No pixel tags set — must have no errors (only possible warnings for empty Type2)
        error_issues = [i for i in issues if "[error]" in i]
        self.assertEqual(error_issues, [])


if __name__ == "__main__":
    unittest.main()
