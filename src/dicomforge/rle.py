"""Dependency-free DICOM RLE Lossless codec (PS3.5 Annex G).

RLE Lossless (``1.2.840.10008.1.2.5``) is the one encapsulated DICOM transfer
syntax that is practical to implement correctly in pure Python: each frame is
one fragment holding a 64-byte header followed by up to 15 PackBits-compressed
byte segments.  This module implements that codec with no third-party
packages, so DicomForge can read *and* write RLE-compressed pixel data even
when pydicom is not installed.

A frame is decomposed into byte segments per DICOM PS3.5 §G.2: one segment per
(sample, byte-of-sample) pair, most significant byte first within each sample.
Each segment is compressed with the PackBits byte run-length scheme
(PS3.5 §G.3.1) and padded to even length.

:func:`rle_encode_frame` consumes the frame's uncompressed little-endian pixel
bytes (pixel-interleaved by default, or colour-by-plane with
``planar_configuration=1``) and returns one RLE fragment.
:func:`rle_decode_frame` reverses it, always producing little-endian,
pixel-interleaved (Planar Configuration 0) bytes — the same convention pydicom
uses for decoded RLE output.

For whole-dataset workflows, use :func:`dicomforge.transcode.compress_pixel_data`
and :func:`dicomforge.transcode.decompress_pixel_data` instead of calling the
frame codec directly.
"""

from __future__ import annotations

import struct
from typing import List

from dicomforge.errors import DicomValidationError

#: Fixed size of the RLE fragment header: 16 little-endian 32-bit words.
RLE_HEADER_SIZE = 64

#: Maximum number of byte segments one RLE frame may contain (PS3.5 §G.4).
RLE_MAX_SEGMENTS = 15


def rle_encode_frame(
    frame: bytes,
    *,
    rows: int,
    columns: int,
    samples_per_pixel: int = 1,
    bits_allocated: int = 8,
    planar_configuration: int = 0,
) -> bytes:
    """Encode one uncompressed frame as a DICOM RLE Lossless fragment.

    Parameters
    ----------
    frame:
        The frame's uncompressed pixel bytes in little-endian byte order.
    rows, columns:
        Frame dimensions (``Rows`` / ``Columns``).
    samples_per_pixel:
        1 for greyscale, 3 for colour.
    bits_allocated:
        8, 16, or 32.
    planar_configuration:
        Arrangement of the *input* bytes when ``samples_per_pixel > 1``:
        0 for pixel-interleaved (RGB RGB …), 1 for colour-by-plane (RR… GG… BB…).

    Returns
    -------
    bytes
        One even-length RLE fragment: 64-byte header plus PackBits segments.
    """

    bytes_per_sample = _bytes_per_sample(bits_allocated)
    segment_count = samples_per_pixel * bytes_per_sample
    if segment_count > RLE_MAX_SEGMENTS:
        raise DicomValidationError(
            f"RLE supports at most {RLE_MAX_SEGMENTS} segments; "
            f"SamplesPerPixel={samples_per_pixel} with BitsAllocated={bits_allocated} "
            f"needs {segment_count}."
        )
    frame_pixels = rows * columns
    expected = frame_pixels * segment_count
    if len(frame) != expected:
        raise DicomValidationError(
            f"RLE frame length mismatch: expected {expected} bytes for "
            f"{rows}x{columns} with SamplesPerPixel={samples_per_pixel} and "
            f"BitsAllocated={bits_allocated}, got {len(frame)}."
        )
    if planar_configuration not in (0, 1):
        raise DicomValidationError(
            f"planar_configuration must be 0 or 1, got {planar_configuration}."
        )

    segments: List[bytes] = []
    for sample in range(samples_per_pixel):
        # Most significant byte first within each sample (PS3.5 §G.2).
        for byte_index in range(bytes_per_sample - 1, -1, -1):
            if planar_configuration == 1 and samples_per_pixel > 1:
                plane_size = frame_pixels * bytes_per_sample
                plane = frame[sample * plane_size : (sample + 1) * plane_size]
                segment = plane[byte_index::bytes_per_sample]
            else:
                start = sample * bytes_per_sample + byte_index
                segment = frame[start::segment_count]
            encoded = _packbits_encode(segment)
            if len(encoded) % 2 == 1:
                encoded += b"\x00"
            segments.append(encoded)

    offsets = []
    position = RLE_HEADER_SIZE
    for encoded in segments:
        offsets.append(position)
        position += len(encoded)
    header = struct.pack(
        "<16L",
        len(segments),
        *(offsets + [0] * (RLE_MAX_SEGMENTS - len(segments))),
    )
    return header + b"".join(segments)


def rle_decode_frame(
    fragment: bytes,
    *,
    rows: int,
    columns: int,
    samples_per_pixel: int = 1,
    bits_allocated: int = 8,
    max_decoded_bytes: int = 512 * 1024 * 1024,
) -> bytes:
    """Decode one DICOM RLE Lossless fragment to uncompressed pixel bytes.

    The returned bytes are little-endian and pixel-interleaved
    (Planar Configuration 0), matching the layout the native uncompressed
    transfer syntaxes and pydicom's RLE decoder use.
    """

    bytes_per_sample = _bytes_per_sample(bits_allocated)
    segment_count = samples_per_pixel * bytes_per_sample
    frame_pixels = rows * columns
    if rows <= 0 or columns <= 0 or not 1 <= segment_count <= RLE_MAX_SEGMENTS:
        raise DicomValidationError("Invalid RLE frame dimensions or sample count")
    if max_decoded_bytes <= 0:
        raise ValueError("max_decoded_bytes must be positive")
    if frame_pixels * segment_count > max_decoded_bytes:
        raise DicomValidationError("RLE frame exceeds max_decoded_bytes before allocation")
    if len(fragment) < RLE_HEADER_SIZE:
        raise DicomValidationError(
            f"RLE fragment is {len(fragment)} bytes; the 64-byte RLE header is "
            "incomplete."
        )
    header = struct.unpack_from("<16L", fragment, 0)
    declared_segments = header[0]
    if declared_segments != segment_count:
        raise DicomValidationError(
            f"RLE header declares {declared_segments} segment(s) but "
            f"SamplesPerPixel={samples_per_pixel} with BitsAllocated="
            f"{bits_allocated} requires {segment_count}."
        )
    if declared_segments > RLE_MAX_SEGMENTS:
        raise DicomValidationError(
            f"RLE header declares {declared_segments} segments; the maximum is "
            f"{RLE_MAX_SEGMENTS}."
        )

    out = bytearray(frame_pixels * segment_count)
    for index in range(declared_segments):
        start = header[1 + index]
        if start < RLE_HEADER_SIZE or start > len(fragment):
            raise DicomValidationError(
                f"RLE segment {index} offset {start} is outside the fragment "
                f"({len(fragment)} bytes)."
            )
        end = header[2 + index] if index + 1 < declared_segments else len(fragment)
        if end < start or end > len(fragment):
            raise DicomValidationError(
                f"RLE segment {index} spans invalid range {start}..{end}."
            )
        segment = _packbits_decode(fragment[start:end], frame_pixels)
        sample, byte_msb_first = divmod(index, bytes_per_sample)
        # Segment order is MSB-first; recompose little-endian interleaved bytes.
        byte_index = bytes_per_sample - 1 - byte_msb_first
        position = sample * bytes_per_sample + byte_index
        out[position::segment_count] = segment
    return bytes(out)


def _bytes_per_sample(bits_allocated: int) -> int:
    if bits_allocated not in (8, 16, 32):
        raise DicomValidationError(
            f"RLE Lossless supports BitsAllocated 8, 16, or 32; got {bits_allocated}."
        )
    return bits_allocated // 8


def _packbits_encode(data: bytes) -> bytes:
    """Compress one byte segment with the PackBits scheme (PS3.5 §G.3.1)."""

    out = bytearray()
    length = len(data)
    pos = 0
    literal_start = 0
    while pos < length:
        run_byte = data[pos]
        run_end = pos + 1
        max_run = min(pos + 128, length)
        while run_end < max_run and data[run_end] == run_byte:
            run_end += 1
        run_length = run_end - pos
        if run_length >= 3 or (run_length >= 2 and run_end == length):
            _flush_literal(out, data, literal_start, pos)
            out.append(257 - run_length)
            out.append(run_byte)
            pos = run_end
            literal_start = pos
        else:
            pos += 1
            if pos - literal_start == 128:
                _flush_literal(out, data, literal_start, pos)
                literal_start = pos
    _flush_literal(out, data, literal_start, length)
    return bytes(out)


def _flush_literal(out: bytearray, data: bytes, start: int, end: int) -> None:
    while start < end:
        chunk_end = min(start + 128, end)
        out.append(chunk_end - start - 1)
        out += data[start:chunk_end]
        start = chunk_end


def _packbits_decode(data: bytes, expected_length: int) -> bytes:
    """Expand one PackBits segment to exactly *expected_length* bytes."""

    out = bytearray()
    pos = 0
    length = len(data)
    while pos < length and len(out) < expected_length:
        control = data[pos]
        pos += 1
        if control <= 127:
            count = control + 1
            if pos + count > length:
                raise DicomValidationError(
                    "Truncated RLE literal run: the segment ends mid-run."
                )
            out += data[pos : pos + count]
            pos += count
        elif control == 128:
            continue  # No-operation control byte.
        else:
            if pos >= length:
                raise DicomValidationError(
                    "Truncated RLE replicate run: missing the repeated byte."
                )
            out += bytes([data[pos]]) * (257 - control)
            pos += 1
    if len(out) < expected_length:
        raise DicomValidationError(
            f"RLE segment decoded to {len(out)} bytes; expected {expected_length}."
        )
    # Segments are padded to even length, so a single trailing byte may spill.
    return bytes(out[:expected_length])
