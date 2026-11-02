"""Dependency-free DICOM Part 10 file reader and writer.

This module lets DicomForge read and write ``.dcm`` files without any external
dependency.  It implements the DICOM File Format (PS3.10): the 128-byte
preamble, the ``DICM`` magic, the File Meta Information group (always Explicit VR
Little Endian), and the data set itself encoded with the declared Transfer
Syntax.

Supported transfer syntaxes (native, no plug-ins required):

* Implicit VR Little Endian (``1.2.840.10008.1.2``)
* Explicit VR Little Endian (``1.2.840.10008.1.2.1``)
* Deflated Explicit VR Little Endian (``1.2.840.10008.1.2.1.99``) — via the
  standard-library :mod:`zlib`
* Explicit VR Big Endian (``1.2.840.10008.1.2.2``)

Encapsulated (compressed) transfer syntaxes are also supported at the framing
level: reading returns the compressed pixel stream as
:class:`~dicomforge.encapsulation.EncapsulatedPixelData` (a ``bytes`` subclass
that preserves fragment boundaries and the Basic Offset Table), and writing
re-emits fragments as an undefined-length item sequence.  This writer frames
already-compressed fragments — it does not compress pixels itself; use
:mod:`dicomforge.transcode` for the built-in RLE Lossless codec or the pydicom
backend for other codecs.

Values are surfaced as natural Python types: ``int``/``float`` for numeric VRs,
``str`` for text, ``bytes`` for binary VRs, :class:`~dicomforge.tags.Tag` for
``AT``, and a ``list`` of :class:`~dicomforge.dataset.DicomDataset` for ``SQ``.
"""

from __future__ import annotations

import struct
import zlib
import mmap
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from dicomforge.charset import PersonName, decode_text, encode_text
from dicomforge.dataset import DicomDataset, _deep_copy_value
from dicomforge.dictionary import (
    BYTES_VRS,
    CHARSET_TEXT_VRS,
    ITEM_DELIMITER_TAG,
    ITEM_TAG,
    LONG_FORM_VRS,
    NUMERIC_STRING_VRS,
    NUMERIC_VR_FORMATS,
    SEQUENCE_DELIMITER_TAG,
    SINGLE_VALUE_TEXT_VRS,
    TEXT_VRS,
    UNDEFINED_LENGTH,
    padding_byte,
    vr_for_tag,
    standard_dictionary,
)
from dicomforge.encapsulation import EncapsulatedPixelData, as_encapsulated
from dicomforge.errors import CharacterSetError, DicomValidationError
from dicomforge.tags import Tag
from dicomforge.uids import ImplementationUID, TransferSyntaxUID, is_valid_uid
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.storage import write_bytes

PathLike = Union[str, Path]
Buffer = Union[bytes, bytearray, mmap.mmap]

_PREAMBLE = b"\x00" * 128
_MAGIC = b"DICM"
_GROUP_LENGTH_TAG = Tag(0x0002, 0x0000)
_FILE_META_VERSION_TAG = Tag(0x0002, 0x0001)
_IMPLEMENTATION_VERSION_TAG = Tag(0x0002, 0x0013)
_FILE_META_GROUP = 0x0002
_LUT_DESCRIPTOR_TAGS = frozenset({Tag(0x0028, element) for element in (0x1101, 0x1102, 0x1103, 0x3002)})

#: Every VR code DicomForge recognises (used to sniff Explicit vs Implicit VR
#: when reading a bare, preamble-less data set with ``force=True``).
_ALL_VRS = (
    set(NUMERIC_VR_FORMATS)
    | set(TEXT_VRS)
    | set(BYTES_VRS)
    | {"SQ", "AT", "OB", "OW", "OF", "OD", "OL", "OV", "UN"}
)


class _Syntax:
    """Resolved byte-level encoding rules for a transfer syntax."""

    __slots__ = ("uid", "explicit", "endian", "deflated", "encapsulated")

    def __init__(self, uid: str) -> None:
        if not is_valid_uid(uid):
            raise DicomValidationError("Invalid Transfer Syntax UID")
        ts = TransferSyntax.from_uid(uid)
        self.uid = uid
        self.explicit = ts.is_explicit_vr
        self.endian = "<" if ts.is_little_endian else ">"
        self.deflated = uid == TransferSyntaxUID.DeflatedExplicitVRLittleEndian
        self.encapsulated = ts.is_encapsulated


_EXPLICIT_LE = _Syntax(TransferSyntaxUID.ExplicitVRLittleEndian)
_IMPLICIT_LE = _Syntax(TransferSyntaxUID.ImplicitVRLittleEndian)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_file(
    path: PathLike, *, stop_before_pixels: bool = False, force: bool = False
) -> DicomDataset:
    """Read a DICOM Part 10 file natively, without pydicom.

    Parameters
    ----------
    path:
        File system path to a ``.dcm`` file.
    stop_before_pixels:
        Stop reading once ``PixelData (7FE0,0010)`` is reached.  Useful for fast
        metadata scans.
    force:
        Read a data set that lacks the 128-byte preamble and ``DICM`` magic by
        auto-detecting Implicit vs Explicit VR Little Endian.
    """

    with Path(path).open("rb") as stream:
        if not Path(path).stat().st_size:
            raise DicomValidationError("Empty DICOM input")
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            dataset = loads(data, stop_before_pixels=stop_before_pixels, force=force)
    dataset.source_path = str(Path(path).resolve())
    return dataset


def write_file(
    path: PathLike,
    dataset: DicomDataset,
    *,
    transfer_syntax: Optional[str] = None,
    ensure_file_meta: bool = True,
    overwrite: bool = True,
) -> None:
    """Write *dataset* to *path* as a DICOM Part 10 file, without pydicom.

    Parameters
    ----------
    path:
        Destination file path.
    transfer_syntax:
        Transfer Syntax UID to encode with.  Defaults to the dataset's
        ``TransferSyntaxUID (0002,0010)`` if present, otherwise Explicit VR
        Little Endian.
    ensure_file_meta:
        When *True* (default) write the preamble, ``DICM`` magic, and a complete
        File Meta Information group.  When *False* write only the bare data set.
    """

    data = dumps(
        dataset, transfer_syntax=transfer_syntax, ensure_file_meta=ensure_file_meta
    )
    write_bytes(path, data, overwrite=overwrite)


def loads(
    data: Union[bytes, bytearray, mmap.mmap],
    *,
    stop_before_pixels: bool = False,
    force: bool = False,
    max_decompressed_bytes: int = 512 * 1024 * 1024,
) -> DicomDataset:
    """Parse an in-memory DICOM Part 10 byte string into a :class:`DicomDataset`."""

    buffer = data
    has_magic = len(buffer) >= 132 and buffer[128:132] == _MAGIC

    dataset = DicomDataset()
    if has_magic:
        meta, pos = _read_file_meta(buffer)
        for tag, value in meta.items():
            dataset.set(tag, value, vr=meta.vr(tag))
        transfer_syntax = meta.get(Tag.TransferSyntaxUID)
        if not transfer_syntax:
            raise DicomValidationError("File Meta Information requires TransferSyntaxUID")
        syntax = _Syntax(str(transfer_syntax))
        body = buffer
    elif force:
        syntax = _detect_syntax(buffer)
        body = buffer
        pos = 0
    else:
        raise DicomValidationError(
            "Not a DICOM Part 10 file (missing 'DICM' magic). Pass force=True to "
            "read a bare data set without File Meta Information."
        )

    charset = dataset.get(Tag.SpecificCharacterSet)
    if syntax.deflated:
        if max_decompressed_bytes <= 0:
            raise ValueError("max_decompressed_bytes must be positive")
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        try:
            body = decompressor.decompress(buffer[pos:], max_decompressed_bytes + 1)
        except zlib.error as exc:
            raise DicomValidationError("Invalid deflated DICOM data") from exc
        if len(body) > max_decompressed_bytes or decompressor.unconsumed_tail:
            raise DicomValidationError("Deflated DICOM exceeds decompressed byte limit")
        if not decompressor.eof:
            raise DicomValidationError("Truncated deflated DICOM data")
        pos = 0
        syntax = _EXPLICIT_LE

    main, _ = _read_elements(
        body, pos, len(body), syntax, charset, stop_before_pixels=stop_before_pixels
    )
    if not syntax.explicit:
        _resolve_implicit_signed_vrs(main, syntax)
    for tag, value in main.items():
        dataset.set(tag, value, vr=main.vr(tag))
    dataset._lexical.update(main._lexical)
    dataset.source_transfer_syntax = str(transfer_syntax) if has_magic else syntax.uid
    dataset.is_partial = stop_before_pixels
    return dataset


def dumps(
    dataset: DicomDataset,
    *,
    transfer_syntax: Optional[str] = None,
    ensure_file_meta: bool = True,
) -> bytes:
    """Serialise *dataset* to a DICOM Part 10 byte string."""

    transfer_syntax = (
        transfer_syntax
        or dataset.get(Tag.TransferSyntaxUID)
        or TransferSyntaxUID.ExplicitVRLittleEndian
    )
    syntax = _Syntax(str(transfer_syntax))
    if dataset.is_partial:
        raise DicomValidationError("Cannot save a metadata-only dataset; re-read the full file")
    source_uid = (dataset.source_transfer_syntax or dataset.get(Tag.TransferSyntaxUID)
                  or TransferSyntaxUID.ExplicitVRLittleEndian)
    source = _Syntax(str(source_uid))
    if source.encapsulated != syntax.encapsulated or (
        source.encapsulated and source.uid != syntax.uid
    ):
        if Tag.PixelData in dataset:
            raise DicomValidationError("Transfer syntax change requires explicit pixel transcoding")

    if source.endian != syntax.endian:
        dataset = _byte_swap_dataset(dataset, source, syntax)
        source = syntax
    charset = dataset.get(Tag.SpecificCharacterSet)
    body = bytearray()
    for tag in sorted(dataset.keys()):
        if ensure_file_meta and tag.group == _FILE_META_GROUP:
            continue
        if syntax.encapsulated and tag == Tag.PixelData:
            body += _encode_encapsulated(dataset[tag], syntax)
            continue
        vr = dataset.vr(tag)
        value = dataset[tag]
        lexical = dataset._lexical.get(tag)
        if lexical is not None and lexical[1] == value:
            value = lexical[0].decode("ascii")
        if source.endian != syntax.endian and isinstance(value, (bytes, bytearray)):
            widths = {"OW": 2, "OF": 4, "OL": 4, "OD": 8, "OV": 8}
            width = widths.get(vr)
            if width:
                if len(value) % width:
                    raise DicomValidationError("Binary value does not match its VR word size")
                value = b"".join(value[i:i + width][::-1] for i in range(0, len(value), width))
            elif vr == "UN" and dataset.source_transfer_syntax is not None:
                raise DicomValidationError("Cannot byte-swap an unknown VR safely")
        body += _encode_element(tag, vr, value, syntax, charset)

    if not ensure_file_meta:
        if syntax.uid not in (
            TransferSyntaxUID.ExplicitVRLittleEndian,
            TransferSyntaxUID.ImplicitVRLittleEndian,
        ):
            raise DicomValidationError(
                "Bare data sets without File Meta Information can only be "
                "written in Explicit VR Little Endian or Implicit VR Little "
                f"Endian; {transfer_syntax!r} cannot be auto-detected by "
                "loads(..., force=True)."
            )
        return bytes(body)

    if syntax.deflated:
        compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
        body = bytearray(compressor.compress(bytes(body)) + compressor.flush())

    meta = _build_file_meta(dataset, str(transfer_syntax))
    return _PREAMBLE + _MAGIC + meta + bytes(body)


# ---------------------------------------------------------------------------
# File Meta Information
# ---------------------------------------------------------------------------


def _read_file_meta(data: Buffer) -> Tuple[DicomDataset, int]:
    pos = 132
    _require_bytes(data, pos, 8, len(data))
    group, element = struct.unpack_from("<HH", data, pos)
    if (group, element) == (_GROUP_LENGTH_TAG.group, _GROUP_LENGTH_TAG.element):
        # Conformant fast path: (0002,0000) declares the group's byte length.
        _tag, _vr, length, value_pos = _read_header(data, pos, _EXPLICIT_LE)
        if _vr != "UL" or length != 4:
            raise DicomValidationError("Invalid File Meta Information group length")
        _require_bytes(data, value_pos, length, len(data))
        (group_length,) = struct.unpack_from("<I", data, value_pos)
        meta_start = value_pos + length
        meta_end = meta_start + group_length
        meta, _ = _read_elements(data, meta_start, meta_end, _EXPLICIT_LE, None)
        return meta, meta_end

    # Lenient fallback for files that omit the group-length element (e.g.
    # pydicom's legacy "write_like_original" output): read group-0002 elements
    # until the group number changes.
    meta = DicomDataset()
    while pos + 8 <= len(data):
        (peek_group,) = struct.unpack_from("<H", data, pos)
        if peek_group != _FILE_META_GROUP:
            break
        tag, vr, length, value_pos = _read_header(data, pos, _EXPLICIT_LE)
        if vr == "SQ" or length == UNDEFINED_LENGTH:
            value, pos = _read_sequence(data, value_pos, length, _EXPLICIT_LE, None)
        else:
            _require_bytes(data, value_pos, length, len(data))
            raw = bytes(data[value_pos : value_pos + length])
            value = _decode_value(vr or "UN", raw, _EXPLICIT_LE, None)
            pos = value_pos + length
        meta.set(tag, value, vr=vr)
    return meta, pos


def _build_file_meta(dataset: DicomDataset, transfer_syntax: str) -> bytes:
    sop_class = _required_value(dataset, Tag.MediaStorageSOPClassUID, Tag.SOPClassUID)
    sop_instance = _required_value(
        dataset, Tag.MediaStorageSOPInstanceUID, Tag.SOPInstanceUID
    )
    implementation = dataset.get(Tag.ImplementationClassUID, ImplementationUID.DicomForge)

    elements: List[Tuple[Tag, str, Any]] = [
        (_FILE_META_VERSION_TAG, "OB", b"\x00\x01"),
        (Tag.MediaStorageSOPClassUID, "UI", sop_class),
        (Tag.MediaStorageSOPInstanceUID, "UI", sop_instance),
        (Tag.TransferSyntaxUID, "UI", transfer_syntax),
        (Tag.ImplementationClassUID, "UI", implementation),
        (_IMPLEMENTATION_VERSION_TAG, "SH", "DICOMFORGE"),
    ]
    regenerated = {tag for tag, _, _ in elements} | {_GROUP_LENGTH_TAG}
    elements.extend((tag, dataset.vr(tag), dataset[tag]) for tag in dataset
                    if tag.group == 2 and tag not in regenerated)
    elements.sort(key=lambda element: element[0])

    meta_body = bytearray()
    for tag, vr, value in elements:
        meta_body += _encode_element(tag, vr, value, _EXPLICIT_LE, None)

    group_length = _encode_element(
        _GROUP_LENGTH_TAG, "UL", len(meta_body), _EXPLICIT_LE, None
    )
    return group_length + bytes(meta_body)


def _required_value(dataset: DicomDataset, primary: Tag, fallback: Tag) -> Any:
    value = dataset.get(primary)
    other = dataset.get(fallback)
    if value not in (None, "") and other not in (None, "") and str(value) != str(other):
        raise DicomValidationError(f"File meta identity {primary} conflicts with {fallback}")
    if value not in (None, ""):
        return value
    value = dataset.get(fallback)
    if value not in (None, ""):
        return value
    raise DicomValidationError(
        f"Writing a DICOM file requires {primary} or {fallback} for File Meta Information."
    )


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _require_bytes(data: Any, pos: int, length: int, end: int) -> None:
    if pos < 0 or length < 0 or pos + length > end or end > len(data):
        raise DicomValidationError(f"Truncated DICOM value or container at byte offset {pos}")


def _read_header(data: Buffer, pos: int, syntax: _Syntax) -> Tuple[Tag, Optional[str], int, int]:
    """Read one element header. Returns (tag, vr, value_length, new_pos)."""

    endian = syntax.endian
    _require_bytes(data, pos, 8, len(data))
    group, element = struct.unpack_from(endian + "HH", data, pos)
    pos += 4
    tag = Tag(group, element)

    if tag in (ITEM_TAG, ITEM_DELIMITER_TAG, SEQUENCE_DELIMITER_TAG):
        (length,) = struct.unpack_from(endian + "I", data, pos)
        return tag, None, length, pos + 4

    if syntax.explicit:
        try:
            vr = data[pos : pos + 2].decode("ascii")
        except UnicodeError as exc:
            raise DicomValidationError(f"Invalid VR at byte offset {pos}") from exc
        if vr not in _ALL_VRS:
            raise DicomValidationError(f"Unknown VR at byte offset {pos}")
        pos += 2
        if vr in LONG_FORM_VRS:
            _require_bytes(data, pos, 6, len(data))
            if data[pos:pos + 2] != b"\x00\x00":
                raise DicomValidationError(f"Invalid reserved bytes at offset {pos}")
            pos += 2  # two reserved bytes
            (length,) = struct.unpack_from(endian + "I", data, pos)
            pos += 4
        else:
            (length,) = struct.unpack_from(endian + "H", data, pos)
            pos += 2
    else:
        vr = vr_for_tag(tag)
        (length,) = struct.unpack_from(endian + "I", data, pos)
        pos += 4
    return tag, vr, length, pos


def _read_elements(
    data: Buffer,
    pos: int,
    end: int,
    syntax: _Syntax,
    charset: Any,
    *,
    stop_before_pixels: bool = False,
    delimiter: Optional[Tag] = None,
    depth: int = 0,
) -> Tuple[DicomDataset, int]:
    if depth > 64:
        raise DicomValidationError("DICOM nesting exceeds 64 levels")
    _require_bytes(data, pos, 0, end)
    dataset = DicomDataset()
    active_charset = charset
    while pos < end:
        _require_bytes(data, pos, 8, end)
        tag, vr, length, pos = _read_header(data, pos, syntax)
        _require_bytes(data, pos, 0, end)
        if tag in (ITEM_DELIMITER_TAG, SEQUENCE_DELIMITER_TAG):
            if tag != delimiter or length != 0:
                raise DicomValidationError(f"Unexpected delimiter at byte offset {pos}")
            return dataset, pos
        if stop_before_pixels and tag == Tag.PixelData:
            return dataset, pos

        value: Any
        if length == UNDEFINED_LENGTH and tag == Tag.PixelData:
            value, pos = _read_encapsulated(data, pos, syntax)
        elif vr == "SQ" or length == UNDEFINED_LENGTH:
            value, pos = _read_sequence(data, pos, length, syntax, active_charset,
                                         depth=depth + 1, end=end)
        else:
            _require_bytes(data, pos, length, end)
            raw = bytes(data[pos : pos + length])
            pos += length
            value = _decode_value(vr or "UN", raw, syntax, active_charset, tag=tag)

        dataset.set(tag, value, vr=vr)
        if vr in NUMERIC_STRING_VRS:
            dataset._lexical[tag] = (bytes(raw), _deep_copy_value(value))
        if tag == Tag.SpecificCharacterSet:
            active_charset = value
    if delimiter is not None:
        raise DicomValidationError("Missing DICOM item delimiter")
    return dataset, pos


def _resolve_implicit_signed_vrs(
    dataset: DicomDataset, syntax: _Syntax, pixel_representation: Optional[int] = None,
) -> None:
    """Resolve signed implicit VRs after local/ancestor pixel context is known.

    Ambiguous elements may precede PixelRepresentation or occur in a sequence
    before the parent's pixel module. Their provisional US decoding retains all
    bits, so it can be reinterpreted without losing values after parsing ends.
    Explicit VR input is never reinterpreted by this pass.
    """
    pixel_representation = dataset.get(Tag.PixelRepresentation, pixel_representation)
    dictionary = standard_dictionary()
    for tag, value in list(dataset.items()):
        entry = dictionary.get(f"{tag.group:04X}{tag.element:04X}")
        if entry and entry[0] == "US or SS" and pixel_representation is not None:
            resolved = vr_for_tag(tag, pixel_representation=pixel_representation)
            previous = dataset.vr(tag)
            if previous != resolved:
                if value is not None:
                    raw = _encode_numbers(previous, value, syntax.endian, tag=tag)
                    value = _decode_numbers(resolved, raw, syntax.endian, tag=tag)
                dataset.set(tag, value, vr=resolved)
        children = value if isinstance(value, (list, tuple)) else [value]
        for child in children:
            if isinstance(child, DicomDataset):
                _resolve_implicit_signed_vrs(child, syntax, pixel_representation)


def _read_sequence(
    data: Buffer, pos: int, seq_length: int, syntax: _Syntax, charset: Any,
    *, depth: int = 0, end: Optional[int] = None,
) -> Tuple[List[DicomDataset], int]:
    items: List[DicomDataset] = []
    container_end = len(data) if end is None else end
    seq_end = container_end if seq_length == UNDEFINED_LENGTH else pos + seq_length
    _require_bytes(data, pos, 0, seq_end)
    if seq_end > container_end:
        raise DicomValidationError("Sequence extends beyond its enclosing container")
    while pos < seq_end:
        tag, _vr, item_length, pos = _read_header(data, pos, syntax)
        if tag == SEQUENCE_DELIMITER_TAG:
            if seq_length != UNDEFINED_LENGTH or item_length != 0:
                raise DicomValidationError("Unexpected sequence delimiter")
            return items, pos
        if tag != ITEM_TAG:
            raise DicomValidationError(
                f"Expected a sequence Item (FFFE,E000) but found {tag}."
            )
        if item_length == UNDEFINED_LENGTH:
            item, pos = _read_elements(data, pos, seq_end, syntax, charset,
                                       delimiter=ITEM_DELIMITER_TAG, depth=depth)
        else:
            if pos + item_length > seq_end:
                raise DicomValidationError("Sequence item extends beyond its container")
            item, _ = _read_elements(data, pos, pos + item_length, syntax, charset, depth=depth)
            pos += item_length
        items.append(item)
    if seq_length == UNDEFINED_LENGTH:
        raise DicomValidationError("Missing DICOM sequence delimiter")
    return items, pos


def _read_encapsulated(
    data: Buffer, pos: int, syntax: _Syntax
) -> Tuple[EncapsulatedPixelData, int]:
    """Read undefined-length (encapsulated) pixel data, keeping fragments."""

    fragments: List[bytes] = []
    while pos < len(data):
        tag, _vr, length, pos = _read_header(data, pos, syntax)
        if tag == SEQUENCE_DELIMITER_TAG:
            if length != 0 or not fragments:
                raise DicomValidationError("Invalid encapsulated pixel delimiter or offset table")
            break
        if tag != ITEM_TAG:
            raise DicomValidationError(
                f"Expected an encapsulated pixel-data Item (FFFE,E000) but found {tag}."
            )
        _require_bytes(data, pos, length, len(data))
        if length % 2:
            raise DicomValidationError("Encapsulated fragment length must be even")
        fragments.append(bytes(data[pos : pos + length]))
        pos += length
    else:
        raise DicomValidationError("Missing encapsulated pixel-data delimiter")
    # Item 0 is the Basic Offset Table; the remaining items are pixel fragments.
    # A lone item (non-conformant file without an offset table) is treated as
    # the pixel fragment itself, matching the pre-0.11 flattened behaviour.
    if fragments:
        offsets = _parse_basic_offset_table(fragments[0], syntax)
        return EncapsulatedPixelData(fragments[1:], offsets), pos
    return EncapsulatedPixelData(fragments), pos


def _parse_basic_offset_table(raw: bytes, syntax: _Syntax) -> Tuple[int, ...]:
    if len(raw) % 4:
        raise DicomValidationError("Basic Offset Table length must be divisible by four")
    count = len(raw) // 4
    if count == 0:
        return ()
    return struct.unpack_from(syntax.endian + "I" * count, raw)


def _decode_value(
    vr: str, raw: bytes, syntax: _Syntax, charset: Any, *, tag: Optional[Tag] = None,
) -> Any:
    if vr in BYTES_VRS:
        return bytes(raw)
    if vr == "AT":
        return _decode_at(raw, syntax.endian)
    if vr in NUMERIC_VR_FORMATS:
        return _decode_numbers(vr, raw, syntax.endian, tag=tag)
    if vr in TEXT_VRS:
        return _decode_text(vr, raw, charset)
    return bytes(raw)


def _decode_at(raw: bytes, endian: str) -> Any:
    if len(raw) % 4:
        raise DicomValidationError("AT value length must be divisible by four")
    count = len(raw) // 4
    tags = []
    for index in range(count):
        group, element = struct.unpack_from(endian + "HH", raw, index * 4)
        tags.append(Tag(group, element))
    if not tags:
        return None
    return tags[0] if len(tags) == 1 else tags


def _decode_numbers(vr: str, raw: bytes, endian: str, *, tag: Optional[Tag] = None) -> Any:
    if vr == "SS" and tag in _LUT_DESCRIPTOR_TAGS and len(raw) == 6:
        # PS3.3 LUT descriptors: only the first mapped value is signed.
        return list(struct.unpack(endian + "HhH", raw))
    fmt = NUMERIC_VR_FORMATS[vr]
    size = struct.calcsize(endian + fmt)
    if len(raw) % size:
        raise DicomValidationError("Numeric value length does not match its VR")
    count = len(raw) // size
    if count == 0:
        return None
    values = list(struct.unpack_from(endian + fmt * count, raw))
    return values[0] if count == 1 else values


def _decode_text(vr: str, raw: bytes, charset: Any) -> Any:
    text = _decode_charset(raw, charset)
    text = text.rstrip("\x00") if vr == "UI" else text.rstrip("\x00 ")
    if vr in NUMERIC_STRING_VRS:
        return _parse_number_string(vr, text)
    if vr not in SINGLE_VALUE_TEXT_VRS and "\\" in text:
        return text.split("\\")
    return text


def _decode_charset(raw: bytes, charset: Any) -> str:
    if raw.isascii() and b"\x1b" not in raw:
        return raw.decode("ascii")
    return decode_text(raw, charset)


def _parse_number_string(vr: str, text: str) -> Any:
    parts = text.split("\\") if "\\" in text else [text]
    converter = int if vr == "IS" else float
    values = []
    for part in parts:
        cleaned = part.strip()
        if cleaned == "":
            continue
        values.append(converter(cleaned))
    if not values:
        return ""
    return values[0] if len(values) == 1 else values


def _detect_syntax(data: Buffer) -> _Syntax:
    if len(data) >= 6:
        candidate = data[4:6]
        try:
            vr = candidate.decode("ascii")
        except UnicodeDecodeError:
            vr = ""
        if vr.isalpha() and vr.upper() in _ALL_VRS:
            return _EXPLICIT_LE
    return _IMPLICIT_LE


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _encode_element(tag: Tag, vr: str, value: Any, syntax: _Syntax, charset: Any) -> bytes:
    value_bytes = _encode_value(tag, vr, value, syntax, charset)
    if len(value_bytes) % 2 == 1:
        value_bytes += padding_byte(vr)

    endian = syntax.endian
    header = struct.pack(endian + "HH", tag.group, tag.element)
    if syntax.explicit:
        header += vr.encode("ascii")
        if vr in LONG_FORM_VRS:
            header += b"\x00\x00" + struct.pack(endian + "I", len(value_bytes))
        else:
            if len(value_bytes) > 0xFFFF:
                raise DicomValidationError(
                    f"Value for {tag} is too long ({len(value_bytes)} bytes) for VR "
                    f"{vr!r} with a 16-bit length field."
                )
            header += struct.pack(endian + "H", len(value_bytes))
    else:
        header += struct.pack(endian + "I", len(value_bytes))
    return header + value_bytes


def _encode_value(tag: Tag, vr: str, value: Any, syntax: _Syntax, charset: Any) -> bytes:
    if value is None or (isinstance(value, str) and not value):
        return b""
    if vr == "SQ":
        return _encode_sequence(value, syntax, charset)
    if vr in BYTES_VRS:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        # Unknown/private tags (VR "UN") often hold opaque text supplied as a
        # Python str. Preserve it as UTF-8 bytes rather than failing the write.
        if vr == "UN" and isinstance(value, str):
            return value.encode("utf-8")
        raise DicomValidationError(
            f"VR {vr!r} for {tag} expects bytes, got {type(value).__name__}."
        )
    if vr == "AT":
        return _encode_at(value, syntax.endian)
    if vr in NUMERIC_VR_FORMATS:
        return _encode_numbers(vr, value, syntax.endian, tag=tag)
    if vr in TEXT_VRS:
        return _encode_text(vr, value, charset)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise DicomValidationError(f"Cannot encode value for {tag} with VR {vr!r}.")


def _encode_encapsulated(value: Any, syntax: _Syntax) -> bytes:
    """Encode PixelData for an encapsulated (compressed) transfer syntax.

    The value must already be compressed: an
    :class:`~dicomforge.encapsulation.EncapsulatedPixelData`, a list/tuple of
    fragment byte strings (one fragment per frame), or plain ``bytes`` holding
    a single fragment.  This frames the fragments as an undefined-length item
    sequence with a Basic Offset Table (PS3.5 Annex A.4); it does not compress
    pixels — use :mod:`dicomforge.transcode` or ``backend="pydicom"`` for that.
    """

    encapsulated = as_encapsulated(value)
    if encapsulated is None:
        if isinstance(value, (bytes, bytearray)):
            encapsulated = EncapsulatedPixelData([bytes(value)], (0,))
        else:
            raise DicomValidationError(
                "Encapsulated transfer syntaxes require compressed PixelData as "
                "EncapsulatedPixelData, a list of fragment bytes, or a single "
                f"fragment of bytes; got {type(value).__name__}. Compress with "
                "dicomforge.transcode.compress_pixel_data (RLE Lossless) or use "
                "backend='pydicom'."
            )

    endian = syntax.endian
    out = bytearray()
    out += struct.pack(endian + "HH", Tag.PixelData.group, Tag.PixelData.element)
    if syntax.explicit:
        out += b"OB\x00\x00" + struct.pack(endian + "I", UNDEFINED_LENGTH)
    else:
        out += struct.pack(endian + "I", UNDEFINED_LENGTH)

    offset_table = struct.pack(
        endian + "I" * len(encapsulated.basic_offset_table),
        *encapsulated.basic_offset_table,
    )
    for payload in (offset_table, *encapsulated.fragments):
        if len(payload) % 2 == 1:
            payload = payload + b"\x00"
        out += struct.pack(endian + "HH", ITEM_TAG.group, ITEM_TAG.element)
        out += struct.pack(endian + "I", len(payload))
        out += payload
    out += struct.pack(
        endian + "HH", SEQUENCE_DELIMITER_TAG.group, SEQUENCE_DELIMITER_TAG.element
    )
    out += struct.pack(endian + "I", 0)
    return bytes(out)


def _encode_sequence(value: Any, syntax: _Syntax, charset: Any) -> bytes:
    if value is None:
        return b""
    items = value if isinstance(value, (list, tuple)) else [value]
    out = bytearray()
    for item in items:
        if not isinstance(item, DicomDataset):
            raise DicomValidationError(
                "Sequence items must be DicomDataset instances; "
                f"got {type(item).__name__}."
            )
        item_charset = item.get(Tag.SpecificCharacterSet, charset)
        body = bytearray()
        for tag in sorted(item.keys()):
            vr = item.vr(tag)
            value = item[tag]
            lexical = item._lexical.get(tag)
            if lexical is not None and lexical[1] == value:
                value = lexical[0].decode("ascii")
            body += _encode_element(tag, vr, value, syntax, item_charset)
        out += struct.pack(syntax.endian + "HH", ITEM_TAG.group, ITEM_TAG.element)
        out += struct.pack(syntax.endian + "I", len(body))
        out += body
    return bytes(out)


def _encode_at(value: Any, endian: str) -> bytes:
    values = value if isinstance(value, (list, tuple)) else [value]
    out = bytearray()
    for item in values:
        tag = Tag.parse(item)
        out += struct.pack(endian + "HH", tag.group, tag.element)
    return bytes(out)


def _encode_numbers(vr: str, value: Any, endian: str, *, tag: Optional[Tag] = None) -> bytes:
    fmt = NUMERIC_VR_FORMATS[vr]
    values = value if isinstance(value, (list, tuple)) else [value]
    if vr == "SS" and tag in _LUT_DESCRIPTOR_TAGS and len(values) == 3:
        return struct.pack(endian + "HhH", *(int(item) for item in values))
    converter = float if vr in ("FL", "FD") else int
    packed = bytearray()
    for item in values:
        packed += struct.pack(endian + fmt, converter(item))
    return bytes(packed)


def _encode_text(vr: str, value: Any, charset: Any) -> bytes:
    if isinstance(value, PersonName):
        text = value.to_dicom_string()
    elif isinstance(value, (list, tuple)):
        text = "\\".join(_format_text_item(vr, item) for item in value)
    else:
        text = _format_text_item(vr, value)

    if vr == "UI" or vr not in CHARSET_TEXT_VRS:
        try:
            return text.encode("ascii")
        except UnicodeEncodeError as exc:
            raise CharacterSetError(
                f"VR {vr!r} value {text!r} must be ASCII."
            ) from exc

    try:
        return encode_text(text, charset)
    except CharacterSetError:
        if text.isascii():
            return text.encode("ascii")
        raise


def _format_text_item(vr: str, value: Any) -> str:
    if isinstance(value, PersonName):
        return value.to_dicom_string()
    if vr == "DS":
        return _format_decimal_string(value)
    if vr == "IS":
        return str(value) if isinstance(value, str) else str(int(value))
    return str(value)


def _format_decimal_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    text = repr(float(value))
    if len(text) <= 16:
        return text
    return f"{float(value):.10E}"


def _byte_swap_dataset(dataset: DicomDataset, source: _Syntax, target: _Syntax) -> DicomDataset:
    """Convert endian-sensitive raw VR values recursively without mutating input."""
    copied = dataset.copy(deep=True)
    widths = {"OW": 2, "OF": 4, "OL": 4, "OD": 8, "OV": 8}
    for path, element in list(copied.iter_paths()):
        value = element.value
        if not isinstance(value, (bytes, bytearray)):
            continue
        width = widths.get(element.vr)
        if element.vr == "UN" and dataset.source_transfer_syntax is not None:
            raise DicomValidationError("Cannot byte-swap unknown VR safely; retain source syntax")
        if width is None:
            continue
        if len(value) % width:
            raise DicomValidationError("Binary VR value has an invalid word length")
        parent = copied
        for index in range(0, len(path) - 1, 2):
            parent = parent[path[index]][path[index + 1]]
        parent.set(element.tag, b"".join(value[i:i + width][::-1]
                                         for i in range(0, len(value), width)))
    copied.source_transfer_syntax = target.uid
    return copied
