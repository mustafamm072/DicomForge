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


class PilAdapterTests(unittest.TestCase):
    def _skip_if_no_pixels(self):
        try:
            import numpy  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            self.skipTest("numpy or Pillow not installed")

    def _make_colour_dataset(self, photometric: str, pixels: "Any") -> DicomDataset:
        import numpy as np
        from dicomforge.uids import TransferSyntaxUID

        rows, cols = pixels.shape[:2]
        return DicomDataset(
            {
                Tag.TransferSyntaxUID: TransferSyntaxUID.ExplicitVRLittleEndian,
                Tag.Rows: rows,
                Tag.Columns: cols,
                Tag.SamplesPerPixel: 3,
                Tag.BitsAllocated: 8,
                Tag.BitsStored: 8,
                Tag.HighBit: 7,
                Tag.PixelRepresentation: 0,
                Tag.PlanarConfiguration: 0,
                Tag.PhotometricInterpretation: photometric,
                Tag.PixelData: pixels.astype(np.uint8).tobytes(),
            }
        )

    def test_rgb_image_returned_unchanged(self):
        self._skip_if_no_pixels()
        import numpy as np
        from PIL import Image

        from dicomforge.adapt import to_pil_image

        # Pure red pixel in RGB
        pixels = np.array([[[255, 0, 0]]], dtype=np.uint8)
        ds = self._make_colour_dataset("RGB", pixels)
        img = to_pil_image(ds, apply_window=False)

        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.mode, "RGB")
        r, g, b = img.getpixel((0, 0))
        self.assertEqual(r, 255)
        self.assertEqual(g, 0)
        self.assertEqual(b, 0)

    def test_ybr_full_converted_to_rgb(self):
        """YBR_FULL white (Y=235, Cb=128, Cr=128) must map to near-white RGB."""
        self._skip_if_no_pixels()
        import numpy as np
        from PIL import Image

        from dicomforge.adapt import to_pil_image

        # YBR_FULL encoding of white: Y=235, Cb=128, Cr=128
        pixels = np.array([[[235, 128, 128]]], dtype=np.uint8)
        ds = self._make_colour_dataset("YBR_FULL", pixels)
        img = to_pil_image(ds, apply_window=False)

        self.assertIsInstance(img, Image.Image)
        self.assertEqual(img.mode, "RGB")
        r, g, b = img.getpixel((0, 0))
        # All channels should be near 235 (bright grey/white), definitely not tinted
        self.assertGreater(r, 200)
        self.assertGreater(g, 200)
        self.assertGreater(b, 200)

    def test_ybr_full_not_treated_as_rgb(self):
        """Confirm YBR_FULL and RGB produce different pixel values for the same raw bytes."""
        self._skip_if_no_pixels()
        import numpy as np

        from dicomforge.adapt import to_pil_image

        # Raw bytes that look clearly wrong when misinterpreted as RGB
        pixels = np.array([[[100, 50, 200]]], dtype=np.uint8)

        ds_ybr = self._make_colour_dataset("YBR_FULL", pixels)
        ds_rgb = self._make_colour_dataset("RGB", pixels)

        rgb_from_ybr = to_pil_image(ds_ybr, apply_window=False).getpixel((0, 0))
        rgb_from_rgb = to_pil_image(ds_rgb, apply_window=False).getpixel((0, 0))

        # The two paths must produce different output for the same raw input
        self.assertNotEqual(rgb_from_ybr, rgb_from_rgb)

    def test_ybr_full_422_converted_to_rgb(self):
        """YBR_FULL_422 uses the same coefficients as YBR_FULL."""
        self._skip_if_no_pixels()
        import numpy as np

        from dicomforge.adapt import to_pil_image

        pixels = np.array([[[235, 128, 128]]], dtype=np.uint8)
        ds = self._make_colour_dataset("YBR_FULL_422", pixels)
        img = to_pil_image(ds, apply_window=False)

        r, g, b = img.getpixel((0, 0))
        self.assertGreater(r, 200)
        self.assertGreater(g, 200)
        self.assertGreater(b, 200)


if __name__ == "__main__":
    unittest.main()
