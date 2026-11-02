"""Public I/O tests use real files rather than fake writer implementations."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dicomforge import DicomDataset, DicomValidationError, Tag
from dicomforge.charset import PersonName
from dicomforge.errors import CharacterSetError
from dicomforge.io import read, write
from dicomforge.uids import SopClassUID, TransferSyntaxUID


class IoTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'image.dcm'

    def dataset(self, **values):
        ds = DicomDataset({Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                           Tag.SOPInstanceUID: '1.2.3.4'})
        for tag, value in values.items():
            ds[tag] = value
        return ds

    def test_read_preserves_file_meta_transfer_syntax(self):
        write(self.path, self.dataset(Rows=2))
        ds = read(self.path)
        self.assertEqual(ds[Tag.TransferSyntaxUID], TransferSyntaxUID.ExplicitVRLittleEndian)
        self.assertEqual(ds[Tag.Rows], 2)

    def test_auto_does_not_import_optional_backend(self):
        with patch.dict('sys.modules', {'pydicom': None}):
            write(self.path, self.dataset(PatientName='Synthetic'))
            self.assertEqual(read(self.path)[Tag.PatientName], 'Synthetic')

    def test_write_uses_standard_vr_for_known_tags(self):
        write(self.path, self.dataset(PatientName='Synthetic', BitsAllocated=16,
                                      PixelData=b'\x00\x01'))
        restored = read(self.path)
        self.assertEqual(restored.vr(Tag.PatientName), 'PN')
        self.assertEqual(restored.vr(Tag.SOPInstanceUID), 'UI')
        self.assertEqual(restored.vr(Tag.PixelData), 'OW')

    def test_write_requires_sop_identity_for_file_meta(self):
        with self.assertRaisesRegex(DicomValidationError, 'File Meta Information'):
            write(self.path, DicomDataset({Tag.PatientName: 'Synthetic'}))
        self.assertFalse(self.path.exists())

    def test_write_propagates_specific_character_set_before_text_values(self):
        write(self.path, self.dataset(SpecificCharacterSet='ISO_IR 192',
                                      PatientName=PersonName('山田', '太郎')))
        self.assertEqual(str(read(self.path)[Tag.PatientName]), '山田^太郎')

    def test_write_accepts_canonical_iso2022_declaration(self):
        terms = ['ISO 2022 IR 6', 'ISO 2022 IR 87']
        write(self.path, self.dataset(SpecificCharacterSet=terms, PatientName='Yamada^Taro'))
        self.assertEqual(read(self.path)[Tag.SpecificCharacterSet], terms)

    def test_write_allows_ascii_text_with_unsupported_declared_charset(self):
        write(self.path, self.dataset(SpecificCharacterSet='ISO_IR 13', PatientName='Yamada^Taro'))
        self.assertEqual(read(self.path)[Tag.PatientName], 'Yamada^Taro')

    def test_write_rejects_non_ascii_text_with_unsupported_declared_charset(self):
        with self.assertRaises(CharacterSetError):
            write(self.path, self.dataset(SpecificCharacterSet='ISO_IR 13', PatientName='ﾔﾏﾀﾞ^ﾀﾛｳ'))

    def test_write_rejects_non_ascii_text_without_declared_charset(self):
        with self.assertRaises(CharacterSetError):
            write(self.path, self.dataset(PatientName='山田^太郎'))
