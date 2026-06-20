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

Encapsulated (compressed) transfer syntaxes carry pixel data this writer does
not re-encode.  Such files can still be *read* — the compressed pixel stream is
returned as ``bytes`` — but writing them requires the pydicom backend
(``backend="pydicom"``), which round-trips fragments faithfully.

Values are surfaced as natural Python types: ``int``/``float`` for numeric VRs,
``str`` for text, ``bytes`` for binary VRs, :class:`~dicomforge.tags.Tag` for
``AT``, and a ``list`` of :class:`~dicomforge.dataset.DicomDataset` for ``SQ``.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Any, List, Optional, Tuple, Union

from dicomforge.charset import PersonName, decode_text, encode_text
from dicomforge.dataset import DicomDataset
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
)
from dicomforge.errors import CharacterSetError, DicomValidationError
from dicomforge.tags import Tag
from dicomforge.uids import ImplementationUID, TransferSyntaxUID
from dicomforge.transfer_syntax import TransferSyntax

PathLike = Union[str, Path]

_PREAMBLE = b"\x00" * 128
_MAGIC = b"DICM"
_GROUP_LENGTH_TAG = Tag(0x0002, 0x0000)
_FILE_META_VERSION_TAG = Tag(0x0002, 0x0001)
_IMPLEMENTATION_VERSION_TAG = Tag(0x0002, 0x0013)
_FILE_META_GROUP = 0x0002

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

    data = Path(path).read_bytes()
    return loads(data, stop_before_pixels=stop_before_pixels, force=force)


def write_file(
    path: PathLike,
    dataset: DicomDataset,
    *,
    transfer_syntax: Optional[str] = None,
    ensure_file_meta: bool = True,
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
    Path(path).write_bytes(data)


def loads(
    data: Union[bytes, bytearray],
    *,
    stop_before_pixels: bool = False,
    force: bool = False,
) -> DicomDataset:
    """Parse an in-memory DICOM Part 10 byte string into a :class:`DicomDataset`."""

    buffer = bytes(data)
    has_magic = len(buffer) >= 132 and buffer[128:132] == _MAGIC

    dataset = DicomDataset()
    if has_magic:
        meta, pos = _read_file_meta(buffer)
        for tag, value in meta.items():
            dataset.set((tag.group, tag.element), value)
        transfer_syntax = (
            meta.get(Tag.TransferSyntaxUID) or TransferSyntaxUID.ExplicitVRLittleEndian
        )
        syntax = _Syntax(str(transfer_syntax))
        body = buffer[pos:]
    elif force:
        syntax = _detect_syntax(buffer)
        body = buffer
    else:
        raise DicomValidationError(
            "Not a DICOM Part 10 file (missing 'DICM' magic). Pass force=True to "
            "read a bare data set without File Meta Information."
        )

    charset = dataset.get(Tag.SpecificCharacterSet)
    if syntax.deflated:
        body = zlib.decompress(body, -zlib.MAX_WBITS)
        syntax = _EXPLICIT_LE

    main, _ = _read_elements(
        body, 0, len(body), syntax, charset, stop_before_pixels=stop_before_pixels
    )
    for tag, value in main.items():
        dataset.set((tag.group, tag.element), value)
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
    if syntax.encapsulated:
        raise DicomValidationError(
            "The native writer cannot encode the encapsulated (compressed) "
            f"transfer syntax {transfer_syntax!r}. Use backend='pydicom' to write "
            "compressed pixel data."
        )

    charset = dataset.get(Tag.SpecificCharacterSet)
    bits_allocated = dataset.get(Tag.BitsAllocated)
    body = bytearray()
    for tag in sorted(dataset.keys()):
        if ensure_file_meta and tag.group == _FILE_META_GROUP:
            continue
        vr = vr_for_tag(tag, bits_allocated=bits_allocated)
        body += _encode_element(tag, vr, dataset[tag], syntax, charset)

    if syntax.deflated:
        compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
        body = bytearray(compressor.compress(bytes(body)) + compressor.flush())

    if not ensure_file_meta:
        return bytes(body)

    meta = _build_file_meta(dataset, str(transfer_syntax))
    return _PREAMBLE + _MAGIC + meta + bytes(body)


# ---------------------------------------------------------------------------
# File Meta Information
# ---------------------------------------------------------------------------


def _read_file_meta(data: bytes) -> Tuple[DicomDataset, int]:
    pos = 132
    group, element = struct.unpack_from("<HH", data, pos)
    if (group, element) == (_GROUP_LENGTH_TAG.group, _GROUP_LENGTH_TAG.element):
        # Conformant fast path: (0002,0000) declares the group's byte length.
        _tag, _vr, length, value_pos = _read_header(data, pos, _EXPLICIT_LE)
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
            raw = data[value_pos : value_pos + length]
            value = _decode_value(vr or "UN", raw, _EXPLICIT_LE, None)
            pos = value_pos + length
        meta.set((tag.group, tag.element), value)
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

    meta_body = bytearray()
    for tag, vr, value in elements:
        meta_body += _encode_element(tag, vr, value, _EXPLICIT_LE, None)

    group_length = _encode_element(
        _GROUP_LENGTH_TAG, "UL", len(meta_body), _EXPLICIT_LE, None
    )
    return group_length + bytes(meta_body)


def _required_value(dataset: DicomDataset, primary: Tag, fallback: Tag) -> Any:
    value = dataset.get(primary)
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


def _read_header(data: bytes, pos: int, syntax: _Syntax) -> Tuple[Tag, Optional[str], int, int]:
    """Read one element header. Returns (tag, vr, value_length, new_pos)."""

    endian = syntax.endian
    group, element = struct.unpack_from(endian + "HH", data, pos)
    pos += 4
    tag = Tag(group, element)

    if tag in (ITEM_TAG, ITEM_DELIMITER_TAG, SEQUENCE_DELIMITER_TAG):
        (length,) = struct.unpack_from(endian + "I", data, pos)
        return tag, None, length, pos + 4

    if syntax.explicit:
        vr = data[pos : pos + 2].decode("ascii")
        pos += 2
        if vr in LONG_FORM_VRS:
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
    data: bytes,
    pos: int,
    end: int,
    syntax: _Syntax,
    charset: Any,
    *,
    stop_before_pixels: bool = False,
) -> Tuple[DicomDataset, int]:
    dataset = DicomDataset()
    active_charset = charset
    while pos < end and end - pos >= 8:
        tag, vr, length, pos = _read_header(data, pos, syntax)
        if tag in (ITEM_DELIMITER_TAG, SEQUENCE_DELIMITER_TAG):
            return dataset, pos
        if stop_before_pixels and tag == Tag.PixelData:
            return dataset, pos

        if length == UNDEFINED_LENGTH and tag == Tag.PixelData:
            value, pos = _read_encapsulated(data, pos, syntax)
        elif vr == "SQ" or length == UNDEFINED_LENGTH:
            value, pos = _read_sequence(data, pos, length, syntax, active_charset)
        else:
            raw = data[pos : pos + length]
            pos += length
            value = _decode_value(vr or "UN", raw, syntax, active_charset)

        dataset.set((tag.group, tag.element), value)
        if tag == Tag.SpecificCharacterSet:
            active_charset = value
    return dataset, pos


def _read_sequence(
    data: bytes, pos: int, seq_length: int, syntax: _Syntax, charset: Any
) -> Tuple[List[DicomDataset], int]:
    items: List[DicomDataset] = []
    seq_end = len(data) if seq_length == UNDEFINED_LENGTH else pos + seq_length
    while pos < seq_end:
        tag, _vr, item_length, pos = _read_header(data, pos, syntax)
        if tag == SEQUENCE_DELIMITER_TAG:
            break
        if tag != ITEM_TAG:
            raise DicomValidationError(
                f"Expected a sequence Item (FFFE,E000) but found {tag}."
            )
        if item_length == UNDEFINED_LENGTH:
            item, pos = _read_elements(data, pos, len(data), syntax, charset)
        else:
            item, _ = _read_elements(data, pos, pos + item_length, syntax, charset)
            pos += item_length
        items.append(item)
    return items, pos


def _read_encapsulated(data: bytes, pos: int, syntax: _Syntax) -> Tuple[bytes, int]:
    """Read undefined-length (encapsulated) pixel data into flattened bytes."""

    fragments: List[bytes] = []
    while pos < len(data):
        tag, _vr, length, pos = _read_header(data, pos, syntax)
        if tag == SEQUENCE_DELIMITER_TAG:
            break
        if tag != ITEM_TAG:
            raise DicomValidationError(
                f"Expected an encapsulated pixel-data Item (FFFE,E000) but found {tag}."
            )
        fragments.append(bytes(data[pos : pos + length]))
        pos += length
    # Fragment 0 is the Basic Offset Table; the remaining fragments are pixels.
    if len(fragments) > 1:
        return b"".join(fragments[1:]), pos
    return (fragments[0] if fragments else b""), pos


def _decode_value(vr: str, raw: bytes, syntax: _Syntax, charset: Any) -> Any:
    if vr in BYTES_VRS:
        return bytes(raw)
    if vr == "AT":
        return _decode_at(raw, syntax.endian)
    if vr in NUMERIC_VR_FORMATS:
        return _decode_numbers(vr, raw, syntax.endian)
    if vr in TEXT_VRS:
        return _decode_text(vr, raw, charset)
    return bytes(raw)


def _decode_at(raw: bytes, endian: str) -> Any:
    count = len(raw) // 4
    tags = []
    for index in range(count):
        group, element = struct.unpack_from(endian + "HH", raw, index * 4)
        tags.append(Tag(group, element))
    if not tags:
        return None
    return tags[0] if len(tags) == 1 else tags


def _decode_numbers(vr: str, raw: bytes, endian: str) -> Any:
    fmt = NUMERIC_VR_FORMATS[vr]
    size = struct.calcsize(endian + fmt)
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
    try:
        return decode_text(raw, charset)
    except CharacterSetError:
        return raw.decode("ascii", errors="replace")


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


def _detect_syntax(data: bytes) -> _Syntax:
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
        return _encode_numbers(vr, value, syntax.endian)
    if vr in TEXT_VRS:
        return _encode_text(vr, value, charset)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    raise DicomValidationError(f"Cannot encode value for {tag} with VR {vr!r}.")


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
        item_bits = item.get(Tag.BitsAllocated)
        body = bytearray()
        for tag in sorted(item.keys()):
            vr = vr_for_tag(tag, bits_allocated=item_bits)
            body += _encode_element(tag, vr, item[tag], syntax, item_charset)
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


def _encode_numbers(vr: str, value: Any, endian: str) -> bytes:
    fmt = NUMERIC_VR_FORMATS[vr]
    values = value if isinstance(value, (list, tuple)) else [value]
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
