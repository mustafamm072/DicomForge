"""Tests for the native RLE Lossless codec, encapsulation, and transcoding."""

import importlib.util
import os
import struct
import tempfile
import unittest

from dicomforge import io, part10
from dicomforge.codecs import default_registry
from dicomforge.dataset import DicomDataset
from dicomforge.encapsulation import EncapsulatedPixelData
from dicomforge.errors import DicomValidationError, UnsupportedTransferSyntaxError
from dicomforge.rle import (
    RLE_HEADER_SIZE,
    _packbits_decode,
    _packbits_encode,
    rle_decode_frame,
    rle_encode_frame,
)
from dicomforge.tags import Tag
from dicomforge.transcode import compress_pixel_data, decompress_pixel_data
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import SopClassUID, TransferSyntaxUID

_HAS_PYDICOM = importlib.util.find_spec("pydicom") is not None
_HAS_NUMPY = importlib.util.find_spec("numpy") is not None


def _image_dataset(
    *,
    rows=4,
    columns=4,
    bits_allocated=16,
    samples_per_pixel=1,
    pixel_representation=0,
    number_of_frames=1,
    photometric="MONOCHROME2",
    planar_configuration=None,
    pixel_data=None,
):
    dataset = DicomDataset(
        {
            Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
            Tag.SOPInstanceUID: "1.2.826.0.1.3680043.8.498.99",
            Tag.Modality: "OT",
            Tag.Rows: rows,
            Tag.Columns: columns,
            Tag.BitsAllocated: bits_allocated,
            Tag.BitsStored: bits_allocated,
            Tag.HighBit: bits_allocated - 1,
            Tag.PixelRepresentation: pixel_representation,
            Tag.SamplesPerPixel: samples_per_pixel,
            Tag.PhotometricInterpretation: photometric,
            Tag.NumberOfFrames: number_of_frames,
        }
    )
    if planar_configuration is not None:
        dataset.set(Tag.PlanarConfiguration, planar_configuration)
    if pixel_data is not None:
        dataset.set(Tag.PixelData, pixel_data)
    return dataset


def _pattern(length, seed=0):
    """Deterministic mixed data: runs plus non-repeating stretches."""

    out = bytearray()
    value = seed
    while len(out) < length:
        run = 1 + (value * 7 + 3) % 9
        out += bytes([value % 256]) * run
        out += bytes(((value + i * 31) % 256) for i in range(5))
        value += 1
    return bytes(out[:length])


class PackBitsTests(unittest.TestCase):
    def _round_trip(self, data):
        encoded = _packbits_encode(data)
        self.assertEqual(_packbits_decode(encoded, len(data)), data)

    def test_empty(self):
        self.assertEqual(_packbits_encode(b""), b"")
        self.assertEqual(_packbits_decode(b"", 0), b"")

    def test_single_byte(self):
        self._round_trip(b"\x42")

    def test_long_replicate_run(self):
        self._round_trip(b"\x07" * 1000)

    def test_long_literal_run(self):
        self._round_trip(bytes(range(256)) * 3)

    def test_alternating_bytes_do_not_bloat(self):
        data = b"\x00\x01" * 500
        encoded = _packbits_encode(data)
        # A run->literal-thrashing encoder would double the size.
        self.assertLess(len(encoded), len(data) + len(data) // 64 + 2)
        self.assertEqual(_packbits_decode(encoded, len(data)), data)

    def test_mixed_pattern(self):
        self._round_trip(_pattern(4096))

    def test_trailing_two_byte_run(self):
        self._round_trip(b"\x01\x02\x03\x09\x09")

    def test_replicate_compresses(self):
        encoded = _packbits_encode(b"\xaa" * 128)
        self.assertEqual(encoded, b"\x81\xaa")

    def test_noop_control_byte_ignored(self):
        self.assertEqual(_packbits_decode(b"\x80\x00\x41", 1), b"A")

    def test_truncated_replicate_raises(self):
        with self.assertRaises(DicomValidationError):
            _packbits_decode(b"\xfe", 3)

    def test_truncated_literal_raises(self):
        with self.assertRaises(DicomValidationError):
            _packbits_decode(b"\x05\x01\x02", 6)

    def test_short_output_raises(self):
        with self.assertRaises(DicomValidationError):
            _packbits_decode(b"\x00\x41", 2)


class RleFrameTests(unittest.TestCase):
    def test_round_trip_8bit_mono(self):
        frame = _pattern(64)
        fragment = rle_encode_frame(frame, rows=8, columns=8, bits_allocated=8)
        self.assertEqual(len(fragment) % 2, 0)
        header = struct.unpack_from("<16L", fragment, 0)
        self.assertEqual(header[0], 1)
        self.assertEqual(header[1], RLE_HEADER_SIZE)
        decoded = rle_decode_frame(fragment, rows=8, columns=8, bits_allocated=8)
        self.assertEqual(decoded, frame)

    def test_round_trip_16bit_mono(self):
        frame = _pattern(2 * 16 * 16)
        fragment = rle_encode_frame(frame, rows=16, columns=16, bits_allocated=16)
        decoded = rle_decode_frame(fragment, rows=16, columns=16, bits_allocated=16)
        self.assertEqual(decoded, frame)

    def test_round_trip_32bit_mono(self):
        frame = _pattern(4 * 8 * 8)
        fragment = rle_encode_frame(frame, rows=8, columns=8, bits_allocated=32)
        decoded = rle_decode_frame(fragment, rows=8, columns=8, bits_allocated=32)
        self.assertEqual(decoded, frame)

    def test_round_trip_rgb_interleaved(self):
        frame = _pattern(3 * 8 * 8)
        fragment = rle_encode_frame(
            frame, rows=8, columns=8, samples_per_pixel=3, bits_allocated=8
        )
        header = struct.unpack_from("<16L", fragment, 0)
        self.assertEqual(header[0], 3)
        decoded = rle_decode_frame(
            fragment, rows=8, columns=8, samples_per_pixel=3, bits_allocated=8
        )
        self.assertEqual(decoded, frame)

    def test_planar_input_decodes_to_interleaved(self):
        # Planes: RR.. GG.. BB.. must decode to RGBRGB...
        rows = columns = 2
        planes = b"\x10" * 4 + b"\x20" * 4 + b"\x30" * 4
        fragment = rle_encode_frame(
            planes,
            rows=rows,
            columns=columns,
            samples_per_pixel=3,
            bits_allocated=8,
            planar_configuration=1,
        )
        decoded = rle_decode_frame(
            fragment, rows=rows, columns=columns, samples_per_pixel=3, bits_allocated=8
        )
        self.assertEqual(decoded, b"\x10\x20\x30" * 4)

    def test_segment_order_is_msb_first(self):
        # One pixel, value 0x0201 little endian -> MSB segment 0x02, LSB 0x01.
        fragment = rle_encode_frame(b"\x01\x02", rows=1, columns=1, bits_allocated=16)
        header = struct.unpack_from("<16L", fragment, 0)
        msb = _packbits_decode(fragment[header[1] : header[2]], 1)
        lsb = _packbits_decode(fragment[header[2] :], 1)
        self.assertEqual((msb, lsb), (b"\x02", b"\x01"))

    def test_wrong_frame_length_raises(self):
        with self.assertRaises(DicomValidationError):
            rle_encode_frame(b"\x00" * 3, rows=2, columns=2, bits_allocated=8)

    def test_too_many_segments_raises(self):
        with self.assertRaises(DicomValidationError):
            rle_encode_frame(
                b"\x00" * 64, rows=2, columns=2, samples_per_pixel=16, bits_allocated=8
            )

    def test_unsupported_bits_allocated_raises(self):
        with self.assertRaises(DicomValidationError):
            rle_encode_frame(b"\x00" * 4, rows=2, columns=2, bits_allocated=12)

    def test_decode_segment_count_mismatch_raises(self):
        fragment = rle_encode_frame(b"\x00" * 4, rows=2, columns=2, bits_allocated=8)
        with self.assertRaises(DicomValidationError):
            rle_decode_frame(fragment, rows=2, columns=2, bits_allocated=16)

    def test_decode_truncated_header_raises(self):
        with self.assertRaises(DicomValidationError):
            rle_decode_frame(b"\x00" * 10, rows=2, columns=2, bits_allocated=8)


class EncapsulatedPixelDataTests(unittest.TestCase):
    def test_behaves_like_bytes(self):
        value = EncapsulatedPixelData([b"abc", b"def"])
        self.assertIsInstance(value, bytes)
        self.assertEqual(value, b"abcdef")
        self.assertEqual(value.fragments, (b"abc", b"def"))

    def test_from_frames_offsets(self):
        value = EncapsulatedPixelData.from_frames([b"ab", b"cde"])
        # Frame 1 starts after item header (8) + 2 payload bytes.
        self.assertEqual(value.basic_offset_table, (0, 10))

    def test_frame_fragments_by_count(self):
        value = EncapsulatedPixelData([b"ab", b"cd", b"ef"])
        self.assertEqual(value.frame_fragments(3), [b"ab", b"cd", b"ef"])
        self.assertEqual(value.frame_fragments(1), [b"abcdef"])

    def test_frame_fragments_by_offset_table(self):
        # Two frames, three fragments: frame 0 = frags 0+1, frame 1 = frag 2.
        fragments = [b"aabb", b"cc", b"dddd"]
        offsets = (0, 8 + 4 + 8 + 2)  # fragment stream positions
        value = EncapsulatedPixelData(fragments, offsets)
        self.assertEqual(value.frame_fragments(2), [b"aabbcc", b"dddd"])

    def test_deepcopy_and_pickle_preserve_fragments(self):
        import copy
        import pickle

        value = EncapsulatedPixelData([b"ab", b"cd"], (0, 10))
        for clone in (
            copy.copy(value),
            copy.deepcopy(value),
            pickle.loads(pickle.dumps(value)),
        ):
            self.assertEqual(clone, b"abcd")
            self.assertEqual(clone.fragments, (b"ab", b"cd"))
            self.assertEqual(clone.basic_offset_table, (0, 10))

    def test_unresolvable_framing_raises(self):
        value = EncapsulatedPixelData([b"ab", b"cd", b"ef"])
        with self.assertRaises(DicomValidationError):
            value.frame_fragments(2)


class TranscodeTests(unittest.TestCase):
    def test_compress_decompress_round_trip_multiframe(self):
        pixels = _pattern(2 * 16 * 2)  # 16-bit, 4x4, 2 frames
        dataset = _image_dataset(number_of_frames=2, pixel_data=pixels)
        compress_pixel_data(dataset)

        self.assertEqual(
            dataset.get(Tag.TransferSyntaxUID), TransferSyntaxUID.RLELossless
        )
        value = dataset.get(Tag.PixelData)
        self.assertIsInstance(value, EncapsulatedPixelData)
        self.assertEqual(len(value.fragments), 2)

        decompress_pixel_data(dataset)
        self.assertEqual(
            dataset.get(Tag.TransferSyntaxUID),
            TransferSyntaxUID.ExplicitVRLittleEndian,
        )
        self.assertEqual(dataset.get(Tag.PixelData), pixels)

    def test_compress_big_endian_source_byte_swaps(self):
        le_pixels = _pattern(2 * 16)
        be_pixels = bytearray(le_pixels)
        be_pixels[0::2], be_pixels[1::2] = le_pixels[1::2], le_pixels[0::2]
        dataset = _image_dataset(pixel_data=bytes(be_pixels))
        dataset.set(Tag.TransferSyntaxUID, TransferSyntaxUID.ExplicitVRBigEndian)
        compress_pixel_data(dataset)
        decompress_pixel_data(dataset)
        self.assertEqual(dataset.get(Tag.PixelData), le_pixels)

    def test_compress_rgb_sets_planar_configuration_zero(self):
        planes = b"\x10" * 4 + b"\x20" * 4 + b"\x30" * 4
        dataset = _image_dataset(
            rows=2,
            columns=2,
            bits_allocated=8,
            samples_per_pixel=3,
            photometric="RGB",
            planar_configuration=1,
            pixel_data=planes,
        )
        compress_pixel_data(dataset)
        self.assertEqual(dataset.get(Tag.PlanarConfiguration), 0)
        decompress_pixel_data(dataset)
        self.assertEqual(dataset.get(Tag.PixelData), b"\x10\x20\x30" * 4)

    def test_compress_to_other_syntax_raises(self):
        dataset = _image_dataset(pixel_data=_pattern(32))
        with self.assertRaises(UnsupportedTransferSyntaxError):
            compress_pixel_data(
                dataset, transfer_syntax=TransferSyntaxUID.JPEG2000Lossless
            )

    def test_compress_already_compressed_raises(self):
        dataset = _image_dataset(pixel_data=_pattern(32))
        compress_pixel_data(dataset)
        with self.assertRaises(UnsupportedTransferSyntaxError):
            compress_pixel_data(dataset)

    def test_decompress_uncompressed_is_noop(self):
        pixels = _pattern(32)
        dataset = _image_dataset(pixel_data=pixels)
        decompress_pixel_data(dataset)
        self.assertEqual(dataset.get(Tag.PixelData), pixels)

    def test_decompress_other_compressed_syntax_raises(self):
        dataset = _image_dataset(pixel_data=b"\x00")
        dataset.set(Tag.TransferSyntaxUID, TransferSyntaxUID.JPEGBaselineProcess1)
        with self.assertRaises(UnsupportedTransferSyntaxError):
            decompress_pixel_data(dataset)

    def test_registry_supports_rle_natively(self):
        registry = default_registry()
        syntax = TransferSyntax.from_uid(TransferSyntaxUID.RLELossless)
        self.assertTrue(registry.supports(syntax))
        self.assertTrue(registry.supports(syntax, encode=True))
        self.assertEqual(registry.find(syntax).name, "native-rle")


class Part10EncapsulatedTests(unittest.TestCase):
    def _compressed_dataset(self, number_of_frames=2):
        pixels = _pattern(2 * 16 * number_of_frames)
        dataset = _image_dataset(number_of_frames=number_of_frames, pixel_data=pixels)
        compress_pixel_data(dataset)
        return dataset, pixels

    def test_dumps_loads_round_trip(self):
        dataset, pixels = self._compressed_dataset()
        original = dataset.get(Tag.PixelData)
        blob = part10.dumps(dataset)
        restored = part10.loads(blob)

        value = restored.get(Tag.PixelData)
        self.assertIsInstance(value, EncapsulatedPixelData)
        self.assertEqual(value.fragments, original.fragments)
        self.assertEqual(value.basic_offset_table, original.basic_offset_table)

        decompress_pixel_data(restored)
        self.assertEqual(restored.get(Tag.PixelData), pixels)

    def test_file_round_trip_via_io_native(self):
        dataset, pixels = self._compressed_dataset()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rle.dcm")
            io.write(path, dataset, backend="native")
            restored = io.read(path, backend="native")
        decompress_pixel_data(restored)
        self.assertEqual(restored.get(Tag.PixelData), pixels)

    def test_dumps_accepts_fragment_list(self):
        dataset, _ = self._compressed_dataset(number_of_frames=1)
        fragments = list(dataset.get(Tag.PixelData).fragments)
        dataset.set(Tag.PixelData, fragments)
        restored = part10.loads(part10.dumps(dataset))
        self.assertEqual(restored.get(Tag.PixelData).fragments, tuple(fragments))

    def test_dumps_accepts_plain_bytes_single_fragment(self):
        dataset, _ = self._compressed_dataset(number_of_frames=1)
        fragment = bytes(dataset.get(Tag.PixelData))
        dataset.set(Tag.PixelData, fragment)
        restored = part10.loads(part10.dumps(dataset))
        self.assertEqual(restored.get(Tag.PixelData), fragment)

    def test_dumps_rejects_uncompressible_value(self):
        dataset, _ = self._compressed_dataset(number_of_frames=1)
        dataset.set(Tag.PixelData, 12345)
        with self.assertRaises(DicomValidationError):
            part10.dumps(dataset)

    def test_stop_before_pixels_still_works(self):
        dataset, _ = self._compressed_dataset()
        blob = part10.dumps(dataset)
        restored = part10.loads(blob, stop_before_pixels=True)
        self.assertIsNone(restored.get(Tag.PixelData))
        self.assertEqual(restored.get(Tag.Rows), 4)


@unittest.skipUnless(_HAS_PYDICOM, "pydicom not installed")
class PydicomInteropTests(unittest.TestCase):
    def test_pydicom_decodes_native_rle_file(self):
        import numpy as np
        import pydicom

        pixels = _pattern(2 * 16 * 2)
        dataset = _image_dataset(number_of_frames=2, pixel_data=pixels)
        compress_pixel_data(dataset)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "native-rle.dcm")
            part10.write_file(path, dataset)
            raw = pydicom.dcmread(path)
            decoded = raw.pixel_array
        expected = np.frombuffer(pixels, dtype="<u2").reshape(2, 4, 4)
        self.assertTrue((decoded == expected).all())

    def test_native_decodes_pydicom_rle_file(self):
        import pydicom
        from pydicom.uid import ExplicitVRLittleEndian, RLELossless

        pixels = _pattern(2 * 16 * 2)
        d = pydicom.Dataset()
        d.SOPClassUID = SopClassUID.SecondaryCaptureImageStorage
        d.SOPInstanceUID = "1.2.826.0.1.3680043.8.498.77"
        d.Modality = "OT"
        d.Rows = 4
        d.Columns = 4
        d.BitsAllocated = 16
        d.BitsStored = 16
        d.HighBit = 15
        d.PixelRepresentation = 0
        d.SamplesPerPixel = 1
        d.PhotometricInterpretation = "MONOCHROME2"
        d.NumberOfFrames = 2
        d.PixelData = pixels
        fm = pydicom.dataset.FileMetaDataset()
        fm.TransferSyntaxUID = ExplicitVRLittleEndian
        d.file_meta = fm
        d.preamble = b"\x00" * 128
        d.compress(RLELossless)

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pydicom-rle.dcm")
            pydicom.dcmwrite(path, d)
            restored = part10.read_file(path)

        self.assertEqual(
            str(restored.get(Tag.TransferSyntaxUID)), str(RLELossless)
        )
        decompress_pixel_data(restored)
        self.assertEqual(restored.get(Tag.PixelData), pixels)


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed")
class AdaptRleTests(unittest.TestCase):
    def test_pixel_array_decodes_rle_natively(self):
        import numpy as np

        from dicomforge.adapt import iter_pixel_frames, pixel_array

        pixels = _pattern(2 * 16 * 2)
        dataset = _image_dataset(number_of_frames=2, pixel_data=pixels)
        compress_pixel_data(dataset)

        expected = np.frombuffer(pixels, dtype="<u2").reshape(2, 4, 4)
        self.assertTrue((pixel_array(dataset, frame=1) == expected[1]).all())
        frames = list(iter_pixel_frames(dataset))
        self.assertEqual(len(frames), 2)
        self.assertTrue((frames[0] == expected[0]).all())

    def test_pixel_array_rle_rgb(self):
        import numpy as np

        from dicomforge.adapt import pixel_array

        frame = _pattern(3 * 4 * 4)
        dataset = _image_dataset(
            bits_allocated=8,
            samples_per_pixel=3,
            photometric="RGB",
            planar_configuration=0,
            pixel_data=frame,
        )
        compress_pixel_data(dataset)
        arr = pixel_array(dataset)
        expected = np.frombuffer(frame, dtype=np.uint8).reshape(4, 4, 3)
        self.assertTrue((arr == expected).all())


if __name__ == "__main__":
    unittest.main()
