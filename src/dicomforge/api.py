"""High-level convenience API for everyday DICOM workflows.

This module provides the "adoption layer" for developers who want named
property access, one-liner operations, and helpful validation without
needing to understand the underlying primitives.  The lower-level modules
(``dicomforge.dataset``, ``dicomforge.anonymize``, etc.) are still
available and this module is a thin, stable façade over them.

Quick-start
-----------
Read a DICOM file and inspect metadata::

    from dicomforge.api import DicomFile

    f = DicomFile("brain_scan.dcm")
    print(f.patient_name, f.modality, f.study_instance_uid)

Anonymize in one call::

    from dicomforge.api import quick_anonymize

    report = quick_anonymize("input.dcm", "output_anon.dcm", uid_salt="my-project")

Validate a dataset before sending it to a PACS::

    from dicomforge.api import validate_dataset
    from dicomforge.io import read

    issues = validate_dataset(read("image.dcm"))
    if issues:
        for issue in issues:
            print(issue)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from dicomforge.anonymize import AnonymizationPlan, AnonymizationReport, PrivateTagAction
from dicomforge.dataset import DicomDataset
from dicomforge.errors import MissingBackendError
from dicomforge.pixels import FrameMetadata, PixelCapability, PixelMetadataError
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import TransferSyntaxUID

PathLike = Union[str, Path]


class DicomFile:
    """High-level wrapper around a DICOM file with named property access.

    The underlying dataset is loaded lazily on first access, so creating
    a ``DicomFile`` is cheap — use ``stop_before_pixels=True`` to avoid
    reading pixel data until you need it.

    Parameters
    ----------
    path:
        Path to the DICOM file.
    stop_before_pixels:
        When *True* the pydicom backend skips reading ``PixelData``,
        making metadata-only access significantly faster for large files.

    Raises
    ------
    MissingBackendError
        On first dataset access, if pydicom is not installed.
    """

    def __init__(self, path: PathLike, *, stop_before_pixels: bool = False) -> None:
        self._path = Path(path)
        self._stop_before_pixels = stop_before_pixels
        self._dataset: Optional[DicomDataset] = None

    @property
    def path(self) -> Path:
        return self._path

    @property
    def dataset(self) -> DicomDataset:
        if self._dataset is None:
            from dicomforge.io import read

            self._dataset = read(self._path, stop_before_pixels=self._stop_before_pixels)
        return self._dataset

    # ------------------------------------------------------------------
    # Patient
    # ------------------------------------------------------------------

    @property
    def patient_name(self) -> str:
        return str(self.dataset.get(Tag.PatientName) or "")

    @property
    def patient_id(self) -> str:
        return str(self.dataset.get(Tag.PatientID) or "")

    @property
    def patient_birth_date(self) -> str:
        return str(self.dataset.get(Tag.PatientBirthDate) or "")

    @property
    def patient_sex(self) -> str:
        return str(self.dataset.get(Tag.PatientSex) or "")

    # ------------------------------------------------------------------
    # Study
    # ------------------------------------------------------------------

    @property
    def study_instance_uid(self) -> str:
        return str(self.dataset.get(Tag.StudyInstanceUID) or "")

    @property
    def study_date(self) -> str:
        return str(self.dataset.get(Tag.StudyDate) or "")

    @property
    def study_description(self) -> str:
        return str(self.dataset.get(Tag.StudyDescription) or "")

    @property
    def accession_number(self) -> str:
        return str(self.dataset.get(Tag.AccessionNumber) or "")

    # ------------------------------------------------------------------
    # Series
    # ------------------------------------------------------------------

    @property
    def series_instance_uid(self) -> str:
        return str(self.dataset.get(Tag.SeriesInstanceUID) or "")

    @property
    def series_number(self) -> Optional[int]:
        val = self.dataset.get(Tag.SeriesNumber)
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def series_description(self) -> str:
        return str(self.dataset.get(Tag.SeriesDescription) or "")

    @property
    def modality(self) -> str:
        return str(self.dataset.get(Tag.Modality) or "")

    @property
    def body_part_examined(self) -> str:
        return str(self.dataset.get(Tag.BodyPartExamined) or "")

    # ------------------------------------------------------------------
    # Instance
    # ------------------------------------------------------------------

    @property
    def sop_instance_uid(self) -> str:
        return str(self.dataset.get(Tag.SOPInstanceUID) or "")

    @property
    def sop_class_uid(self) -> str:
        return str(self.dataset.get(Tag.SOPClassUID) or "")

    @property
    def instance_number(self) -> Optional[int]:
        val = self.dataset.get(Tag.InstanceNumber)
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Equipment
    # ------------------------------------------------------------------

    @property
    def manufacturer(self) -> str:
        return str(self.dataset.get(Tag.Manufacturer) or "")

    @property
    def manufacturer_model_name(self) -> str:
        return str(self.dataset.get(Tag.ManufacturerModelName) or "")

    @property
    def station_name(self) -> str:
        return str(self.dataset.get(Tag.StationName) or "")

    @property
    def institution_name(self) -> str:
        return str(self.dataset.get(Tag.InstitutionName) or "")

    # ------------------------------------------------------------------
    # Transfer syntax / pixel capability
    # ------------------------------------------------------------------

    @property
    def transfer_syntax(self) -> TransferSyntax:
        uid = self.dataset.get(Tag.TransferSyntaxUID)
        if uid is None:
            return TransferSyntax.from_uid(TransferSyntaxUID.ExplicitVRLittleEndian)
        return TransferSyntax.from_uid(str(uid))

    def pixel_capability(self) -> PixelCapability:
        """Check whether pixel data can be accessed with the built-in codec."""
        from dicomforge.pixels import check_pixel_capability

        return check_pixel_capability(self.dataset)

    def frame_metadata(self) -> FrameMetadata:
        """Return pixel shape and encoding metadata."""
        return FrameMetadata.from_dataset(self.dataset)

    @property
    def number_of_frames(self) -> int:
        val = self.dataset.get(Tag.NumberOfFrames)
        try:
            return int(val) if val is not None else 1
        except (TypeError, ValueError):
            return 1

    @property
    def rows(self) -> Optional[int]:
        val = self.dataset.get(Tag.Rows)
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    @property
    def columns(self) -> Optional[int]:
        val = self.dataset.get(Tag.Columns)
        try:
            return int(val) if val is not None else None
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------

    def anonymize(
        self,
        *,
        uid_salt: str = "dicomforge",
        private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE,
        replacements: Optional[Mapping[Any, Any]] = None,
    ) -> AnonymizationReport:
        """Apply the starter de-identification profile in-place.

        Returns the :class:`AnonymizationReport` audit trail.

        Parameters
        ----------
        uid_salt:
            Salt used for deterministic UID remapping.  Change this per
            project so UIDs from different anonymization runs stay distinct.
        private_tag_action:
            Whether to remove or keep private tags.
        replacements:
            Per-tag replacement overrides, e.g.
            ``{"PatientName": "Volunteer-01"}``.
        """
        plan = AnonymizationPlan.starter_profile(
            replacements=replacements,
            uid_salt=uid_salt,
            private_tag_action=private_tag_action,
        )
        return plan.apply_with_report(self.dataset)

    def save(self, path: PathLike) -> None:
        """Write the (possibly modified) dataset to *path*.

        Requires ``pip install dicomforge[pydicom]``.
        """
        from dicomforge.io import write

        write(path, self.dataset)

    def tags(self) -> Dict[str, Any]:
        """Return a plain ``{tag_string: value}`` dict for inspection."""
        return self.dataset.to_plain_dict()

    def __repr__(self) -> str:
        return (
            f"DicomFile(path={self._path.name!r}, "
            f"modality={self.modality!r}, "
            f"patient={self.patient_name!r})"
        )


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def quick_anonymize(
    input_path: PathLike,
    output_path: PathLike,
    *,
    uid_salt: str = "dicomforge",
    private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE,
    replacements: Optional[Mapping[Any, Any]] = None,
) -> AnonymizationReport:
    """Read, anonymize, and write a DICOM file in one call.

    Requires ``pip install dicomforge[pydicom]``.

    Parameters
    ----------
    input_path:
        Source DICOM file.
    output_path:
        Destination for the anonymized file.  Parent directories must exist.
    uid_salt:
        Salt for deterministic UID remapping.  Use a constant salt per
        project so the same source UID always maps to the same output UID.
    private_tag_action:
        Whether to remove or keep private tags.
    replacements:
        Per-tag replacement overrides.

    Returns
    -------
    AnonymizationReport
        Full audit trail of every tag touched by the de-identification plan.

    Example
    -------
    ::

        from dicomforge.api import quick_anonymize
        from dicomforge import PrivateTagAction

        report = quick_anonymize(
            "patient_scan.dcm",
            "anonymized_scan.dcm",
            uid_salt="research-project-42",
            replacements={"PatientName": "Subject-001"},
        )
        print(f"Removed {report.private_tags_removed} private tags")
    """
    from dicomforge.io import read, write

    dataset = read(input_path)
    plan = AnonymizationPlan.starter_profile(
        replacements=replacements,
        uid_salt=uid_salt,
        private_tag_action=private_tag_action,
    )
    report = plan.apply_with_report(dataset)
    write(output_path, dataset)
    return report


def validate_dataset(dataset: DicomDataset) -> List[str]:
    """Return a list of validation issues found in *dataset*.

    An empty list means no issues were detected.  Issues are human-readable
    strings that describe missing tags, inconsistent metadata, or other
    problems that would prevent correct storage or display.

    Checks performed
    ----------------
    - ``SOPClassUID`` present and non-empty
    - ``SOPInstanceUID`` present and non-empty
    - ``TransferSyntaxUID`` present (group 0002)
    - ``Modality`` present and non-empty
    - Pixel metadata consistency (when pixel tags are present):
      ``Rows``, ``Columns``, ``BitsAllocated``, ``BitsStored``,
      ``HighBit``, ``PixelRepresentation``, ``PhotometricInterpretation``
    - ``BurnedInAnnotation`` is ``"NO"`` or absent (informational warning)
    """
    issues: List[str] = []

    def _require(tag: Tag, label: str) -> None:
        val = dataset.get(tag)
        if val is None or str(val).strip() == "":
            issues.append(f"Missing required tag {label} {tag}.")

    _require(Tag.SOPClassUID, "SOPClassUID")
    _require(Tag.SOPInstanceUID, "SOPInstanceUID")
    _require(Tag.Modality, "Modality")

    if dataset.get(Tag.TransferSyntaxUID) is None:
        issues.append(
            "TransferSyntaxUID (0002,0010) is absent. "
            "File meta information may be missing or incomplete."
        )

    if dataset.get(Tag.Rows) is not None:
        try:
            FrameMetadata.from_dataset(dataset)
        except PixelMetadataError as exc:
            issues.append(f"Pixel metadata inconsistency: {exc}")

    burned = str(dataset.get(Tag.BurnedInAnnotation) or "").strip().upper()
    if burned == "YES":
        issues.append(
            "BurnedInAnnotation is 'YES' — pixel data may contain PHI. "
            "Review pixel content before distribution."
        )

    return issues


def batch_anonymize(
    input_paths: List[PathLike],
    output_dir: PathLike,
    *,
    uid_salt: str = "dicomforge",
    private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE,
    replacements: Optional[Mapping[Any, Any]] = None,
) -> Dict[str, Union[AnonymizationReport, Exception]]:
    """Anonymize a list of DICOM files, writing each to *output_dir*.

    Output filenames are preserved from the input.  Returns a dict mapping
    each input filename to its :class:`AnonymizationReport` on success or
    to the :class:`Exception` on failure, so partial failures do not abort
    the whole batch.

    Parameters
    ----------
    input_paths:
        List of source DICOM file paths.
    output_dir:
        Directory to write anonymized files.  Must exist.
    uid_salt, private_tag_action, replacements:
        Passed through to :func:`quick_anonymize`.
    """
    output_directory = Path(output_dir)
    results: Dict[str, Union[AnonymizationReport, Exception]] = {}
    for raw_path in input_paths:
        src = Path(raw_path)
        dest = output_directory / src.name
        try:
            report = quick_anonymize(
                src,
                dest,
                uid_salt=uid_salt,
                private_tag_action=private_tag_action,
                replacements=replacements,
            )
            results[str(src)] = report
        except Exception as exc:  # noqa: BLE001
            results[str(src)] = exc
    return results
