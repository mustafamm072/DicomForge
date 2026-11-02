"""Tests for the dependency-free DICOM Part 10 reader/writer."""

import importlib.util
import os
import tempfile
import unittest

from dicomforge import io, part10
from dicomforge.charset import PersonName
from dicomforge.dataset import DicomDataset
from dicomforge.errors import CharacterSetError, DicomValidationError
from dicomforge.part10 import _decode_at, _decode_numbers, _encode_at, _encode_numbers
from dicomforge.tags import Tag
from dicomforge.uids import SopClassUID, TransferSyntaxUID

_HAS_PYDICOM = importlib.util.find_spec("pydicom") is not None

_UNCOMPRESSED = (
    TransferSyntaxUID.ExplicitVRLittleEndian,
    TransferSyntaxUID.ImplicitVRLittleEndian,
    TransferSyntaxUID.ExplicitVRBigEndian,
    TransferSyntaxUID.DeflatedExplicitVRLittleEndian,
)


def _sample_dataset():
    inner = DicomDataset(
        {
            Tag.ReferencedSOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
            Tag.ReferencedSOPInstanceUID: "1.2.3.4",
        }
    )
    return DicomDataset(
        {
            Tag.SpecificCharacterSet: "ISO_IR 192",
            Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
            Tag.SOPInstanceUID: "1.2.3.4.5",
            Tag.PatientName: PersonName("山田", "太郎"),
            Tag.PatientID: "ID-007",
            Tag.Modality: "CT",
            Tag.Rows: 4,
            Tag.Columns: 2,
            Tag.BitsAllocated: 16,
            Tag.BitsStored: 16,
            Tag.HighBit: 15,
            Tag.PixelRepresentation: 0,
            Tag.SamplesPerPixel: 1,
            Tag.PhotometricInterpretation: "MONOCHROME2",
            Tag.PixelSpacing: [0.5, 0.5],
            Tag.WindowCenter: 40.0,
            Tag.InstanceNumber: 7,
            Tag.ImageType: ["ORIGINAL", "PRIMARY"],
            Tag.ReferencedStudySequence: [inner],
            Tag.PixelData: bytes(range(16)),
        }
    )


class RoundTripTests(unittest.TestCase):
    def test_round_trip_all_uncompressed_syntaxes(self):
        for ts in _UNCOMPRESSED:
            with self.subTest(transfer_syntax=ts):
                blob = part10.dumps(_sample_dataset(), transfer_syntax=ts)
                out = part10.loads(blob)
                self.assertEqual(out.get(Tag.PatientID), "ID-007")
                self.assertEqual(out.get(Tag.Rows), 4)
                self.assertEqual(out.get(Tag.Columns), 2)
                self.assertEqual(out.get(Tag.PixelSpacing), [0.5, 0.5])
                self.assertEqual(out.get(Tag.ImageType), ["ORIGINAL", "PRIMARY"])
                self.assertEqual(out.get(Tag.InstanceNumber), 7)
                self.assertEqual(out.get(Tag.WindowCenter), 40.0)
                self.assertEqual(out.get(Tag.PixelData), (bytes(v ^ 1 for v in range(16))
                    if ts == TransferSyntaxUID.ExplicitVRBigEndian else bytes(range(16))))
                self.assertEqual(str(out.get(Tag.PatientName)), "山田^太郎")
                self.assertEqual(out.get(Tag.TransferSyntaxUID), ts)

    def test_round_trip_preserves_nested_sequence(self):
        blob = part10.dumps(_sample_dataset())
        out = part10.loads(blob)
        seq = out.get(Tag.ReferencedStudySequence)
        self.assertIsInstance(seq, list)
        self.assertEqual(len(seq), 1)
        self.assertEqual(seq[0].get(Tag.ReferencedSOPInstanceUID), "1.2.3.4")

    def test_deeply_nested_sequences(self):
        leaf = DicomDataset({Tag.PatientID: "leaf"})
        middle = DicomDataset(
            {
                Tag.SOPClassUID: "1.2",
                Tag.SOPInstanceUID: "1.2.3",
                Tag.ReferencedSeriesSequence: [leaf],
            }
        )
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.ReferencedStudySequence: [middle],
            }
        )
        out = part10.loads(part10.dumps(ds))
        nested = out.get(Tag.ReferencedStudySequence)[0]
        self.assertEqual(
            nested.get(Tag.ReferencedSeriesSequence)[0].get(Tag.PatientID), "leaf"
        )

    def test_empty_sequence_round_trips_to_empty_list(self):
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.ReferencedStudySequence: [],
            }
        )
        out = part10.loads(part10.dumps(ds))
        self.assertEqual(out.get(Tag.ReferencedStudySequence), [])

    def test_stop_before_pixels(self):
        blob = part10.dumps(_sample_dataset())
        out = part10.loads(blob, stop_before_pixels=True)
        self.assertIsNone(out.get(Tag.PixelData))
        self.assertEqual(out.get(Tag.Rows), 4)

    def test_empty_string_round_trips(self):
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.StudyDescription: "",
            }
        )
        out = part10.loads(part10.dumps(ds))
        self.assertEqual(out.get(Tag.StudyDescription), "")

    def test_private_tag_round_trips(self):
        # Bytes preserved exactly across every transfer syntax; str (VR UN) is
        # written as opaque UTF-8 bytes instead of failing the write.
        for ts in _UNCOMPRESSED:
            with self.subTest(transfer_syntax=ts):
                ds = DicomDataset(
                    {
                        Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                        Tag.SOPInstanceUID: "1.2.3.4.5",
                        (0x0011, 0x1002): b"\x01\x02\x03\x04",
                    }
                )
                out = part10.loads(part10.dumps(ds, transfer_syntax=ts))
                self.assertEqual(out.get((0x0011, 0x1002)), b"\x01\x02\x03\x04")

    def test_private_string_tag_written_as_bytes(self):
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                (0x0011, 0x1001): "vendorstring!!",
            }
        )
        out = part10.loads(part10.dumps(ds))
        self.assertEqual(out.get((0x0011, 0x1001)), b"vendorstring!!")


class FileFormatTests(unittest.TestCase):
    def test_writes_preamble_and_magic(self):
        blob = part10.dumps(_sample_dataset())
        self.assertEqual(blob[:128], b"\x00" * 128)
        self.assertEqual(blob[128:132], b"DICM")

    def test_file_meta_carries_required_uids(self):
        out = part10.loads(part10.dumps(_sample_dataset()))
        # MediaStorage* falls back to the SOP identity of the dataset.
        self.assertEqual(
            out.get(Tag.MediaStorageSOPClassUID),
            SopClassUID.SecondaryCaptureImageStorage,
        )
        self.assertEqual(out.get(Tag.MediaStorageSOPInstanceUID), "1.2.3.4.5")
        self.assertEqual(out.get(Tag.ImplementationClassUID).startswith("2.25."), True)

    def test_missing_sop_identity_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "File Meta Information"):
            part10.dumps(DicomDataset({Tag.PatientName: "Ada"}))

    def test_missing_magic_without_force_raises(self):
        with self.assertRaisesRegex(DicomValidationError, "DICM"):
            part10.loads(b"not a dicom file at all")

    def test_encapsulated_write_frames_compressed_fragments(self):
        # Since 0.11 the native writer frames already-compressed PixelData as an
        # undefined-length fragment sequence instead of rejecting the syntax.
        ds = _sample_dataset()
        ds[Tag.TransferSyntaxUID] = TransferSyntaxUID.JPEGBaselineProcess1
        out = part10.loads(
            part10.dumps(ds, transfer_syntax=TransferSyntaxUID.JPEGBaselineProcess1)
        )
        self.assertEqual(
            out.get(Tag.TransferSyntaxUID), TransferSyntaxUID.JPEGBaselineProcess1
        )
        self.assertEqual(out.get(Tag.PixelData), ds.get(Tag.PixelData))

    def test_encapsulated_write_rejects_non_fragment_value(self):
        ds = _sample_dataset()
        ds.set(Tag.PixelData, 12345)
        ds[Tag.TransferSyntaxUID] = TransferSyntaxUID.JPEGBaselineProcess1
        with self.assertRaisesRegex(DicomValidationError, "EncapsulatedPixelData"):
            part10.dumps(ds, transfer_syntax=TransferSyntaxUID.JPEGBaselineProcess1)

    def test_bare_dataset_force_round_trip(self):
        for ts in (
            TransferSyntaxUID.ExplicitVRLittleEndian,
            TransferSyntaxUID.ImplicitVRLittleEndian,
        ):
            with self.subTest(transfer_syntax=ts):
                ds = DicomDataset(
                    {
                        Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                        Tag.SOPInstanceUID: "1.2.3.4.5",
                        Tag.PatientID: "BARE-1",
                        Tag.Rows: 12,
                    }
                )
                blob = part10.dumps(ds, transfer_syntax=ts, ensure_file_meta=False)
                self.assertNotEqual(blob[128:132], b"DICM")
                out = part10.loads(blob, force=True)
                self.assertEqual(out.get(Tag.PatientID), "BARE-1")
                self.assertEqual(out.get(Tag.Rows), 12)

    def test_bare_dataset_rejects_big_endian(self):
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.PatientID: "BARE-BE",
            }
        )
        with self.assertRaisesRegex(DicomValidationError, "cannot be auto-detected"):
            part10.dumps(
                ds,
                transfer_syntax=TransferSyntaxUID.ExplicitVRBigEndian,
                ensure_file_meta=False,
            )

    def test_bare_dataset_rejects_deflated(self):
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.PatientID: "BARE-DEF",
            }
        )
        with self.assertRaisesRegex(DicomValidationError, "cannot be auto-detected"):
            part10.dumps(
                ds,
                transfer_syntax=TransferSyntaxUID.DeflatedExplicitVRLittleEndian,
                ensure_file_meta=False,
            )


class CharsetTests(unittest.TestCase):
    def test_utf8_person_name_round_trips(self):
        ds = DicomDataset(
            {
                Tag.SpecificCharacterSet: "ISO_IR 192",
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.PatientName: "Müller^Anna",
            }
        )
        out = part10.loads(part10.dumps(ds))
        self.assertEqual(str(out.get(Tag.PatientName)), "Müller^Anna")

    def test_non_ascii_without_declared_charset_rejected(self):
        ds = DicomDataset(
            {
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.PatientName: "山田^太郎",
            }
        )
        with self.assertRaises(CharacterSetError):
            part10.dumps(ds)

    def test_ascii_passes_with_unsupported_declared_charset(self):
        ds = DicomDataset(
            {
                Tag.SpecificCharacterSet: "ISO_IR 13",
                Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
                Tag.SOPInstanceUID: "1.2.3.4.5",
                Tag.PatientName: "Yamada^Taro",
            }
        )
        out = part10.loads(part10.dumps(ds))
        self.assertEqual(str(out.get(Tag.PatientName)), "Yamada^Taro")


class NumericCodecTests(unittest.TestCase):
    def test_numeric_vr_round_trip(self):
        cases = {
            "US": (65535, [1, 2, 3]),
            "SS": (-1, [-2, 7]),
            "UL": (4294967295, [0, 10]),
            "SL": (-2147483648, [5, -5]),
            "FL": (1.5, [0.25, -0.5]),
            "FD": (3.141592653589793, [1.0, 2.0]),
            "SV": (-9, [9, -3]),
            "UV": (18446744073709551615, [1, 2]),
        }
        for vr, (scalar, vector) in cases.items():
            for endian in ("<", ">"):
                with self.subTest(vr=vr, endian=endian):
                    raw = _encode_numbers(vr, scalar, endian)
                    self.assertEqual(_decode_numbers(vr, raw, endian), scalar)
                    raw = _encode_numbers(vr, vector, endian)
                    self.assertEqual(_decode_numbers(vr, raw, endian), vector)

    def test_at_codec_round_trip(self):
        for endian in ("<", ">"):
            raw = _encode_at(Tag(0x0010, 0x0010), endian)
            self.assertEqual(_decode_at(raw, endian), Tag(0x0010, 0x0010))
            raw = _encode_at([Tag(0x0008, 0x0018), Tag(0x0020, 0x000D)], endian)
            self.assertEqual(
                _decode_at(raw, endian), [Tag(0x0008, 0x0018), Tag(0x0020, 0x000D)]
            )


class IoBackendTests(unittest.TestCase):
    def test_io_native_backend_round_trip(self):
        path = tempfile.mktemp(suffix=".dcm")
        try:
            io.write(path, _sample_dataset(), backend="native")
            out = io.read(path, backend="native")
        finally:
            if os.path.exists(path):
                os.remove(path)
        self.assertEqual(out.get(Tag.PatientID), "ID-007")
        self.assertEqual(out.get(Tag.Rows), 4)
        self.assertEqual(str(out.get(Tag.PatientName)), "山田^太郎")

    def test_io_native_backend_with_transfer_syntax(self):
        path = tempfile.mktemp(suffix=".dcm")
        try:
            io.write(
                path,
                _sample_dataset(),
                backend="native",
                transfer_syntax=TransferSyntaxUID.ImplicitVRLittleEndian,
            )
            out = io.read(path, backend="native")
        finally:
            if os.path.exists(path):
                os.remove(path)
        self.assertEqual(
            out.get(Tag.TransferSyntaxUID), TransferSyntaxUID.ImplicitVRLittleEndian
        )

    def test_invalid_backend_raises(self):
        with self.assertRaises(ValueError):
            io.read("x.dcm", backend="bogus")

    def test_native_backend_rejects_template(self):
        with self.assertRaises(DicomValidationError):
            io.write("x.dcm", _sample_dataset(), backend="native", template=object())


@unittest.skipUnless(_HAS_PYDICOM, "pydicom not installed")
class PydicomCrossCompatTests(unittest.TestCase):
    def test_pydicom_reads_native_written(self):
        import pydicom

        for ts in _UNCOMPRESSED:
            with self.subTest(transfer_syntax=ts):
                path = tempfile.mktemp(suffix=".dcm")
                try:
                    part10.write_file(path, _sample_dataset(), transfer_syntax=ts)
                    pd = pydicom.dcmread(path)
                finally:
                    if os.path.exists(path):
                        os.remove(path)
                self.assertEqual(pd.PatientID, "ID-007")
                self.assertEqual(pd.Rows, 4)
                self.assertEqual(str(pd.PatientName), "山田^太郎")
                self.assertEqual(pd.file_meta.TransferSyntaxUID, ts)
                self.assertEqual(bytes(pd.PixelData), (bytes(v ^ 1 for v in range(16))
                    if ts == TransferSyntaxUID.ExplicitVRBigEndian else bytes(range(16))))
                # The nested sequence must survive the round-trip into pydicom.
                self.assertEqual(
                    pd.ReferencedStudySequence[0].ReferencedSOPInstanceUID, "1.2.3.4"
                )

    def test_native_reads_pydicom_written(self):
        import pydicom

        for ts in (
            TransferSyntaxUID.ExplicitVRLittleEndian,
            TransferSyntaxUID.ImplicitVRLittleEndian,
            TransferSyntaxUID.ExplicitVRBigEndian,
        ):
            with self.subTest(transfer_syntax=ts):
                path = tempfile.mktemp(suffix=".dcm")
                try:
                    fm = pydicom.dataset.FileMetaDataset()
                    fm.MediaStorageSOPClassUID = SopClassUID.SecondaryCaptureImageStorage
                    fm.MediaStorageSOPInstanceUID = "1.2.3.4.5"
                    fm.TransferSyntaxUID = ts
                    d = pydicom.Dataset()
                    d.file_meta = fm
                    d.preamble = b"\x00" * 128
                    d.is_little_endian = ts != TransferSyntaxUID.ExplicitVRBigEndian
                    d.is_implicit_VR = ts == TransferSyntaxUID.ImplicitVRLittleEndian
                    d.PatientName = "Doe^Jane"
                    d.PatientID = "ID-009"
                    d.Rows = 8
                    d.PixelSpacing = [1.25, 1.25]
                    pydicom.dcmwrite(path, d)
                    out = part10.read_file(path)
                finally:
                    if os.path.exists(path):
                        os.remove(path)
                self.assertEqual(out.get(Tag.PatientID), "ID-009")
                self.assertEqual(out.get(Tag.Rows), 8)
                self.assertEqual(str(out.get(Tag.PatientName)), "Doe^Jane")
                self.assertEqual(out.get(Tag.PixelSpacing), [1.25, 1.25])


if __name__ == "__main__":
    unittest.main()
