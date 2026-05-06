import unittest

from dicomforge import DicomDataset, FrameMetadata, Tag, VoiLut
from dicomforge.errors import UnsupportedTransferSyntaxError
from dicomforge.pixels import (
    PixelMetadataError,
    apply_voi_window,
    assert_pixel_data_length,
    check_pixel_capability,
    expected_samples_per_pixel,
    is_monochrome,
    needs_inversion,
    rescale_from_dataset,
    rescale_value,
    rescale_values,
    voi_window_bounds,
)


def native_ct_dataset() -> DicomDataset:
    return DicomDataset(
        {
            Tag.TransferSyntaxUID: "1.2.840.10008.1.2.1",
            Tag.Rows: 2,
            Tag.Columns: 2,
            Tag.SamplesPerPixel: 1,
            Tag.PhotometricInterpretation: "MONOCHROME2",
            Tag.BitsAllocated: 16,
            Tag.BitsStored: 12,
            Tag.HighBit: 11,
            Tag.PixelRepresentation: 0,
            Tag.RescaleSlope: "2",
            Tag.RescaleIntercept: "-1024",
            Tag.WindowCenter: 40,
            Tag.WindowWidth: 400,
            Tag.PixelData: b"\x00\x00\x01\x00\x02\x00\x03\x00",
        }
    )


class FrameMetadataTests(unittest.TestCase):
    def test_frame_metadata_from_golden_native_ct_sample(self):
        metadata = FrameMetadata.from_dataset(native_ct_dataset())

        self.assertEqual(metadata.rows, 2)
        self.assertEqual(metadata.columns, 2)
        self.assertEqual(metadata.frame_pixels, 4)
        self.assertEqual(metadata.expected_frame_bytes, 8)
        self.assertEqual(metadata.expected_pixel_bytes, 8)
        self.assertFalse(metadata.is_signed)

    def test_frame_metadata_rejects_inconsistent_high_bit(self):
        dataset = native_ct_dataset()
        dataset.set(Tag.HighBit, 15)

        with self.assertRaises(PixelMetadataError):
            FrameMetadata.from_dataset(dataset)

    def test_frame_metadata_validates_direct_construction(self):
        with self.assertRaisesRegex(PixelMetadataError, "BitsStored"):
            FrameMetadata(
                rows=1,
                columns=1,
                samples_per_pixel=1,
                bits_allocated=8,
                bits_stored=16,
                high_bit=15,
                pixel_representation=0,
                photometric_interpretation="MONOCHROME2",
            )

    def test_rgb_metadata_defaults_planar_configuration(self):
        dataset = native_ct_dataset()
        dataset.set(Tag.SamplesPerPixel, 3)
        dataset.set(Tag.PhotometricInterpretation, "RGB")
        dataset.set(Tag.PlanarConfiguration, 0)
        dataset.set(Tag.PixelData, b"\x00" * 24)

        metadata = FrameMetadata.from_dataset(dataset)

        self.assertEqual(metadata.planar_configuration, 0)
        self.assertEqual(metadata.expected_pixel_bytes, 24)

    def test_frame_metadata_requires_core_pixel_tags(self):
        dataset = native_ct_dataset()
        del dataset[Tag.SamplesPerPixel]

        with self.assertRaisesRegex(PixelMetadataError, "SamplesPerPixel"):
            FrameMetadata.from_dataset(dataset)

    def test_color_metadata_requires_planar_configuration(self):
        dataset = native_ct_dataset()
        dataset.set(Tag.SamplesPerPixel, 3)
        dataset.set(Tag.PhotometricInterpretation, "RGB")

        with self.assertRaisesRegex(PixelMetadataError, "PlanarConfiguration"):
            FrameMetadata.from_dataset(dataset)

    def test_photometric_samples_per_pixel_must_match(self):
        dataset = native_ct_dataset()
        dataset.set(Tag.SamplesPerPixel, 3)
        dataset.set(Tag.PhotometricInterpretation, "MONOCHROME2")
        dataset.set(Tag.PlanarConfiguration, 0)

        with self.assertRaisesRegex(PixelMetadataError, "SamplesPerPixel 1"):
            FrameMetadata.from_dataset(dataset)


class PixelCapabilityTests(unittest.TestCase):
    def test_native_uncompressed_dataset_is_supported(self):
        capability = check_pixel_capability(native_ct_dataset())

        self.assertTrue(capability.can_decode)
        self.assertEqual(capability.codec_name, "native-uncompressed")
        self.assertFalse(capability.transfer_syntax.is_compressed)

    def test_unsupported_compressed_syntax_has_actionable_error(self):
        dataset = native_ct_dataset()
        dataset.set(Tag.TransferSyntaxUID, "1.2.840.10008.1.2.4.90")

        with self.assertRaisesRegex(
            UnsupportedTransferSyntaxError,
            "compressed and no decoder is registered",
        ):
            check_pixel_capability(dataset)

    def test_pixel_data_length_check(self):
        metadata = FrameMetadata.from_dataset(native_ct_dataset())

        assert_pixel_data_length(b"\x00\x00\x01\x00\x02\x00\x03\x00", metadata)
        assert_pixel_data_length(bytearray(b"\x00\x00\x01\x00\x02\x00\x03\x00"), metadata)
        with self.assertRaises(PixelMetadataError):
            assert_pixel_data_length(b"\x00", metadata)

    def test_capability_checks_native_pixel_data_length(self):
        dataset = native_ct_dataset()
        dataset.set(Tag.PixelData, b"\x00")

        with self.assertRaisesRegex(PixelMetadataError, "PixelData length mismatch"):
            check_pixel_capability(dataset)

    def test_capability_requires_transfer_syntax(self):
        dataset = native_ct_dataset()
        del dataset[Tag.TransferSyntaxUID]

        with self.assertRaisesRegex(PixelMetadataError, "TransferSyntaxUID"):
            check_pixel_capability(dataset)

    def test_odd_length_native_pixel_data_allows_zero_padding(self):
        metadata = FrameMetadata(
            rows=1,
            columns=1,
            samples_per_pixel=1,
            bits_allocated=8,
            bits_stored=8,
            high_bit=7,
            pixel_representation=0,
            photometric_interpretation="MONOCHROME2",
        )

        assert_pixel_data_length(b"\x7f", metadata)
        assert_pixel_data_length(b"\x7f\x00", metadata)
        with self.assertRaisesRegex(PixelMetadataError, "padding byte"):
            assert_pixel_data_length(b"\x7f\x01", metadata)

    def test_even_length_pixel_data_last_byte_not_checked(self):
        # Regression: assert_pixel_data_length must NOT check the last byte's
        # value when expected length is even — it is real pixel data, not padding.
        metadata = FrameMetadata(
            rows=2,
            columns=2,
            samples_per_pixel=1,
            bits_allocated=8,
            bits_stored=8,
            high_bit=7,
            pixel_representation=0,
            photometric_interpretation="MONOCHROME2",
        )
        # 4 pixels, last byte is 0xFF — must not raise
        assert_pixel_data_length(b"\x00\x01\x02\xff", metadata)


class PixelHelperTests(unittest.TestCase):
    def test_rescale_helpers(self):
        self.assertEqual(rescale_value(100, slope=2, intercept=-1024), -824)
        self.assertEqual(rescale_values([0, 1, 2], slope=2, intercept=-1), [-1, 1, 3])
        self.assertEqual(rescale_from_dataset(100, native_ct_dataset()), -824)

    def test_voi_window_helpers(self):
        self.assertEqual(voi_window_bounds(40, 400), (-160.0, 239.0))
        self.assertEqual(apply_voi_window(-200, center=40, width=400), 0)
        self.assertEqual(apply_voi_window(300, center=40, width=400), 255)
        self.assertAlmostEqual(apply_voi_window(40, center=40, width=400), 127.81954887218045)

    def test_voi_lut_helper(self):
        lut = VoiLut.from_descriptor([4, -1, 16], [10, 20, 30, 40])

        self.assertEqual(lut.apply(-2), 10)
        self.assertEqual(lut.apply(-1), 10)
        self.assertEqual(lut.apply(1), 30)
        self.assertEqual(lut.apply(99), 40)

    def test_photometric_helpers(self):
        self.assertTrue(is_monochrome("monochrome1"))
        self.assertTrue(needs_inversion("MONOCHROME1"))
        self.assertFalse(needs_inversion("MONOCHROME2"))
        self.assertEqual(expected_samples_per_pixel("RGB"), 3)
        self.assertEqual(expected_samples_per_pixel("PALETTE COLOR"), 1)


if __name__ == "__main__":
    unittest.main()
