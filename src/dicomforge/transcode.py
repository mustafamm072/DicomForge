"""Dependency-free pixel-data transcoding between transfer syntaxes.

Two one-call helpers move a dataset between uncompressed pixel data and
RLE Lossless — the encapsulated transfer syntax DicomForge implements natively
(:mod:`dicomforge.rle`) — with no third-party packages::

    from dicomforge import compress_pixel_data, decompress_pixel_data

    compress_pixel_data(dataset)      # → RLE Lossless, in place
    decompress_pixel_data(dataset)    # → Explicit VR Little Endian, in place

Both helpers modify the dataset in place (updating ``PixelData``,
``TransferSyntaxUID``, and — for colour images — ``PlanarConfiguration``) and
return it for chaining.  Other encapsulated syntaxes (JPEG, JPEG 2000, …)
still require the pydicom backend with the relevant codec plugin.
"""

from __future__ import annotations

from typing import List

from dicomforge.dataset import DicomDataset
from dicomforge.encapsulation import EncapsulatedPixelData, as_encapsulated
from dicomforge.errors import DicomValidationError, UnsupportedTransferSyntaxError
from dicomforge.pixels import FrameMetadata, assert_pixel_data_length
from dicomforge.rle import rle_decode_frame, rle_encode_frame
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import TransferSyntaxUID


def compress_pixel_data(
    dataset: DicomDataset,
    *,
    transfer_syntax: str = TransferSyntaxUID.RLELossless,
) -> DicomDataset:
    """Compress uncompressed ``PixelData`` in place using the native RLE codec.

    The dataset's pixel bytes are split into frames, each frame is encoded as
    one RLE Lossless fragment, and ``TransferSyntaxUID`` is updated.  For
    colour images ``PlanarConfiguration`` is set to 0, the arrangement the
    frames decode back to.

    Parameters
    ----------
    dataset:
        Dataset holding uncompressed ``PixelData`` and standard pixel metadata.
    transfer_syntax:
        Target transfer syntax.  Only RLE Lossless (``1.2.840.10008.1.2.5``)
        is supported natively; other encapsulated syntaxes raise
        :class:`UnsupportedTransferSyntaxError` with a pydicom hint.

    Returns
    -------
    DicomDataset
        The same dataset, for call chaining.
    """

    if transfer_syntax != TransferSyntaxUID.RLELossless:
        target = TransferSyntax.from_uid(str(transfer_syntax))
        raise UnsupportedTransferSyntaxError(
            f"The native transcoder can only compress to RLE Lossless "
            f"({TransferSyntaxUID.RLELossless}); {target.name} ({target.uid}) "
            "requires the pydicom backend with a codec plugin."
        )

    source_uid = str(
        dataset.get(Tag.TransferSyntaxUID) or TransferSyntaxUID.ExplicitVRLittleEndian
    )
    source = TransferSyntax.from_uid(source_uid)
    if source.is_encapsulated:
        raise UnsupportedTransferSyntaxError(
            f"PixelData is already compressed ({source.name}). Decompress it "
            "before re-compressing to RLE Lossless."
        )

    meta = FrameMetadata.from_dataset(dataset)
    if meta.bits_allocated not in {8, 16} or meta.photometric_interpretation not in {
        "MONOCHROME1", "MONOCHROME2", "RGB", "YBR_FULL", "PALETTE COLOR"
    } or (meta.samples_per_pixel > 1 and meta.is_signed):
        raise DicomValidationError(
            "Unsupported DICOM RLE image attributes (PS3.5 Table 8.2.2-1); "
            "native encoding supports 8/16-bit standard monochrome or unsigned colour"
        )
    pixel_data = dataset.get(Tag.PixelData)
    if not isinstance(pixel_data, (bytes, bytearray)):
        raise DicomValidationError(
            "compress_pixel_data requires uncompressed PixelData bytes; got "
            f"{type(pixel_data).__name__}."
        )
    pixel_bytes = bytes(pixel_data)
    assert_pixel_data_length(pixel_bytes, meta)
    if not source.is_little_endian:
        pixel_bytes = _swap_bytes(pixel_bytes, meta.bytes_per_sample)

    frame_size = meta.expected_frame_bytes
    fragments = []
    for index in range(meta.number_of_frames):
        frame = pixel_bytes[index * frame_size : (index + 1) * frame_size]
        fragments.append(
            rle_encode_frame(
                frame,
                rows=meta.rows,
                columns=meta.columns,
                samples_per_pixel=meta.samples_per_pixel,
                bits_allocated=meta.bits_allocated,
                planar_configuration=meta.planar_configuration or 0,
            )
        )

    dataset.set(Tag.PixelData, EncapsulatedPixelData.from_frames(fragments), vr="OB")
    dataset.set(Tag.TransferSyntaxUID, TransferSyntaxUID.RLELossless)
    dataset.source_transfer_syntax = TransferSyntaxUID.RLELossless
    for tag in ((0x7FE0, 0x0001), (0x7FE0, 0x0002)):
        dataset.pop(Tag.parse(tag), None)
    if meta.samples_per_pixel > 1:
        dataset.set(Tag.PlanarConfiguration, 0)
    return dataset


def decompress_pixel_data(
    dataset: DicomDataset, *, max_output_bytes: int = 512 * 1024 * 1024,
) -> DicomDataset:
    """Decompress RLE Lossless ``PixelData`` in place to uncompressed bytes.

    ``TransferSyntaxUID`` becomes Explicit VR Little Endian and the decoded
    bytes are pixel-interleaved (``PlanarConfiguration`` 0) little-endian —
    the same layout the native uncompressed readers and numpy adapters expect.
    Datasets that are already uncompressed are returned unchanged, so the call
    is safe in pipelines that see mixed inputs.

    Raises
    ------
    UnsupportedTransferSyntaxError
        If ``PixelData`` is compressed with anything other than RLE Lossless.
    DicomValidationError
        If the compressed fragments cannot be resolved to frames.
    """

    source_uid = str(
        dataset.get(Tag.TransferSyntaxUID) or TransferSyntaxUID.ExplicitVRLittleEndian
    )
    source = TransferSyntax.from_uid(source_uid)
    if not source.is_encapsulated:
        return dataset
    if source_uid != TransferSyntaxUID.RLELossless:
        raise UnsupportedTransferSyntaxError(
            f"The native transcoder can only decompress RLE Lossless; "
            f"{source.name} ({source.uid}) requires the pydicom backend with a "
            "codec plugin."
        )

    meta = FrameMetadata.from_dataset(dataset)
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    if meta.expected_pixel_bytes > max_output_bytes:
        raise DicomValidationError("Decompressed PixelData exceeds max_output_bytes")
    frames = rle_frame_fragments(dataset, meta)
    decoded = bytearray()
    for fragment in frames:
        decoded += rle_decode_frame(
            fragment,
            rows=meta.rows,
            columns=meta.columns,
            samples_per_pixel=meta.samples_per_pixel,
            bits_allocated=meta.bits_allocated,
            max_decoded_bytes=max_output_bytes,
        )
    if len(decoded) % 2 == 1:
        decoded += b"\x00"

    dataset.set(Tag.PixelData, bytes(decoded), vr="OB" if meta.bits_allocated <= 8 else "OW")
    dataset.set(Tag.TransferSyntaxUID, TransferSyntaxUID.ExplicitVRLittleEndian)
    dataset.source_transfer_syntax = TransferSyntaxUID.ExplicitVRLittleEndian
    for tag in ((0x7FE0, 0x0001), (0x7FE0, 0x0002)):
        dataset.pop(Tag.parse(tag), None)
    if meta.samples_per_pixel > 1:
        dataset.set(Tag.PlanarConfiguration, 0)
    return dataset


def rle_frame_fragments(dataset: DicomDataset, meta: FrameMetadata) -> List[bytes]:
    """Return one RLE fragment per frame from a dataset's ``PixelData``."""

    pixel_data = dataset.get(Tag.PixelData)
    if pixel_data is None:
        raise DicomValidationError("PixelData (7FE0,0010) is missing.")
    encapsulated = as_encapsulated(pixel_data)
    if encapsulated is not None:
        return encapsulated.frame_fragments(meta.number_of_frames)
    if isinstance(pixel_data, (bytes, bytearray)):
        if meta.number_of_frames == 1:
            return [bytes(pixel_data)]
        raise DicomValidationError(
            f"Cannot split flattened compressed PixelData bytes into "
            f"{meta.number_of_frames} frames. Re-read the file with the native "
            "backend, which preserves fragment boundaries."
        )
    raise DicomValidationError(
        f"Compressed PixelData must be bytes or EncapsulatedPixelData; got "
        f"{type(pixel_data).__name__}."
    )


def _swap_bytes(data: bytes, bytes_per_sample: int) -> bytes:
    """Reverse byte order within each sample word (big ↔ little endian)."""

    if bytes_per_sample == 1:
        return data
    out = bytearray(len(data))
    for index in range(bytes_per_sample):
        out[index::bytes_per_sample] = data[bytes_per_sample - 1 - index :: bytes_per_sample]
    return bytes(out)
