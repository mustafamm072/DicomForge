"""Adoption-layer integration adapters.

Bridges DicomDataset with the wider Python ecosystem:

- **pydicom** — bidirectional conversion so you can adopt DicomForge
  alongside an existing pydicom codebase without rewriting everything.
- **numpy** — extract pixel arrays from uncompressed PixelData with
  correct dtype, shape, and optional rescale/window application.
- **Pillow** — convert a DICOM frame to a PIL Image ready for display
  or export; handles MONOCHROME inversion automatically.
- **JSON** — round-trip through the DICOM JSON Model (PS3.18 Annex F).

No backend is imported at module level.  Each function raises
``MissingBackendError`` with a ``pip install`` hint when the backend is
absent, so the core stays dependency-free.

Example
-------
Convert a pydicom Dataset you already have::

    from dicomforge.adapt import from_pydicom, to_pydicom

    ds_forge = from_pydicom(raw_pydicom_dataset)
    raw_back  = to_pydicom(ds_forge)

Extract a numpy array (requires ``pip install dicomforge[pixels]``)::

    from dicomforge.adapt import pixel_array
    arr = pixel_array(ds_forge, frame=0)

Display a DICOM frame via Pillow::

    from dicomforge.adapt import to_pil_image
    to_pil_image(ds_forge).show()

Create a lightweight JPEG preview for web/API responses::

    from dicomforge.adapt import to_jpeg_preview
    preview_bytes = to_jpeg_preview(ds_forge, quality=85)
"""

from __future__ import annotations

import json as _json
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, List, Optional, Union

from dicomforge.dataset import DicomDataset
from dicomforge.dicomweb import dataset_from_dicom_json, dataset_to_dicom_json
from dicomforge.errors import (
    DicomValidationError,
    MissingBackendError,
    UnsupportedTransferSyntaxError,
)
from dicomforge.pixels import (
    FrameMetadata,
    is_monochrome,
    needs_inversion,
)
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import TransferSyntaxUID

PathLike = Union[str, Path]

# ---------------------------------------------------------------------------
# pydicom adapters
# ---------------------------------------------------------------------------


def from_pydicom(raw: Any) -> DicomDataset:
    """Convert a ``pydicom.Dataset`` (or ``FileDataset``) to a :class:`DicomDataset`.

    Both the main dataset and the ``file_meta`` group-0002 elements are
    copied.  Nested sequences are converted recursively.

    Raises
    ------
    MissingBackendError
        If pydicom is not installed (used only for type-checking here, not
        for the actual import — pass in whatever pydicom gave you).
    """
    dataset = DicomDataset()
    file_meta = getattr(raw, "file_meta", None)
    if file_meta is not None:
        _copy_pydicom_to_forge(file_meta, dataset)
    _copy_pydicom_to_forge(raw, dataset)
    return dataset


def to_pydicom(dataset: DicomDataset, *, write_like_original: bool = False) -> Any:
    """Convert a :class:`DicomDataset` to a ``pydicom.Dataset``.

    Requires ``pip install dicomforge[pydicom]``.

    Parameters
    ----------
    dataset:
        The DicomForge dataset to convert.
    write_like_original:
        Passed through to ``pydicom.Dataset`` — has no effect on the
        returned object type but is available for callers who pass the
        result to ``pydicom.dcmwrite``.

    Returns
    -------
    pydicom.Dataset
        A new pydicom Dataset populated with the same tags and values.
    """
    try:
        import pydicom
    except ImportError as exc:
        raise MissingBackendError(
            "to_pydicom() requires the optional pydicom backend. "
            "Install with `pip install dicomforge[pydicom]`."
        ) from exc

    raw = pydicom.Dataset()
    for tag, value in dataset.items():
        if tag.group == 0x0002:
            if not hasattr(raw, "file_meta"):
                raw.file_meta = pydicom.dataset.FileMetaDataset()
            raw.file_meta.add_new((tag.group, tag.element), dataset.vr(tag), value)
            continue
        vr = dataset.vr(tag)
        converted = _forge_value_to_pydicom(value, pydicom)
        lexical = dataset._lexical.get(tag)
        if lexical is not None and lexical[1] == value:
            converted = lexical[0].decode("ascii")
        if tag == Tag.PixelData:
            from dicomforge.encapsulation import as_encapsulated
            structured = as_encapsulated(value)
            if structured is not None:
                from dicomforge.part10 import _encode_encapsulated, _EXPLICIT_LE
                converted = _encode_encapsulated(structured, _EXPLICIT_LE)[12:-8]
        raw.add_new((tag.group, tag.element), vr, converted)
        if tag == Tag.PixelData and dataset.get(Tag.TransferSyntaxUID):
            raw[(tag.group, tag.element)].is_undefined_length = TransferSyntax.from_uid(
                str(dataset[Tag.TransferSyntaxUID])).is_encapsulated
    return raw


# ---------------------------------------------------------------------------
# numpy adapters
# ---------------------------------------------------------------------------


def pixel_array(
    dataset: DicomDataset,
    *,
    frame: int = 0,
    apply_rescale: bool = False,
    registry: Any = None,
    max_frame_bytes: int = 512 * 1024 * 1024,
) -> Any:
    """Extract one frame of PixelData as a ``numpy.ndarray``.

    The returned array has shape ``(rows, columns)`` for single-sample images
    or ``(rows, columns, samples)`` for colour images, and the dtype matches
    ``BitsAllocated`` (``uint8``, ``uint16``, ``int16``, ``int32`` for signed
    data).  Native uncompressed data is decoded directly, and RLE Lossless is
    decoded by the built-in dependency-free codec (:mod:`dicomforge.rle`).
    Other encapsulated compressed syntaxes are delegated to pydicom when
    pydicom and the required pydicom pixel plugin are installed.

    Parameters
    ----------
    dataset:
        Dataset containing ``PixelData`` and pixel-metadata tags.
    frame:
        Zero-based frame index.  Defaults to 0 (first frame).
    apply_rescale:
        When *True*, apply ``RescaleSlope`` / ``RescaleIntercept`` and return
        ``float64``.  Useful for CT Hounsfield Units.
    registry:
        Optional :class:`~dicomforge.codecs.CodecRegistry` to use when
        checking codec support.  Defaults to the built-in uncompressed registry.

    Raises
    ------
    MissingBackendError
        If numpy is not installed.
    PixelMetadataError
        If required pixel-metadata tags are missing or inconsistent.
    UnsupportedTransferSyntaxError
        If the transfer syntax requires a codec not in *registry*, or if
        pydicom cannot decode a compressed frame with the installed plugins.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingBackendError(
            "pixel_array() requires numpy. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    from dicomforge.codecs import default_registry
    from dicomforge.pixels import check_pixel_capability

    active_registry = registry or default_registry()
    cap = check_pixel_capability(dataset, registry=active_registry)
    meta = cap.frame_metadata
    _check_frame_budget(meta, max_frame_bytes)
    _validate_frame_index(frame, meta.number_of_frames)
    codec = active_registry.find(cap.transfer_syntax, dataset=dataset)
    if codec.decode_frame is not None:
        return _apply_rescale_if_requested(np.asarray(codec.decode_frame(dataset, frame)),
                                           dataset, apply_rescale, np)

    if cap.transfer_syntax.is_compressed:
        fragments = _rle_fragments_or_none(dataset, meta, cap.transfer_syntax)
        if fragments is not None:
            return _rle_pixel_array(
                fragments[frame], dataset, meta, cap.transfer_syntax, apply_rescale, np
            )
        selected = _pydicom_pixel_array(dataset, np, frame=frame)
        return _apply_rescale_if_requested(selected, dataset, apply_rescale, np)

    return _native_pixel_array(dataset, meta, cap.transfer_syntax, frame, apply_rescale, np)


def iter_pixel_frames(
    dataset: DicomDataset,
    *,
    apply_rescale: bool = False,
    registry: Any = None,
    max_frame_bytes: int = 512 * 1024 * 1024,
) -> Iterator[Any]:
    """Yield pixel frames one at a time as ``numpy.ndarray`` objects.

    For native uncompressed PixelData, frames are sliced from the source byte
    buffer without materialising the whole pixel stack.  RLE Lossless frames
    are decoded one fragment at a time by the built-in codec.  For other
    compressed syntaxes, decoding is delegated once to pydicom and frames are
    then yielded from the decoded result.  This keeps the API lightweight while giving
    callers a memory-conscious path for ordinary multiframe native datasets.

    Requires ``pip install dicomforge[pixels]``.  Compressed syntaxes also
    require ``pip install dicomforge[pydicom]`` plus the pydicom codec backend
    for the transfer syntax.
    """
    try:
        import numpy as np
    except ImportError as exc:
        raise MissingBackendError(
            "iter_pixel_frames() requires numpy. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    from dicomforge.codecs import default_registry
    from dicomforge.pixels import check_pixel_capability

    active_registry = registry or default_registry()
    cap = check_pixel_capability(dataset, registry=active_registry)
    meta = cap.frame_metadata
    _check_frame_budget(meta, max_frame_bytes)
    codec = active_registry.find(cap.transfer_syntax, dataset=dataset)
    if codec.decode_frame is not None:
        for index in range(meta.number_of_frames):
            yield _apply_rescale_if_requested(np.asarray(codec.decode_frame(dataset, index)),
                                              dataset, apply_rescale, np)
        return

    if cap.transfer_syntax.is_compressed:
        fragments = _rle_fragments_or_none(dataset, meta, cap.transfer_syntax)
        if fragments is not None:
            for fragment in fragments:
                yield _rle_pixel_array(
                    fragment, dataset, meta, cap.transfer_syntax, apply_rescale, np
                )
            return
        raw = to_pydicom(dataset)
        _ensure_raw_transfer_syntax(raw, str(dataset[Tag.TransferSyntaxUID]))
        import pydicom
        if hasattr(pydicom, "pixels"):
            frames = pydicom.pixels.iter_pixels(raw, raw=True)
        else:
            arr = np.asarray(raw.pixel_array)
            frames = (_select_frame(arr, meta, index) for index in range(meta.number_of_frames))
        for selected in frames:
            yield _apply_rescale_if_requested(selected, dataset, apply_rescale, np)
        return

    for frame_index in range(meta.number_of_frames):
        yield _native_pixel_array(
            dataset,
            meta,
            cap.transfer_syntax,
            frame_index,
            apply_rescale,
            np,
        )


def _native_pixel_array(
    dataset: DicomDataset,
    meta: FrameMetadata,
    transfer_syntax: TransferSyntax,
    frame: int,
    apply_rescale: bool,
    np: Any,
) -> Any:
    _validate_frame_index(frame, meta.number_of_frames)

    pixel_data = dataset.require(Tag.PixelData)
    if isinstance(pixel_data, bytes):
        raw_bytes = pixel_data
    elif isinstance(pixel_data, bytearray):
        raw_bytes = bytes(pixel_data)
    else:
        raise TypeError(f"PixelData must be bytes or bytearray, got {type(pixel_data).__name__}")

    if meta.bits_allocated == 1:
        start = frame * meta.frame_values
        first, last = start // 8, (start + meta.frame_values + 7) // 8
        unpacked = np.unpackbits(np.frombuffer(raw_bytes[first:last], dtype=np.uint8),
                                 bitorder="little")
        frame_flat = unpacked[start % 8:start % 8 + meta.frame_values]
    elif meta.photometric_interpretation == "YBR_FULL_422":
        if meta.bits_allocated != 8 or meta.columns % 2:
            raise DicomValidationError("Native YBR_FULL_422 requires 8-bit even-column images")
        pairs = np.frombuffer(raw_bytes, dtype=np.uint8, count=meta.frame_pixels * 2,
                              offset=frame * meta.expected_frame_bytes).reshape(-1, 4)
        expanded = np.empty((len(pairs), 2, 3), dtype=np.uint8)
        expanded[:, 0, 0], expanded[:, 1, 0] = pairs[:, 0], pairs[:, 1]
        expanded[:, :, 1], expanded[:, :, 2] = pairs[:, 2, None], pairs[:, 3, None]
        frame_flat = expanded.reshape(-1)
    else:
        dtype = _numpy_dtype(meta, transfer_syntax)
        frame_flat = np.frombuffer(raw_bytes, dtype=dtype, count=meta.frame_values,
                                   offset=frame * meta.expected_frame_bytes)
        frame_flat = _normalize_stored_bits(frame_flat, meta, np)

    if meta.samples_per_pixel == 1:
        arr = frame_flat.reshape(meta.rows, meta.columns)
    else:
        if meta.planar_configuration == 1:
            # Plane-interleaved: [R…R, G…G, B…B] → reshape then transpose
            arr = frame_flat.reshape(meta.samples_per_pixel, meta.rows, meta.columns)
            arr = arr.transpose(1, 2, 0)
        else:
            # Pixel-interleaved: [RGB, RGB, …]
            arr = frame_flat.reshape(meta.rows, meta.columns, meta.samples_per_pixel)

    return _apply_rescale_if_requested(arr, dataset, apply_rescale, np)


# ---------------------------------------------------------------------------
# Pillow adapters
# ---------------------------------------------------------------------------


def to_pil_image(
    dataset: DicomDataset,
    *,
    frame: int = 0,
    apply_window: bool = True,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
) -> Any:
    """Convert a DICOM frame to a ``PIL.Image.Image``.

    For monochrome images the output mode is ``'L'`` (8-bit greyscale).
    For colour images the output mode is ``'RGB'``.  YBR colour spaces
    (``YBR_FULL``, ``YBR_FULL_422``, ``YBR_PARTIAL_422``) are converted to
    RGB automatically so the returned image is always display-correct.

    ``MONOCHROME1`` (bright = air) is automatically inverted to display
    convention (bright = high density).

    Parameters
    ----------
    dataset:
        Dataset containing ``PixelData`` and required metadata tags.
    frame:
        Zero-based frame index.
    apply_window:
        Apply ``WindowCenter`` / ``WindowWidth`` VOI windowing when *True*.
        Pass explicit *window_center* and *window_width* to override the
        dataset values.
    window_center:
        Override ``WindowCenter``.  Ignored when *apply_window* is *False*.
    window_width:
        Override ``WindowWidth``.  Ignored when *apply_window* is *False*.

    Raises
    ------
    MissingBackendError
        If Pillow (PIL) or numpy is not installed.
    """
    try:
        from PIL import Image
    except ImportError as exc:
        raise MissingBackendError(
            "to_pil_image() requires Pillow. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    try:
        import numpy as np
    except ImportError as exc:
        raise MissingBackendError(
            "to_pil_image() requires numpy. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    arr = pixel_array(dataset, frame=frame, apply_rescale=True
                      if is_monochrome(str(dataset.get(Tag.PhotometricInterpretation))) else False)
    meta = FrameMetadata.from_dataset(dataset)
    photometric = meta.photometric_interpretation

    if is_monochrome(photometric):
        arr_float = arr.astype(np.float64)
        if apply_window:
            center = window_center
            width = window_width
            if center is None:
                raw_center = dataset.get(Tag.WindowCenter)
                center = float(_first(raw_center)) if raw_center is not None else float(arr_float.mean())
            if width is None:
                raw_width = dataset.get(Tag.WindowWidth)
                width = (
                    float(_first(raw_width))
                    if raw_width is not None
                    else float(arr_float.max() - arr_float.min()) or 1.0
                )
            arr_windowed = _apply_window_numpy(arr_float, center, width, np)
        else:
            vmin = float(arr_float.min())
            vmax = float(arr_float.max())
            span = vmax - vmin or 1.0
            arr_windowed = ((arr_float - vmin) / span * 255.0)

        arr_uint8 = arr_windowed.clip(0, 255).astype(np.uint8)
        if needs_inversion(photometric):
            arr_uint8 = 255 - arr_uint8
        return Image.fromarray(arr_uint8)

    # Colour path — convert YBR colour spaces to RGB before PIL sees the data.
    # PIL treats every (rows, cols, 3) uint8 array as RGB; passing raw YBR
    # samples would produce heavily tinted or incorrect images.
    arr = _ybr_to_rgb_if_needed(arr, photometric, np)

    # Ensure uint8 for PIL
    if arr.dtype != np.uint8:
        vmin = float(arr.min())
        vmax = float(arr.max())
        span = vmax - vmin or 1.0
        arr = ((arr.astype(np.float64) - vmin) / span * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr)


def to_jpeg_preview(
    dataset: DicomDataset,
    *,
    frame: int = 0,
    quality: int = 85,
    apply_window: bool = True,
    window_center: Optional[float] = None,
    window_width: Optional[float] = None,
    progressive: bool = False,
    optimize: bool = False,
) -> bytes:
    """Render one DICOM frame as 8-bit JPEG preview bytes.

    This is intended for thumbnails, web viewer previews, and API responses.
    It reuses :func:`to_pil_image`, so native uncompressed pixels are handled
    directly and compressed syntaxes are decoded through pydicom when the
    relevant optional codec plugin is installed.  The core package still has no
    mandatory NumPy, Pillow, pydicom, or codec dependency.

    Parameters
    ----------
    dataset:
        Dataset containing ``PixelData`` and required pixel metadata tags.
    frame:
        Zero-based frame index.
    quality:
        Pillow JPEG quality from 1 to 95.  Defaults to 85, which is a practical
        preview default without paying the size cost of near-lossless output.
    apply_window:
        Apply VOI windowing for monochrome images before encoding.
    window_center:
        Override ``WindowCenter`` when *apply_window* is true.
    window_width:
        Override ``WindowWidth`` when *apply_window* is true.
    progressive:
        Write a progressive JPEG.  Defaults to ``False`` for faster encoding.
    optimize:
        Ask Pillow to optimize Huffman tables.  Defaults to ``False`` because
        it can add CPU cost in request/response preview paths.

    Raises
    ------
    MissingBackendError
        If Pillow or NumPy is not installed.
    ValueError
        If *quality* is outside Pillow's normal 1..95 range.
    """

    if quality < 1 or quality > 95:
        raise ValueError(f"JPEG quality must be between 1 and 95, got {quality}.")

    image = to_pil_image(
        dataset,
        frame=frame,
        apply_window=apply_window,
        window_center=window_center,
        window_width=window_width,
    )
    if image.mode not in {"L", "RGB"}:
        image = image.convert("RGB")

    output = BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=quality,
        progressive=progressive,
        optimize=optimize,
    )
    return output.getvalue()


def from_jpeg_preview(data: bytes, *, mode: Optional[str] = None) -> Any:
    """Decode JPEG preview bytes to a loaded ``PIL.Image.Image``.

    The returned image is detached from the input byte stream, so callers can
    inspect or reuse it after this function returns.  Pass *mode* (for example
    ``"RGB"`` or ``"L"``) to force a Pillow mode conversion.

    Raises
    ------
    MissingBackendError
        If Pillow is not installed.
    """

    try:
        from PIL import Image
    except ImportError as exc:
        raise MissingBackendError(
            "from_jpeg_preview() requires Pillow. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    with Image.open(BytesIO(data)) as image:
        loaded = image.copy()
    return loaded.convert(mode) if mode is not None else loaded


# ---------------------------------------------------------------------------
# JSON adapters
# ---------------------------------------------------------------------------


def to_json(dataset: DicomDataset, *, indent: Optional[int] = None) -> str:
    """Serialize a :class:`DicomDataset` to a DICOM JSON Model string (PS3.18 Annex F).

    The output is a single JSON object whose keys are 8-character uppercase
    tag strings (e.g. ``"00100010"``).

    Parameters
    ----------
    dataset:
        The dataset to serialize.
    indent:
        JSON indentation.  ``None`` produces compact output.
    """
    return _json.dumps(dataset_to_dicom_json(dataset), indent=indent)


def from_json(data: Union[str, bytes]) -> DicomDataset:
    """Deserialize a DICOM JSON Model string into a :class:`DicomDataset`.

    Parameters
    ----------
    data:
        A JSON string or UTF-8 bytes in DICOM JSON Model format.
    """
    raw = _json.loads(data)
    return dataset_from_dicom_json(raw)


# ---------------------------------------------------------------------------
# pynetdicom bridge helpers
# ---------------------------------------------------------------------------


def from_pynetdicom_event(event: Any) -> DicomDataset:
    """Extract the :class:`DicomDataset` from a ``pynetdicom`` event.

    Handles C-STORE, N-SET, N-CREATE events that carry a ``dataset``
    attribute, as well as C-FIND events that carry a ``identifier``
    attribute.

    Parameters
    ----------
    event:
        A ``pynetdicom.events.Event`` instance.

    Returns
    -------
    DicomDataset
        The event payload converted to a DicomForge dataset.

    Raises
    ------
    MissingBackendError
        If pynetdicom is not installed.
    AttributeError
        If the event carries neither a ``dataset`` nor ``identifier``.
    """
    try:
        import pynetdicom  # noqa: F401
    except ImportError as exc:
        raise MissingBackendError(
            "from_pynetdicom_event() requires pynetdicom. "
            "Install with `pip install pynetdicom`."
        ) from exc

    raw = getattr(event, "dataset", None) or getattr(event, "identifier", None)
    if raw is None:
        raise AttributeError(
            "Event has neither a 'dataset' nor an 'identifier' attribute. "
            "Check that the event type carries a DICOM dataset payload."
        )
    return from_pydicom(raw)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _copy_pydicom_to_forge(source: Any, dataset: DicomDataset) -> None:
    for element in source:
        value = _pydicom_value_to_forge(element.value)
        tag = Tag(element.tag.group, element.tag.element)
        if tag == Tag.PixelData and getattr(element, "is_undefined_length", False):
            from dicomforge.part10 import _read_encapsulated, _EXPLICIT_LE
            import struct
            value, _ = _read_encapsulated(bytes(element.value) + struct.pack(
                "<HHI", 0xFFFE, 0xE0DD, 0), 0, _EXPLICIT_LE)
        dataset.set(tag, value, vr=element.VR)
        if element.VR in {"DS", "IS"} and element.value not in (None, ""):
            from dicomforge.dataset import _deep_copy_value
            original = element.value
            items = original if type(original).__name__ == "MultiValue" or isinstance(
                original, (list, tuple)) else [original]
            text = "\\".join(str(getattr(item, "original_string", item)) for item in items)
            dataset._lexical[tag] = (text.encode("ascii"), _deep_copy_value(value))


def _pydicom_value_to_forge(value: Any) -> Any:
    """Recursively convert pydicom value types to plain Python equivalents."""
    type_name = type(value).__name__
    module = type(value).__module__ or ""
    if "pydicom" in module:
        if type_name in {"Dataset", "FileDataset"}:
            child = DicomDataset()
            _copy_pydicom_to_forge(value, child)
            return child
        if type_name == "Sequence":
            return [_pydicom_value_to_forge(item) for item in value]
        if type_name == "PersonName":
            return str(value)
        if type_name == "UID":
            return str(value)
        if type_name == "DSfloat" or type_name == "DSdecimal":
            return float(value)
        if type_name == "IS":
            return int(value)
        if type_name == "MultiValue":
            return [_pydicom_value_to_forge(item) for item in value]
    if isinstance(value, (list, tuple)):
        return [_pydicom_value_to_forge(item) for item in value]
    return value


def _forge_value_to_pydicom(value: Any, pydicom: Any) -> Any:
    """Recursively convert DicomForge value types to pydicom equivalents."""
    from dicomforge.charset import PersonName

    if isinstance(value, PersonName):
        return value.to_dicom_string()
    if isinstance(value, DicomDataset):
        raw = pydicom.Dataset()
        for tag, v in value.items():
            raw.add_new(
                (tag.group, tag.element),
                value.vr(tag),
                _forge_value_to_pydicom(v, pydicom),
            )
        return raw
    if isinstance(value, (list, tuple)):
        return [_forge_value_to_pydicom(item, pydicom) for item in value]
    return value


def _rle_fragments_or_none(
    dataset: DicomDataset, meta: FrameMetadata, transfer_syntax: TransferSyntax
) -> Optional[List[bytes]]:
    """Return per-frame RLE fragments for native decode, or ``None``.

    ``None`` means the native path cannot serve this dataset — not RLE, or the
    fragment boundaries were lost (flattened multiframe bytes from an external
    source) — and the caller should delegate to pydicom.
    """

    if transfer_syntax.uid != TransferSyntaxUID.RLELossless:
        return None
    from dicomforge.transcode import rle_frame_fragments

    try:
        return rle_frame_fragments(dataset, meta)
    except DicomValidationError:
        return None


def _rle_pixel_array(
    fragment: bytes,
    dataset: DicomDataset,
    meta: FrameMetadata,
    transfer_syntax: TransferSyntax,
    apply_rescale: bool,
    np: Any,
) -> Any:
    """Decode one RLE fragment natively and shape it like the native path."""

    from dicomforge.rle import rle_decode_frame

    raw = rle_decode_frame(
        fragment,
        rows=meta.rows,
        columns=meta.columns,
        samples_per_pixel=meta.samples_per_pixel,
        bits_allocated=meta.bits_allocated,
    )
    flat = np.frombuffer(raw, dtype=_numpy_dtype(meta, transfer_syntax))
    flat = _normalize_stored_bits(flat, meta, np)
    if meta.samples_per_pixel == 1:
        arr = flat.reshape(meta.rows, meta.columns)
    else:
        # Decoded RLE output is always pixel-interleaved (PlanarConfiguration 0).
        arr = flat.reshape(meta.rows, meta.columns, meta.samples_per_pixel)
    return _apply_rescale_if_requested(arr, dataset, apply_rescale, np)


def _pydicom_pixel_array(dataset: DicomDataset, np: Any, *, frame: int = 0) -> Any:
    try:
        raw = to_pydicom(dataset)
    except MissingBackendError as exc:
        raise MissingBackendError(
            "Compressed pixel_array() requires pydicom plus a pydicom pixel "
            "plugin for the transfer syntax. Install with "
            "`pip install dicomforge[pydicom]` and the appropriate codec extra."
        ) from exc

    syntax_uid = str(dataset.get(Tag.TransferSyntaxUID) or "")
    _ensure_raw_transfer_syntax(raw, syntax_uid)
    try:
        import pydicom
        if hasattr(pydicom, "pixels"):
            decoded = pydicom.pixels.pixel_array(raw, index=frame, raw=True)
        else:
            decoded = _select_frame(raw.pixel_array, FrameMetadata.from_dataset(dataset), frame)
    except Exception as exc:
        raise UnsupportedTransferSyntaxError(
            "pydicom could not decode compressed PixelData for transfer syntax "
            f"{syntax_uid!r}. Install the pydicom pixel plugin for this syntax "
            "or register a different decoder before calling pixel_array()."
        ) from exc
    return np.asarray(decoded)


def _ensure_raw_transfer_syntax(raw: Any, syntax_uid: str) -> None:
    file_meta = getattr(raw, "file_meta", None)
    if file_meta is None:
        try:
            file_meta = type(raw)()
        except Exception:
            file_meta = type("_FileMeta", (), {})()
        try:
            raw.file_meta = file_meta
        except Exception:
            return
    try:
        file_meta.TransferSyntaxUID = syntax_uid
    except Exception:
        return


def _select_frame(arr: Any, meta: FrameMetadata, frame: int) -> Any:
    _validate_frame_index(frame, meta.number_of_frames)
    if meta.number_of_frames == 1:
        return arr
    try:
        return arr[frame]
    except Exception as exc:
        raise IndexError(
            f"Decoded pixel array does not expose frame {frame} of "
            f"{meta.number_of_frames}."
        ) from exc


def _validate_frame_index(frame: int, number_of_frames: int) -> None:
    if frame < 0 or frame >= number_of_frames:
        raise IndexError(
            f"Frame index {frame} is out of range for {number_of_frames} frame(s)."
        )


def _apply_rescale_if_requested(
    arr: Any,
    dataset: DicomDataset,
    apply_rescale: bool,
    np: Any,
) -> Any:
    if apply_rescale:
        slope = float(_first(dataset.get(Tag.RescaleSlope, 1)))
        intercept = float(_first(dataset.get(Tag.RescaleIntercept, 0)))
        return arr.astype(np.float64) * slope + intercept
    copy = getattr(arr, "copy", None)
    return copy() if callable(copy) else arr


def _numpy_dtype(meta: FrameMetadata, transfer_syntax: TransferSyntax) -> Any:
    import numpy as np

    if meta.bits_allocated == 8:
        return np.dtype(np.int8 if meta.is_signed else np.uint8)
    if meta.bits_allocated == 16:
        dtype = np.dtype(np.int16 if meta.is_signed else np.uint16)
    elif meta.bits_allocated == 32:
        dtype = np.dtype(np.int32 if meta.is_signed else np.uint32)
    elif meta.bits_allocated == 64:
        dtype = np.dtype(np.int64 if meta.is_signed else np.uint64)
    else:
        raise ValueError(
            f"Unsupported BitsAllocated={meta.bits_allocated} for numpy dtype mapping."
        )
    return dtype.newbyteorder("<" if transfer_syntax.is_little_endian else ">")


def _ybr_to_rgb_if_needed(arr: Any, photometric: str, np: Any) -> Any:
    """Convert a YBR colour array to RGB when required for display.

    DICOM allows colour pixel data to be stored in several YCbCr variants.
    PIL expects RGB, so we must convert before constructing the Image.

    Handled variants
    ----------------
    YBR_FULL
        Full-range ITU-R BT.601 YCbCr.  Y in [0, 255], Cb/Cr in [0, 255]
        with a 128 offset (0 = −128 after centering).
    YBR_FULL_422
        Same encoding as YBR_FULL; chroma subsampling is resolved at the
        pixel-decode stage so the array already has one sample per pixel.
    YBR_PARTIAL_422
        Partial-range (studio-swing) YCbCr.  Y in [16, 235],
        Cb/Cr in [16, 240].  Less common in DICOM but must not be
        displayed as-is.

    RGB and unknown variants are returned unchanged.
    """
    normalized = photometric.strip().upper()

    if normalized in {"YBR_FULL", "YBR_FULL_422"}:
        # ITU-R BT.601 full-range: Y∈[0,255], Cb/Cr∈[0,255] centred at 128
        f = arr.astype(np.float64)
        y  = f[..., 0]
        cb = f[..., 1] - 128.0
        cr = f[..., 2] - 128.0
        r = y                   + 1.402   * cr
        g = y - 0.344136 * cb  - 0.714136 * cr
        b = y + 1.772   * cb
        rgb = np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)
        return rgb

    if normalized == "YBR_PARTIAL_422":
        # ITU-R BT.601 partial-range (studio swing)
        f = arr.astype(np.float64)
        y  = (f[..., 0] - 16.0)  * (255.0 / 219.0)
        cb = (f[..., 1] - 128.0) * (255.0 / 224.0)
        cr = (f[..., 2] - 128.0) * (255.0 / 224.0)
        r = y                   + 1.402   * cr
        g = y - 0.344136 * cb  - 0.714136 * cr
        b = y + 1.772   * cb
        rgb = np.stack([r, g, b], axis=-1).clip(0, 255).astype(np.uint8)
        return rgb

    # RGB or any other variant — return as-is
    return arr


def _apply_window_numpy(arr: Any, center: float, width: float, np: Any) -> Any:
    """Vectorised linear VOI window application."""
    from dicomforge.pixels import voi_window_bounds
    voi_window_bounds(center, width)
    if width == 1:
        return np.where(arr <= center - 0.5, 0.0, 255.0)
    lower = center - 0.5 - (width - 1) / 2.0
    upper = center - 0.5 + (width - 1) / 2.0
    out = np.where(
        arr <= lower,
        0.0,
        np.where(
            arr > upper,
            255.0,
            ((arr - (center - 0.5)) / (width - 1) + 0.5) * 255.0,
        ),
    )
    return out


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, (list, tuple)) and value else value


def _check_frame_budget(meta: FrameMetadata, limit: int) -> None:
    if limit <= 0:
        raise ValueError("max_frame_bytes must be positive")
    if meta.frame_values * max(1, meta.bytes_per_sample) > limit:
        raise DicomValidationError("Decoded frame exceeds max_frame_bytes")


def _normalize_stored_bits(arr: Any, meta: FrameMetadata, np: Any) -> Any:
    """Mask unused bits and sign-extend at BitsStored, not BitsAllocated."""
    shift = meta.bits_allocated - meta.bits_stored
    if not shift:
        return arr
    if meta.is_signed:
        return (arr << shift) >> shift
    return arr & ((1 << meta.bits_stored) - 1)
