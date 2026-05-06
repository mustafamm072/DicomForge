"""Tests for the adopt.py integration adapters."""

import json
import unittest

from dicomforge.adapt import from_json, to_json
from dicomforge.dataset import DicomDataset
from dicomforge.errors import MissingBackendError
from dicomforge.tags import Tag


class JsonAdapterTests(unittest.TestCase):
    def test_roundtrip_simple_tags(self):
        ds = DicomDataset(
            {
                Tag.PatientName: "Ada Lovelace",
                Tag.PatientID: "MRN-001",
                Tag.Modality: "CT",
            }
        )
        serialized = to_json(ds)
        parsed = json.loads(serialized)
        self.assertIn("00100010", parsed)
        self.assertIn("00100020", parsed)

        restored = from_json(serialized)
        self.assertEqual(restored.get(Tag.PatientName), "Ada Lovelace")
        self.assertEqual(restored.get(Tag.PatientID), "MRN-001")
        self.assertEqual(restored.get(Tag.Modality), "CT")

    def test_roundtrip_uid_tags(self):
        ds = DicomDataset(
            {
                Tag.StudyInstanceUID: "1.2.840.10008.5.1",
                Tag.SOPInstanceUID: "1.2.3.4.5",
            }
        )
        restored = from_json(to_json(ds))
        self.assertEqual(restored.get(Tag.StudyInstanceUID), "1.2.840.10008.5.1")

    def test_roundtrip_bytes_value(self):
        payload = b"\x00\x01\x02\x03"
        ds = DicomDataset({Tag.PixelData: payload})
        restored = from_json(to_json(ds))
        self.assertEqual(restored.get(Tag.PixelData), payload)

    def test_from_json_bytes_input(self):
        ds = DicomDataset({Tag.Modality: "MR"})
        serialized_bytes = to_json(ds).encode("utf-8")
        restored = from_json(serialized_bytes)
        self.assertEqual(restored.get(Tag.Modality), "MR")

    def test_to_json_indent(self):
        ds = DicomDataset({Tag.Modality: "CT"})
        pretty = to_json(ds, indent=2)
        self.assertIn("\n", pretty)

    def test_empty_dataset(self):
        ds = DicomDataset()
        restored = from_json(to_json(ds))
        self.assertEqual(len(restored), 0)


class PydicomAdapterTests(unittest.TestCase):
    def _skip_if_no_pydicom(self):
        try:
            import pydicom  # noqa: F401
        except ImportError:
            self.skipTest("pydicom not installed")

    def test_from_pydicom_basic(self):
        self._skip_if_no_pydicom()
        import pydicom

        raw = pydicom.Dataset()
        raw.add_new((0x0010, 0x0010), "PN", "Test Patient")
        raw.add_new((0x0008, 0x0060), "CS", "CT")

        from dicomforge.adapt import from_pydicom

        ds = from_pydicom(raw)
        self.assertEqual(ds.get(Tag.PatientName), "Test Patient")
        self.assertEqual(ds.get(Tag.Modality), "CT")

    def test_to_pydicom_basic(self):
        self._skip_if_no_pydicom()

        from dicomforge.adapt import to_pydicom

        ds = DicomDataset({Tag.PatientName: "Ada", Tag.Modality: "MR"})
        raw = to_pydicom(ds)
        self.assertIsNotNone(raw)

    def test_from_pydicom_with_file_meta(self):
        self._skip_if_no_pydicom()
        import pydicom

        raw = pydicom.Dataset()
        raw.file_meta = pydicom.Dataset()
        raw.file_meta.add_new((0x0002, 0x0010), "UI", "1.2.840.10008.1.2.1")
        raw.add_new((0x0010, 0x0010), "PN", "Meta Patient")

        from dicomforge.adapt import from_pydicom

        ds = from_pydicom(raw)
        self.assertEqual(ds.get(Tag.PatientName), "Meta Patient")
        self.assertEqual(str(ds.get(Tag.TransferSyntaxUID)), "1.2.840.10008.1.2.1")

    def test_to_pydicom_missing_backend_raises(self):
        import sys
        from unittest.mock import patch

        from dicomforge.adapt import to_pydicom

        ds = DicomDataset({Tag.Modality: "CT"})
        with patch.dict(sys.modules, {"pydicom": None}):
            with self.assertRaises(MissingBackendError):
                to_pydicom(ds)


class NumpyAdapterTests(unittest.TestCase):
    def _skip_if_no_numpy(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")

    def test_pixel_array_uint8_monochrome(self):
        self._skip_if_no_numpy()
        import numpy as np

        from dicomforge.adapt import pixel_array
        from dicomforge.uids import TransferSyntaxUID

        rows, cols = 4, 4
        raw_bytes = bytes(range(rows * cols))
        ds = DicomDataset(
            {
                Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
                Tag.Rows: rows,
                Tag.Columns: cols,
                Tag.SamplesPerPixel: 1,
                Tag.BitsAllocated: 8,
                Tag.BitsStored: 8,
                Tag.HighBit: 7,
                Tag.PixelRepresentation: 0,
                Tag.PhotometricInterpretation: "MONOCHROME2",
                Tag.PixelData: raw_bytes,
            }
        )
        arr = pixel_array(ds)
        self.assertEqual(arr.shape, (rows, cols))
        self.assertEqual(arr.dtype, np.uint8)

    def test_pixel_array_uint16(self):
        self._skip_if_no_numpy()
        import numpy as np

        from dicomforge.adapt import pixel_array
        from dicomforge.uids import TransferSyntaxUID

        rows, cols = 2, 2
        values = [100, 200, 300, 400]
        raw_bytes = np.array(values, dtype=np.uint16).tobytes()
        ds = DicomDataset(
            {
                Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
                Tag.Rows: rows,
                Tag.Columns: cols,
                Tag.SamplesPerPixel: 1,
                Tag.BitsAllocated: 16,
                Tag.BitsStored: 16,
                Tag.HighBit: 15,
                Tag.PixelRepresentation: 0,
                Tag.PhotometricInterpretation: "MONOCHROME2",
                Tag.PixelData: raw_bytes,
            }
        )
        arr = pixel_array(ds)
        self.assertEqual(arr.shape, (rows, cols))
        self.assertEqual(arr.dtype, np.uint16)
        self.assertEqual(arr[0, 0], 100)
        self.assertEqual(arr[1, 1], 400)

    def test_pixel_array_with_rescale(self):
        self._skip_if_no_numpy()
        import numpy as np

        from dicomforge.adapt import pixel_array
        from dicomforge.uids import TransferSyntaxUID

        rows, cols = 1, 4
        raw_bytes = np.array([0, 100, 200, 300], dtype=np.uint16).tobytes()
        ds = DicomDataset(
            {
                Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
                Tag.Rows: rows,
                Tag.Columns: cols,
                Tag.SamplesPerPixel: 1,
                Tag.BitsAllocated: 16,
                Tag.BitsStored: 16,
                Tag.HighBit: 15,
                Tag.PixelRepresentation: 0,
                Tag.PhotometricInterpretation: "MONOCHROME2",
                Tag.RescaleSlope: 1.0,
                Tag.RescaleIntercept: -1024.0,
                Tag.PixelData: raw_bytes,
            }
        )
        arr = pixel_array(ds, apply_rescale=True)
        self.assertEqual(arr.dtype, np.float64)
        self.assertAlmostEqual(float(arr[0, 0]), -1024.0)
        self.assertAlmostEqual(float(arr[0, 1]), -924.0)

    def test_pixel_array_missing_numpy_raises(self):
        import sys
        from unittest.mock import patch

        from dicomforge.adapt import pixel_array

        ds = DicomDataset()
        with patch.dict(sys.modules, {"numpy": None}):
            with self.assertRaises(MissingBackendError):
                pixel_array(ds)


if __name__ == "__main__":
    unittest.main()
