"""Dependency-free RLE Lossless compression and decompression.

This example runs with zero optional dependencies installed: the RLE codec,
the encapsulated pixel-data framing, and the Part 10 file IO are all native.

Run from the repository root:

    PYTHONPATH=src python3 examples/rle_compression.py
"""

import os
import tempfile

from dicomforge import (
    DicomDataset,
    SopClassUID,
    Tag,
    TransferSyntaxUID,
    compress_pixel_data,
    dcmread,
    dcmwrite,
    decompress_pixel_data,
    generate_uid,
)


def build_sample() -> DicomDataset:
    """A two-frame 16-bit image with smooth ramps (compresses well)."""

    rows, columns, frames = 64, 64, 2
    pixels = bytearray()
    for frame in range(frames):
        for row in range(rows):
            value = (frame * 500 + row * 16) & 0xFFFF
            pixels += value.to_bytes(2, "little") * columns
    return DicomDataset(
        {
            Tag.SOPClassUID: SopClassUID.SecondaryCaptureImageStorage,
            Tag.SOPInstanceUID: generate_uid(),
            Tag.Modality: "OT",
            Tag.PhotometricInterpretation: "MONOCHROME2",
            Tag.SamplesPerPixel: 1,
            Tag.Rows: rows,
            Tag.Columns: columns,
            Tag.NumberOfFrames: frames,
            Tag.BitsAllocated: 16,
            Tag.BitsStored: 16,
            Tag.HighBit: 15,
            Tag.PixelRepresentation: 0,
            Tag.PixelData: bytes(pixels),
        }
    )


def main() -> None:
    dataset = build_sample()
    original_pixels = dataset.get(Tag.PixelData)

    with tempfile.TemporaryDirectory() as tmp:
        raw_path = os.path.join(tmp, "uncompressed.dcm")
        rle_path = os.path.join(tmp, "rle.dcm")

        dcmwrite(raw_path, dataset, backend="native")

        # Compress in place and write an RLE Lossless file.
        compress_pixel_data(dataset)
        assert dataset.get(Tag.TransferSyntaxUID) == TransferSyntaxUID.RLELossless
        dcmwrite(rle_path, dataset, backend="native")

        raw_size = os.path.getsize(raw_path)
        rle_size = os.path.getsize(rle_path)
        print(f"uncompressed file: {raw_size} bytes")
        print(f"RLE Lossless file: {rle_size} bytes ({rle_size / raw_size:.0%})")

        # Read the compressed file back and restore the original pixels.
        restored = dcmread(rle_path, backend="native")
        decompress_pixel_data(restored)
        assert restored.get(Tag.PixelData) == original_pixels
        print("round trip: decompressed pixels are bit-identical")


if __name__ == "__main__":
    main()
