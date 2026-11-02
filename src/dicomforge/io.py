"""Deterministic file I/O with a dependency-free default and explicit adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from dicomforge import part10
from dicomforge.dataset import DicomDataset
from dicomforge.errors import DicomValidationError, MissingBackendError
from dicomforge.storage import atomic_write
from dicomforge.tags import Tag
from dicomforge.uids import TransferSyntaxUID

PathLike = Union[str, Path]
_VALID_BACKENDS = ("auto", "native", "pydicom")


def _use_native_backend(backend: str, *, template_present: bool = False) -> bool:
    if backend not in _VALID_BACKENDS:
        raise ValueError("backend must be auto, native, or pydicom")
    return backend == "native" or (backend == "auto" and not template_present)


def _vr_for_tag(tag: Tag, dataset: DicomDataset) -> str:
    return dataset.vr(tag)


def read(
    path: PathLike, *, stop_before_pixels: bool = False,
    force: bool = False, backend: str = "auto",
) -> DicomDataset:
    """Read a file; auto always selects native, regardless of installed extras.

    The explicit pydicom adapter recursively normalizes values and preserves VRs
    and compressed fragments. Metadata-only datasets cannot be saved accidentally.
    """
    if _use_native_backend(backend):
        return part10.read_file(path, stop_before_pixels=stop_before_pixels, force=force)
    try:
        import pydicom
    except ImportError as exc:
        raise MissingBackendError("Install dicomforge[pydicom] for backend='pydicom'") from exc
    from dicomforge.adapt import from_pydicom
    raw = pydicom.dcmread(str(path), stop_before_pixels=stop_before_pixels, force=force)
    dataset = from_pydicom(raw)
    dataset.source_path = str(Path(path).resolve())
    dataset.source_transfer_syntax = str(dataset.get(Tag.TransferSyntaxUID) or
                                        TransferSyntaxUID.ExplicitVRLittleEndian)
    dataset.is_partial = stop_before_pixels
    return dataset


def write(
    path: PathLike, dataset: DicomDataset, *, template: Any = None,
    ensure_file_meta: bool = True, transfer_syntax: Any = None,
    backend: str = "auto", overwrite: bool = True,
) -> None:
    """Write atomically, preserving source element semantics.

    Use overwrite=False for no-clobber publication. An explicit syntax override
    converts native word byte order; compression changes require the transcoder.
    A template selects pydicom under auto, and is copied rather than mutated.
    """
    if _use_native_backend(backend, template_present=template is not None):
        if template is not None:
            raise DicomValidationError("Templates require backend='pydicom'")
        part10.write_file(path, dataset, transfer_syntax=transfer_syntax,
                          ensure_file_meta=ensure_file_meta, overwrite=overwrite)
        return
    try:
        import pydicom
    except ImportError as exc:
        raise MissingBackendError("Install dicomforge[pydicom] for backend='pydicom'") from exc
    from dicomforge.adapt import to_pydicom
    # Shared serialization preparation checks partial reads, identities, syntax
    # conversion, charset, and binary word order before opening any destination.
    prepared = part10.loads(part10.dumps(dataset, transfer_syntax=transfer_syntax))
    raw = to_pydicom(prepared)
    if template is not None:
        import copy
        merged = copy.deepcopy(template)
        for element in raw:
            merged[element.tag] = element
        merged.file_meta = raw.file_meta
        raw = merged
    def save(staging: Path) -> None:
        if int(pydicom.__version__.split(".")[0]) >= 3:
            pydicom.dcmwrite(str(staging), raw, enforce_file_format=ensure_file_meta)
        else:
            raw.is_little_endian = prepared.get(Tag.TransferSyntaxUID) != (
                TransferSyntaxUID.ExplicitVRBigEndian)
            raw.is_implicit_VR = prepared.get(Tag.TransferSyntaxUID) == (
                TransferSyntaxUID.ImplicitVRLittleEndian)
            pydicom.dcmwrite(str(staging), raw, write_like_original=not ensure_file_meta)
    atomic_write(path, save, overwrite=overwrite)
