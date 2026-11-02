"""Research release and real command-line process tests, including clean-core installs."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dicomforge.collection import ReleasePolicy, inspect_collection, release_collection, validate_collection
from dicomforge.dataset import as_dataset
from dicomforge.errors import DicomValidationError
from dicomforge.io import read, write
from dicomforge.tags import Tag
from tests.test_hardening import image


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/'source').mkdir()
        self.paths = []
        for index in range(2):
            path = self.root/'source'/f'SYNTHETIC-source-{index}.dcm'
            write(path, image(index))
            self.paths.append(path)
        self.policy = ReleasePolicy('trial-a', b'k'*32, pixels_reviewed=True)

    def test_inventory_and_geometry_report_has_no_identifiers(self):
        report = inspect_collection(self.paths)
        self.assertEqual(report.status, 'accepted')
        self.assertGreater(report.bytes_on_disk, 0)
        self.assertEqual(report.max_decoded_frame_bytes, 4)
        self.assertNotIn('SYNTHETIC', json.dumps(report.to_dict()))

    def test_duplicate_missing_reference_and_bad_geometry(self):
        ds = image(ReferencedStudySequence=[image(20)])
        ds[Tag.ReferencedStudySequence][0][Tag.ReferencedSOPInstanceUID] = '1.2.99'
        report = validate_collection([ds, ds], require_reference_closure=True)
        codes = {issue.code for issue in report.issues}
        self.assertTrue({'duplicate-instance', 'duplicate-plane', 'missing-reference'}.issubset(codes))
        self.assertEqual(report.status, 'quarantined')
        ds = image(ImageOrientationPatient=[2, 0, 0, 0, 1, 0])
        self.assertEqual(validate_collection([ds]).status, 'needs_review')

    def test_frame_budget_and_multiframe_scope(self):
        self.assertEqual(inspect_collection(self.paths, max_frame_bytes=1).status, 'quarantined')
        self.assertEqual(validate_collection([image(NumberOfFrames=2, PixelData=b'\x00'*8)]).status, 'needs_review')
        with self.assertRaises(DicomValidationError):
            inspect_collection(self.paths, max_input_bytes=1)

    def test_dry_run_does_not_create_output(self):
        destination = self.root/'dry'
        result = release_collection(self.paths, destination, self.policy, dry_run=True)
        self.assertTrue(result['dry_run'])
        self.assertFalse(destination.exists())

    def test_release_is_reproducible_resumable_and_value_free(self):
        first, second = self.root/'first', self.root/'second'
        a = release_collection(self.paths, first, self.policy)
        b = release_collection(self.paths, second, self.policy)
        self.assertEqual(a, b)
        self.assertEqual(release_collection(self.paths, first, self.policy, resume=True), a)
        self.assertTrue(a['completed'])
        self.assertNotIn('SYNTHETIC', json.dumps(a))
        outputs = [read(first/item['file']) for item in a['instances']]
        self.assertEqual(outputs[0][Tag.PatientID], outputs[1][Tag.PatientID])
        self.assertNotEqual(outputs[0][Tag.PatientID], 'ANON')
        self.assertNotEqual(outputs[0][Tag.SOPInstanceUID], outputs[1][Tag.SOPInstanceUID])
        self.assertEqual(outputs[0][Tag.PatientIdentityRemoved], 'YES')
        self.assertEqual(outputs[0][Tag.StudyDate], '')
        self.assertIn(Tag.AccessionNumber, outputs[0])
        self.assertIn(Tag.StudyID, outputs[0])
        with self.assertRaises(FileExistsError):
            release_collection(self.paths, first, self.policy)

    def test_resume_rejects_changed_key_and_corrupt_output(self):
        destination = self.root/'out'
        result = release_collection(self.paths, destination, self.policy)
        with self.assertRaises(DicomValidationError):
            release_collection(self.paths, destination,
                               ReleasePolicy('trial-a', b'x'*32, pixels_reviewed=True), resume=True)
        (destination/result['instances'][0]['file']).write_bytes(b'corrupt')
        with self.assertRaises(DicomValidationError):
            release_collection(self.paths, destination, self.policy, resume=True)

    def test_resume_rejects_added_or_removed_source_instances(self):
        destination = self.root/'same-set'
        release_collection(self.paths, destination, self.policy)
        added = self.root/'source'/'extra.dcm'
        write(added, image(2))
        for paths in (self.paths + [added], self.paths[:1]):
            with self.assertRaises(DicomValidationError):
                release_collection(paths, destination, self.policy, resume=True)

    def test_interrupted_job_resumes_without_overwriting(self):
        from dicomforge import io
        real = io.write
        count = []
        def interrupted(path, ds, **kwargs):
            count.append(path)
            if len(count) == 2:
                raise OSError('synthetic interruption')
            real(path, ds, **kwargs)
        destination = self.root/'interrupted'
        with patch('dicomforge.collection.io.write', side_effect=interrupted):
            with self.assertRaises(OSError):
                release_collection(self.paths, destination, self.policy)
        self.assertEqual(len(list(destination.glob('*.dcm'))), 1)
        result = release_collection(self.paths, destination, self.policy, resume=True)
        self.assertEqual(len(result['instances']), 2)
        self.assertTrue(result['completed'])

    def test_policy_requires_explicit_key_and_pixel_review(self):
        with self.assertRaises(ValueError):
            ReleasePolicy('trial', b'short')
        with self.assertRaises(DicomValidationError):
            ReleasePolicy('trial', b'k'*32).transform(image())

    def test_longitudinal_linkage_shifts_dates_consistently_and_rejects_partial(self):
        policy = ReleasePolicy('trial', b'k'*32, longitudinal_dates=True, pixels_reviewed=True)
        first = policy.transform(image(StudyDate='20260101'))
        second = policy.transform(image(1, StudyDate='20260102'))
        from datetime import datetime
        delta = datetime.strptime(second[Tag.StudyDate], '%Y%m%d') - datetime.strptime(first[Tag.StudyDate], '%Y%m%d')
        self.assertEqual(delta.days, 1)
        self.assertEqual(first[Tag.LongitudinalTemporalInformationModified], 'MODIFIED')
        with self.assertRaises(DicomValidationError):
            policy.transform(image(StudyDate='2026'))

    @unittest.skipUnless(importlib.util.find_spec('pydicom'), 'optional pydicom')
    def test_readonly_pydicom_validation_does_not_copy_pixels(self):
        from dicomforge.adapt import to_pydicom
        raw = to_pydicom(image())
        view = as_dataset(raw)
        self.assertIs(view[Tag.PixelData], raw.PixelData)
        self.assertEqual(validate_collection([raw]).status, 'accepted')
        with self.assertRaises(TypeError):
            view[Tag.PatientID] = 'forbidden'

    def cli(self, *args):
        environment = dict(os.environ)
        if environment.get('DICOMFORGE_TEST_INSTALLED'):
            environment.pop('PYTHONPATH', None)
        else:
            environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1]/'src')
        return subprocess.run([sys.executable, '-m', 'dicomforge', *map(str, args)],
                              capture_output=True, text=True, env=environment, timeout=20)

    def test_cli_help_version_inventory_validate_and_error_codes(self):
        self.assertEqual(self.cli('--help').returncode, 0)
        self.assertIn('0.12.0', self.cli('--version').stdout)
        for command in ('inventory', 'validate'):
            result = self.cli(command, *self.paths)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'accepted')
            self.assertNotIn('SYNTHETIC', result.stdout)
        missing = self.cli('inventory', self.root/'SYNTHETIC-private.dcm')
        self.assertEqual(missing.returncode, 2)
        self.assertNotIn('SYNTHETIC', missing.stderr)
        rejected = self.cli('validate', self.paths[0], self.paths[0])
        self.assertEqual(rejected.returncode, 1)

    def test_cli_plan_release_resume_and_key_not_printed(self):
        key = self.root/'key'
        key.write_bytes(b'UNIQUE-SECRET-DO-NOT-PRINT-0123456789')
        destination = self.root/'release'
        options = [*self.paths, '--output', destination, '--namespace', 'trial',
                   '--key-file', key, '--pixels-reviewed']
        plan = self.cli('plan', *options)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        self.assertFalse(destination.exists())
        result = self.cli('release', *options)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('UNIQUE-SECRET', result.stdout + result.stderr)
        self.assertEqual(self.cli('release', *options, '--resume').returncode, 0)


if __name__ == '__main__':
    unittest.main()
