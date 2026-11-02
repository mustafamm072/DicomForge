"""Regressions for the adoption-hardening follow-up review."""

import importlib.util
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from dicomforge import AnonymizationAction, AnonymizationPlan, DicomDataset, Rule, Tag, part10
from dicomforge.anonymize import _shift_date_value
from dicomforge.api import DicomFile
from dicomforge.collection import ReleasePolicy, release_collection
from dicomforge.errors import DicomValidationError
from dicomforge.io import read, write
from dicomforge.uids import TransferSyntaxUID as TS
from tests.test_hardening import image


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_loading_pixels_preserves_metadata_deletions_and_edits_on_disk(self):
        nested = DicomDataset({'PatientAddress': 'NESTED-SYNTHETIC', (0x0011, 0x1010): b'private'})
        source = image(PatientAddress='SYNTHETIC-ADDRESS', ReferencedStudySequence=[nested],
                       RescaleSlope='1.0000000000')
        source.set((0x0011, 0x1010), b'private')
        source.set((0xFFFC, 0xFFFC), b'\x00\x00', vr='OB')
        path = self.root/'source.dcm'
        write(path, source)
        file = DicomFile(path, stop_before_pixels=True)
        metadata = file.dataset
        del metadata[Tag.PatientAddress]
        metadata.remove_private_tags()
        del metadata[Tag.ReferencedStudySequence][0][Tag.PatientAddress]
        metadata[Tag.PatientName] = 'Edited^Synthetic'
        metadata[Tag.SeriesDescription] = 'Added series description'

        full = file.load_pixels()
        self.assertNotIn(Tag.PatientAddress, full)
        self.assertNotIn((0x0011, 0x1010), full)
        self.assertNotIn(Tag.PatientAddress, full[Tag.ReferencedStudySequence][0])
        self.assertNotIn((0x0011, 0x1010), full[Tag.ReferencedStudySequence][0])
        self.assertEqual(full[Tag.PixelData], source[Tag.PixelData])
        self.assertEqual(full[(0xFFFC, 0xFFFC)], b'\x00\x00')
        self.assertIs(file.load_pixels(), full)

        output = self.root/'output.dcm'
        file.save(output)
        restored = read(output)
        self.assertNotIn(Tag.PatientAddress, restored)
        self.assertNotIn((0x0011, 0x1010), restored)
        self.assertNotIn(Tag.PatientAddress, restored[Tag.ReferencedStudySequence][0])
        self.assertEqual(restored[Tag.PatientName], 'Edited^Synthetic')
        self.assertEqual(restored[Tag.SeriesDescription], 'Added series description')
        self.assertIn(b'1.0000000000', output.read_bytes())

    def test_loading_pixels_preserves_deletion_of_an_entire_sequence(self):
        path = self.root/'sequence.dcm'
        write(path, image(ReferencedStudySequence=[DicomDataset({'PatientAddress': 'SYNTHETIC'})]))
        file = DicomFile(path, stop_before_pixels=True)
        file.dataset.pop(Tag.ReferencedStudySequence)
        self.assertNotIn(Tag.ReferencedStudySequence, file.load_pixels())

    def test_implicit_signed_values_survive_an_explicit_rewrite(self):
        values = {'PixelPaddingValue': -1, 'PixelPaddingRangeLimit': -2,
                  'ZeroVelocityPixelValue': -5, 'SmallestImagePixelValue': -1024}
        source = image(PixelRepresentation=1, **values)
        restored = part10.loads(part10.dumps(source, transfer_syntax=TS.ImplicitVRLittleEndian))
        rewritten = part10.loads(part10.dumps(restored, transfer_syntax=TS.ExplicitVRLittleEndian))
        for keyword, expected in values.items():
            with self.subTest(tag=keyword):
                self.assertEqual(restored[keyword], expected)
                self.assertEqual(restored.vr(keyword), 'SS')
                self.assertEqual(rewritten[keyword], expected)
                self.assertEqual(rewritten.vr(keyword), 'SS')

    def test_nested_implicit_values_inherit_context_and_respect_local_override(self):
        inherited = DicomDataset()
        inherited.set('PixelPaddingValue', -1, vr='SS')
        unsigned = DicomDataset({'PixelRepresentation': 0, 'PixelPaddingValue': 65535})
        source = image(PixelRepresentation=1, ReferencedStudySequence=[inherited, unsigned])
        restored = part10.loads(part10.dumps(source, transfer_syntax=TS.ImplicitVRLittleEndian))
        first, second = restored[Tag.ReferencedStudySequence]
        self.assertEqual(first['PixelPaddingValue'], -1)
        self.assertEqual(first.vr('PixelPaddingValue'), 'SS')
        self.assertEqual(second['PixelPaddingValue'], 65535)
        self.assertEqual(second.vr('PixelPaddingValue'), 'US')

    def test_unsigned_implicit_and_explicit_declared_vrs_are_unchanged(self):
        source = image(PixelPaddingValue=65535)
        restored = part10.loads(part10.dumps(source, transfer_syntax=TS.ImplicitVRLittleEndian))
        self.assertEqual(restored['PixelPaddingValue'], 65535)
        self.assertEqual(restored.vr('PixelPaddingValue'), 'US')
        source[Tag.PixelRepresentation] = 1
        source.set('PixelPaddingValue', 65535, vr='US')
        explicit = part10.loads(part10.dumps(source))
        self.assertEqual(explicit['PixelPaddingValue'], 65535)
        self.assertEqual(explicit.vr('PixelPaddingValue'), 'US')

    def test_signed_lut_descriptor_retains_unsigned_count_during_resolution(self):
        source = image(PixelRepresentation=1, LUTDescriptor=[65535, -1, 16])
        for syntax in (TS.ImplicitVRLittleEndian, TS.ExplicitVRLittleEndian, TS.ExplicitVRBigEndian):
            with self.subTest(syntax=syntax):
                restored = part10.loads(part10.dumps(source, transfer_syntax=syntax))
                self.assertEqual(restored['LUTDescriptor'], [65535, -1, 16])
                self.assertEqual(restored.vr('LUTDescriptor'), 'SS')

    @unittest.skipUnless(importlib.util.find_spec('pydicom'), 'optional pydicom')
    def test_pydicom_agrees_with_signed_implicit_and_explicit_output(self):
        import pydicom
        blob = part10.dumps(image(PixelRepresentation=1, PixelPaddingValue=-1),
                             transfer_syntax=TS.ImplicitVRLittleEndian)
        self.assertEqual(pydicom.dcmread(io.BytesIO(blob)).PixelPaddingValue, -1)
        rewritten = part10.dumps(part10.loads(blob), transfer_syntax=TS.ExplicitVRLittleEndian)
        raw = pydicom.dcmread(io.BytesIO(rewritten))
        self.assertEqual(raw.PixelPaddingValue, -1)
        self.assertEqual(raw['PixelPaddingValue'].VR, 'SS')

    def test_shift_date_lists_and_tuples_preserve_shape_and_datetime_suffixes(self):
        for container in (list, tuple):
            dates = container(['20250101', '20250201'])
            expected = container(['20250103', '20250203'])
            self.assertEqual(_shift_date_value(dates, 2), expected)
            dataset = DicomDataset({'DateOfLastCalibration': dates})
            AnonymizationPlan([Rule(Tag.parse('DateOfLastCalibration'),
                                    AnonymizationAction.SHIFT_DATE, 2)]).apply(dataset)
            self.assertEqual(dataset['DateOfLastCalibration'], expected)
            self.assertIsInstance(dataset['DateOfLastCalibration'], container)
        self.assertEqual(_shift_date_value(['20250101120000+0530', '20250201120000.123'], 2),
                         ['20250103120000+0530', '20250203120000.123'])

    def test_longitudinal_release_shifts_every_date_value_in_saved_output(self):
        policy = ReleasePolicy('trial', b'k'*32, longitudinal_dates=True, pixels_reviewed=True)
        for container in (list, tuple):
            dates = container(['20250101', '20250201'])
            source = image(DateOfLastCalibration=dates)
            shifted = policy.transform(source)
            delta = datetime.strptime(shifted[Tag.StudyDate], '%Y%m%d') - datetime(2026, 1, 1)
            self.assertNotEqual(delta.days, 0)
            for before, after in zip(dates, shifted['DateOfLastCalibration']):
                self.assertEqual(datetime.strptime(after, '%Y%m%d') - datetime.strptime(before, '%Y%m%d'), delta)
            self.assertIsInstance(shifted['DateOfLastCalibration'], container)
            self.assertEqual(source['DateOfLastCalibration'], dates)
        (self.root/'input').mkdir()
        path = self.root/'input'/'source.dcm'
        write(path, image(DateOfLastCalibration=['20250101', '20250201']))
        manifest = release_collection([path], self.root/'release', policy)
        saved = read(self.root/'release'/manifest['instances'][0]['file'])
        self.assertEqual(saved['DateOfLastCalibration'], list(shifted['DateOfLastCalibration']))
        self.assertEqual(saved[Tag.LongitudinalTemporalInformationModified], 'MODIFIED')

    def test_longitudinal_release_still_rejects_partial_dates_in_collections(self):
        policy = ReleasePolicy('trial', b'k'*32, longitudinal_dates=True, pixels_reviewed=True)
        for dates in (['20250101', '2025'], ('20250101', 'not-a-date')):
            with self.assertRaises(DicomValidationError):
                policy.transform(image(DateOfLastCalibration=dates))
