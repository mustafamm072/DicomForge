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
from typing import Any, Iterator, Optional, Union

from dicomforge.dataset import DicomDataset
from dicomforge.dicomweb import dataset_from_dicom_json, dataset_to_dicom_json
from dicomforge.errors import MissingBackendError, UnsupportedTransferSyntaxError
from dicomforge.pixels import (
    FrameMetadata,
    apply_voi_window,
    is_monochrome,
    needs_inversion,
    rescale_value,
)
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax

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
        import pydicom  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "to_pydicom() requires the optional pydicom backend. "
            "Install with `pip install dicomforge[pydicom]`."
        ) from exc

    from dicomforge.io import _vr_for_tag  # local import to avoid circular

    raw = pydicom.Dataset()
    for tag, value in dataset.items():
        vr = _vr_for_tag(tag, dataset)
        converted = _forge_value_to_pydicom(value, pydicom)
        raw.add_new((tag.group, tag.element), vr, converted)
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
) -> Any:
    """Extract one frame of PixelData as a ``numpy.ndarray``.

    The returned array has shape ``(rows, columns)`` for single-sample images
    or ``(rows, columns, samples)`` for colour images, and the dtype matches
    ``BitsAllocated`` (``uint8``, ``uint16``, ``int16``, ``int32`` for signed
    data).  Native uncompressed data is decoded directly.  Encapsulated
    compressed data is delegated to pydicom when pydicom and the required
    pydicom pixel plugin are installed.

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
        import numpy as np  # type: ignore[import-not-found]
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
    _validate_frame_index(frame, meta.number_of_frames)

    if cap.transfer_syntax.is_compressed:
        arr = _pydicom_pixel_array(dataset, np)
        selected = _select_frame(arr, meta, frame)
        return _apply_rescale_if_requested(selected, dataset, apply_rescale, np)

    return _native_pixel_array(dataset, meta, cap.transfer_syntax, frame, apply_rescale, np)


def iter_pixel_frames(
    dataset: DicomDataset,
    *,
    apply_rescale: bool = False,
    registry: Any = None,
) -> Iterator[Any]:
    """Yield pixel frames one at a time as ``numpy.ndarray`` objects.

    For native uncompressed PixelData, frames are sliced from the source byte
    buffer without materialising the whole pixel stack.  For compressed
    syntaxes, decoding is delegated once to pydicom and frames are then yielded
    from the decoded result.  This keeps the API lightweight while giving
    callers a memory-conscious path for ordinary multiframe native datasets.

    Requires ``pip install dicomforge[pixels]``.  Compressed syntaxes also
    require ``pip install dicomforge[pydicom]`` plus the pydicom codec backend
    for the transfer syntax.
    """
    try:
        import numpy as np  # type: ignore[import-not-found]
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

    if cap.transfer_syntax.is_compressed:
        arr = _pydicom_pixel_array(dataset, np)
        for frame_index in range(meta.number_of_frames):
            selected = _select_frame(arr, meta, frame_index)
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

    dtype = _numpy_dtype(meta, transfer_syntax)
    total_values = meta.frame_values * meta.number_of_frames
    flat = np.frombuffer(raw_bytes[: total_values * meta.bytes_per_sample], dtype=dtype)

    frame_start = frame * meta.frame_values
    frame_end = frame_start + meta.frame_values
    frame_flat = flat[frame_start:frame_end]

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
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "to_pil_image() requires Pillow. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    try:
        import numpy as np  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "to_pil_image() requires numpy. "
            "Install with `pip install dicomforge[pixels]`."
        ) from exc

    arr = pixel_array(dataset, frame=frame)
    meta = FrameMetadata.from_dataset(dataset)
    photometric = meta.photometric_interpretation

    if is_monochrome(photometric):
        arr_float = arr.astype(np.float64)
        if apply_window:
            center = window_center
            width = window_width
            if center is None:
                raw_center = dataset.get(Tag.WindowCenter)
                center = float(raw_center) if raw_center is not None else float(arr_float.mean())
            if width is None:
                raw_width = dataset.get(Tag.WindowWidth)
                width = (
                    float(raw_width)
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
        return Image.fromarray(arr_uint8, mode="L")

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
    return Image.fromarray(arr, mode="RGB")


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
        from PIL import Image  # type: ignore[import-not-found]
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
        import pynetdicom  # type: ignore[import-not-found]  # noqa: F401
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
        dataset.set((element.tag.group, element.tag.element), value)


def _pydicom_value_to_forge(value: Any) -> Any:
    """Recursively convert pydicom value types to plain Python equivalents."""
    type_name = type(value).__name__
    module = type(value).__module__ or ""
    if "pydicom" in module:
        if type_name == "Dataset":
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
    if isinstance(value, list):
        return [_pydicom_value_to_forge(item) for item in value]
    return value


def _forge_value_to_pydicom(value: Any, pydicom: Any) -> Any:
    """Recursively convert DicomForge value types to pydicom equivalents."""
    from dicomforge.charset import PersonName

    if isinstance(value, PersonName):
        return value.to_dicom_string()
    if isinstance(value, DicomDataset):
        from dicomforge.io import _vr_for_tag

        raw = pydicom.Dataset()
        for tag, v in value.items():
            raw.add_new(
                (tag.group, tag.element),
                _vr_for_tag(tag, value),
                _forge_value_to_pydicom(v, pydicom),
            )
        return pydicom.Sequence([raw])
    if isinstance(value, list):
        return [_forge_value_to_pydicom(item, pydicom) for item in value]
    return value


def _pydicom_pixel_array(dataset: DicomDataset, np: Any) -> Any:
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
        decoded = raw.pixel_array
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
        slope = float(dataset.get(Tag.RescaleSlope) or 1)
        intercept = float(dataset.get(Tag.RescaleIntercept) or 0)
        return arr.astype(np.float64) * slope + intercept
    copy = getattr(arr, "copy", None)
    return copy() if callable(copy) else arr


def _numpy_dtype(meta: FrameMetadata, transfer_syntax: TransferSyntax) -> Any:
    import numpy as np  # type: ignore[import-not-found]

    if meta.bits_allocated == 8:
        return np.dtype(np.int8 if meta.is_signed else np.uint8)
    if meta.bits_allocated == 16:
        dtype = np.dtype(np.int16 if meta.is_signed else np.uint16)
    elif meta.bits_allocated == 32:
        dtype = np.dtype(np.int32 if meta.is_signed else np.uint32)
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
