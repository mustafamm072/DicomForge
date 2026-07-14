"""File IO adapters.

Two interchangeable backends read and write DICOM files:

* ``"native"`` — DicomForge's own dependency-free DICOM Part 10 codec
  (:mod:`dicomforge.part10`).  Handles the uncompressed transfer syntaxes
  (Implicit/Explicit VR Little Endian, Explicit VR Big Endian), Deflated
  Explicit VR Little Endian, and encapsulated (compressed) pixel-data framing
  with no third-party packages; RLE Lossless is compressed/decompressed
  natively via :mod:`dicomforge.transcode`.
* ``"pydicom"`` — the optional :mod:`pydicom` backend, required for JPEG-family
  pixel codecs and the broadest real-world coverage.

The default ``backend="auto"`` prefers pydicom when it is importable and falls
back to the native codec otherwise, so reading and writing a ``.dcm`` file now
works out of the box even with zero optional dependencies installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from dicomforge import part10
from dicomforge.charset import PersonName, ensure_text_encodable
from dicomforge.dataset import DicomDataset
from dicomforge.dictionary import vr_for_tag
from dicomforge.errors import CharacterSetError, DicomValidationError, MissingBackendError
from dicomforge.tags import Tag
from dicomforge.uids import ImplementationUID, TransferSyntaxUID

PathLike = Union[str, Path]

_VALID_BACKENDS = ("auto", "native", "pydicom")


def _pydicom_available() -> bool:
    try:
        import pydicom  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def _use_native_backend(backend: str, *, template_present: bool = False) -> bool:
    if backend not in _VALID_BACKENDS:
        raise ValueError(
            f"backend must be one of {_VALID_BACKENDS!r}, got {backend!r}."
        )
    if backend == "native":
        return True
    if backend == "pydicom":
        return False
    # auto: a pydicom template can only be honoured by pydicom; otherwise prefer
    # pydicom when available and fall back to the native codec.
    if template_present:
        return False
    return not _pydicom_available()

_TEXT_VRS = {
    "AE",
    "AS",
    "CS",
    "DA",
    "DS",
    "DT",
    "IS",
    "LO",
    "LT",
    "PN",
    "SH",
    "ST",
    "TM",
    "UC",
    "UR",
    "UT",
}


def _copy_pydicom_elements(source: Any, dataset: DicomDataset) -> None:
    for element in source:
        dataset.set((element.tag.group, element.tag.element), element.value)


def _vr_for_tag(tag: Tag, dataset: DicomDataset) -> str:
    bits_allocated = dataset.get(Tag.BitsAllocated, 16) if tag == Tag.PixelData else None
    return vr_for_tag(tag, bits_allocated=bits_allocated)


def _required_value(dataset: DicomDataset, primary: Tag, fallback: Tag) -> object:
    value = dataset.get(primary)
    if value not in (None, ""):
        return value
    value = dataset.get(fallback)
    if value not in (None, ""):
        return value
    raise DicomValidationError(
        f"Writing a DICOM file requires {primary} or {fallback} for File Meta Information."
    )


def _value_for_write(value: Any) -> Any:
    if isinstance(value, PersonName):
        return value.to_dicom_string()
    if isinstance(value, DicomDataset):
        return value
    if isinstance(value, list):
        return [_value_for_write(item) for item in value]
    return value


def _validate_text_value(value: Any, specific_character_set: Any) -> None:
    if isinstance(value, DicomDataset):
        return
    if isinstance(value, (bytes, bytearray)):
        return
    if isinstance(value, list):
        for item in value:
            _validate_text_value(item, specific_character_set)
        return
    try:
        ensure_text_encodable(value, specific_character_set)
    except CharacterSetError:
        if str(value).isascii():
            return
        raise


def _ensure_file_meta(raw: Any, dataset: DicomDataset, pydicom: Any) -> None:
    file_meta = getattr(raw, "file_meta", None)
    if file_meta is None:
        factory = getattr(pydicom, "FileMetaDataset", getattr(pydicom, "Dataset"))
        file_meta = factory()
        raw.file_meta = file_meta

    media_storage_sop_class_uid = _required_value(
        dataset,
        Tag.MediaStorageSOPClassUID,
        Tag.SOPClassUID,
    )
    media_storage_sop_instance_uid = _required_value(
        dataset,
        Tag.MediaStorageSOPInstanceUID,
        Tag.SOPInstanceUID,
    )
    transfer_syntax_uid = dataset.get(
        Tag.TransferSyntaxUID,
        TransferSyntaxUID.ExplicitVRLittleEndian,
    )
    implementation_class_uid = dataset.get(
        Tag.ImplementationClassUID,
        ImplementationUID.DicomForge,
    )

    for tag, value in (
        (Tag.MediaStorageSOPClassUID, media_storage_sop_class_uid),
        (Tag.MediaStorageSOPInstanceUID, media_storage_sop_instance_uid),
        (Tag.TransferSyntaxUID, transfer_syntax_uid),
        (Tag.ImplementationClassUID, implementation_class_uid),
    ):
        file_meta.add_new((tag.group, tag.element), _vr_for_tag(tag, dataset), value)


def read(
    path: PathLike,
    *,
    stop_before_pixels: bool = False,
    force: bool = False,
    backend: str = "auto",
) -> DicomDataset:
    """Read a DICOM file.

    Parameters
    ----------
    path:
        File system path to the DICOM file.
    stop_before_pixels:
        Stop before reading ``PixelData (7FE0,0010)`` for fast metadata scans.
    force:
        Read a data set that lacks the preamble / ``DICM`` magic.
    backend:
        ``"auto"`` (default) uses pydicom when installed and the native codec
        otherwise; ``"native"`` always uses the dependency-free codec;
        ``"pydicom"`` always uses pydicom.
    """

    if _use_native_backend(backend):
        return part10.read_file(path, stop_before_pixels=stop_before_pixels, force=force)

    try:
        import pydicom  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "Reading DICOM files with backend='pydicom' requires the optional "
            "pydicom backend. Install with `pip install dicomforge[pydicom]`, "
            "or use backend='native' for the dependency-free reader."
        ) from exc

    raw = pydicom.dcmread(str(path), stop_before_pixels=stop_before_pixels, force=force)
    dataset = DicomDataset()
    file_meta = getattr(raw, "file_meta", None)
    if file_meta is not None:
        _copy_pydicom_elements(file_meta, dataset)
    _copy_pydicom_elements(raw, dataset)
    return dataset


def write(
    path: PathLike,
    dataset: DicomDataset,
    *,
    template: Any = None,
    ensure_file_meta: bool = True,
    transfer_syntax: Any = None,
    backend: str = "auto",
) -> None:
    """Write a DICOM file.

    Parameters
    ----------
    path:
        Destination file path.
    template:
        Optional pydicom ``Dataset`` to populate (pydicom backend only).
    ensure_file_meta:
        Write the preamble, ``DICM`` magic, and File Meta Information group.
    transfer_syntax:
        Transfer Syntax UID to encode with (native backend).  Defaults to the
        dataset's ``TransferSyntaxUID`` if present, else Explicit VR Little
        Endian.
    backend:
        ``"auto"`` (default) uses pydicom when installed and the native codec
        otherwise; ``"native"`` always uses the dependency-free codec;
        ``"pydicom"`` always uses pydicom.  A *template* forces the pydicom
        backend under ``"auto"``.
    """

    if _use_native_backend(backend, template_present=template is not None):
        if template is not None:
            raise DicomValidationError(
                "The 'template' argument is only supported by the pydicom backend."
            )
        part10.write_file(
            path,
            dataset,
            transfer_syntax=transfer_syntax,
            ensure_file_meta=ensure_file_meta,
        )
        return

    try:
        import pydicom  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "Writing DICOM files with backend='pydicom' requires the optional "
            "pydicom backend. Install with `pip install dicomforge[pydicom]`, "
            "or use backend='native' for the dependency-free writer."
        ) from exc

    raw = template if template is not None else pydicom.Dataset()
    if ensure_file_meta:
        _ensure_file_meta(raw, dataset, pydicom)
    specific_character_set = dataset.get(Tag.SpecificCharacterSet)
    if specific_character_set is not None:
        raw.add_new(
            (Tag.SpecificCharacterSet.group, Tag.SpecificCharacterSet.element),
            _vr_for_tag(Tag.SpecificCharacterSet, dataset),
            specific_character_set,
        )
    for tag, value in dataset.items():
        if ensure_file_meta and tag.group == 0x0002:
            continue
        if tag == Tag.SpecificCharacterSet:
            continue
        vr = _vr_for_tag(tag, dataset)
        write_value = _value_for_write(value)
        if vr in _TEXT_VRS:
            _validate_text_value(write_value, specific_character_set)
        raw.add_new((tag.group, tag.element), vr, write_value)
    # pydicom ≥ 3.0 deprecates Dataset.save_as() in favour of pydicom.dcmwrite().
    if hasattr(pydicom, "dcmwrite"):
        pydicom.dcmwrite(str(path), raw)
    else:
        raw.save_as(str(path))
