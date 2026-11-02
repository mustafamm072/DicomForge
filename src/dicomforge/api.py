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

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Tuple, Union

from dicomforge.anonymize import AnonymizationPlan, AnonymizationReport, PrivateTagAction
from dicomforge.dataset import DicomDataset, as_dataset
from dicomforge.pixels import FrameMetadata, PixelCapability, PixelMetadataError, assert_pixel_data_length
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import TransferSyntaxUID, is_valid_uid

PathLike = Union[str, Path]


@dataclass(frozen=True)
class ValidationIssue:
    """Structured validation issue for applications that need machine-readable output.

    The existing validation helpers still return human-readable strings by
    default.  Use ``validate_dataset_detailed`` or
    ``validate_for_sop_class_detailed`` when a caller needs to filter by
    severity, tag, or issue code without parsing display text.
    """

    severity: str
    message: str
    code: str
    tag: Optional[Tag] = None
    label: Optional[str] = None
    requirement: Optional[str] = None
    sop_class_uid: Optional[str] = None
    sop_class_name: Optional[str] = None
    path: Tuple[object, ...] = ()
    assessed: bool = True
    standard: Optional[str] = None

    @property
    def is_error(self) -> bool:
        """Return whether this issue should block storage or transmission."""

        return self.severity == "error"

    def __str__(self) -> str:
        return self.message


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
        When *True* the native reader stops before ``PixelData``,
        making metadata-only access significantly faster for large files.

    Raises
    ------
    MissingBackendError
        Only when an explicitly requested optional integration is unavailable.
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

        Uses the dependency-free native backend by default.
        """
        from dicomforge.io import write

        write(path, self.dataset)

    def load_pixels(self) -> DicomDataset:
        """Reload a metadata-only file while retaining edited metadata values."""
        current = self.dataset
        if current.is_partial:
            from dicomforge.io import read
            full = read(self._path)
            for element in current.elements():
                full.set(element.tag, element.value, vr=element.vr)
            self._dataset = full
        return self.dataset

    def tags(self) -> Dict[str, Any]:
        """Return a plain ``{tag_string: value}`` dict for inspection."""
        return self.dataset.to_plain_dict()

    def validate(
        self, *, detailed: bool = False
    ) -> Union[List[str], List[ValidationIssue]]:
        """Validate this file's dataset.

        Parameters
        ----------
        detailed:
            When *False* (default), return the same human-readable strings as
            :func:`validate_dataset`.  When *True*, return structured
            :class:`ValidationIssue` objects.
        """

        if detailed:
            return validate_dataset_detailed(self.dataset)
        return validate_dataset(self.dataset)

    def __repr__(self) -> str:
        return f"DicomFile(loaded={self._dataset is not None})"


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
    overwrite: bool = False,
) -> AnonymizationReport:
    """Read, anonymize, and write a DICOM file in one call.

    Uses the dependency-free native backend by default.

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
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("De-identification output must not replace the source file")

    dataset = read(input_path)
    plan = AnonymizationPlan.starter_profile(
        replacements=replacements,
        uid_salt=uid_salt,
        private_tag_action=private_tag_action,
    )
    report = plan.apply_with_report(dataset)
    write(output_path, dataset, overwrite=overwrite)
    return report


def validate_dataset_detailed(dataset: DicomDataset) -> List[ValidationIssue]:
    """Return a list of validation issues found in *dataset*.

    An empty list means no issues were detected.  Issues are structured
    :class:`ValidationIssue` objects for production callers that need stable
    fields for filtering and logging.

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
    dataset = as_dataset(dataset)
    issues: List[ValidationIssue] = []

    def _require(tag: Tag, label: str) -> None:
        val = dataset.get(tag)
        if _empty_value(val):
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"Missing required tag {label} {tag}.",
                    code="missing-required-tag",
                    tag=tag,
                    label=label,
                )
            )

    _require(Tag.SOPClassUID, "SOPClassUID")
    _require(Tag.SOPInstanceUID, "SOPInstanceUID")
    _require(Tag.Modality, "Modality")

    if dataset.get(Tag.TransferSyntaxUID) is None:
        issues.append(
            ValidationIssue(
                severity="warning",
                message=(
                    "TransferSyntaxUID (0002,0010) is absent. "
                    "File meta information may be missing or incomplete."
                ),
                code="missing-transfer-syntax",
                tag=Tag.TransferSyntaxUID,
                label="TransferSyntaxUID",
            )
        )

    _validate_uid_value(issues, dataset, Tag.SOPClassUID, "SOPClassUID")
    _validate_uid_value(issues, dataset, Tag.SOPInstanceUID, "SOPInstanceUID")
    _validate_uid_value(issues, dataset, Tag.StudyInstanceUID, "StudyInstanceUID")
    _validate_uid_value(issues, dataset, Tag.SeriesInstanceUID, "SeriesInstanceUID")
    _validate_uid_value(issues, dataset, Tag.TransferSyntaxUID, "TransferSyntaxUID")

    if dataset.get(Tag.Rows) is not None:
        try:
            metadata = FrameMetadata.from_dataset(dataset)
            pixels = dataset.get(Tag.PixelData)
            uid = str(dataset.get(Tag.TransferSyntaxUID) or TransferSyntaxUID.ExplicitVRLittleEndian)
            if isinstance(pixels, (bytes, bytearray)) and not TransferSyntax.from_uid(uid).is_compressed:
                assert_pixel_data_length(pixels, metadata)
        except PixelMetadataError as exc:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"Pixel metadata inconsistency: {exc}",
                    code="pixel-metadata-inconsistency",
                )
            )

    burned = str(dataset.get(Tag.BurnedInAnnotation) or "").strip().upper()
    if burned == "YES":
        issues.append(
            ValidationIssue(
                severity="warning",
                message=(
                    "BurnedInAnnotation is 'YES' — pixel data may contain PHI. "
                    "Review pixel content before distribution."
                ),
                code="burned-in-annotation",
                tag=Tag.BurnedInAnnotation,
                label="BurnedInAnnotation",
            )
        )

    return issues


def validate_dataset(dataset: DicomDataset) -> List[str]:
    """Return human-readable validation issues found in *dataset*.

    This compatibility wrapper keeps the simple list-of-strings API.  Use
    :func:`validate_dataset_detailed` when severity, tag, and code fields are
    needed for application logic.
    """

    return [str(issue) for issue in validate_dataset_detailed(dataset)]


def _validate_uid_value(
    issues: List[ValidationIssue], dataset: DicomDataset, tag: Tag, label: str
) -> None:
    value = dataset.get(tag)
    if value is None or str(value).strip() == "":
        return
    if not is_valid_uid(str(value).strip()):
        issues.append(
            ValidationIssue(
                severity="error",
                message=f"{label} {tag} is not a valid DICOM UID.",
                code="invalid-uid",
                tag=tag,
                label=label,
            )
        )


# ---------------------------------------------------------------------------
# IOD / SOP Class validation helpers
# ---------------------------------------------------------------------------


class _IodProfile(NamedTuple):
    """Mandatory-attribute requirements for one SOP Class IOD."""

    name: str
    # Tags that MUST be present and non-empty (DICOM Type 1).
    # A missing or empty value is reported as an error.
    type1: Tuple[Tuple[Tag, str], ...]
    # Tags that MUST be present, but may be empty (DICOM Type 2).
    # A missing value is reported as an error.
    type2: Tuple[Tuple[Tag, str], ...]


# Common image-module tags shared by all image SOP classes.
_COMMON_TYPE1: Tuple[Tuple[Tag, str], ...] = (
    (Tag.SOPClassUID, "SOPClassUID"),
    (Tag.SOPInstanceUID, "SOPInstanceUID"),
    (Tag.StudyInstanceUID, "StudyInstanceUID"),
    (Tag.SeriesInstanceUID, "SeriesInstanceUID"),
    (Tag.Modality, "Modality"),
    (Tag.SamplesPerPixel, "SamplesPerPixel"),
    (Tag.PhotometricInterpretation, "PhotometricInterpretation"),
    (Tag.Rows, "Rows"),
    (Tag.Columns, "Columns"),
    (Tag.BitsAllocated, "BitsAllocated"),
    (Tag.BitsStored, "BitsStored"),
    (Tag.HighBit, "HighBit"),
    (Tag.PixelRepresentation, "PixelRepresentation"),
    (Tag.PixelData, "PixelData"),
)

_COMMON_TYPE2: Tuple[Tuple[Tag, str], ...] = (
    (Tag.PatientName, "PatientName"),
    (Tag.PatientID, "PatientID"),
    (Tag.StudyDate, "StudyDate"),
    (Tag.StudyTime, "StudyTime"),
    (Tag.StudyID, "StudyID"),
    (Tag.AccessionNumber, "AccessionNumber"),
    (Tag.SeriesNumber, "SeriesNumber"),
    (Tag.InstanceNumber, "InstanceNumber"),
)

# Per-SOP-class IOD profiles keyed by SOP Class UID string.
_IOD_PROFILES: Dict[str, _IodProfile] = {
    # CT Image Storage
    "1.2.840.10008.5.1.4.1.1.2": _IodProfile(
        name="CT Image Storage",
        type1=_COMMON_TYPE1 + (
            (Tag.ImageType, "ImageType"),
            (Tag.RescaleIntercept, "RescaleIntercept"),
            (Tag.RescaleSlope, "RescaleSlope"),
        ),
        type2=_COMMON_TYPE2 + (
            (Tag.KVP, "KVP"),
            (Tag.AcquisitionNumber, "AcquisitionNumber"),
        ),
    ),
    # MR Image Storage
    "1.2.840.10008.5.1.4.1.1.4": _IodProfile(
        name="MR Image Storage",
        type1=_COMMON_TYPE1 + (
            (Tag.ImageType, "ImageType"),
            (Tag.ScanningSequence, "ScanningSequence"),
            (Tag.SequenceVariant, "SequenceVariant"),
        ),
        type2=_COMMON_TYPE2,
    ),
    # Ultrasound Image Storage
    "1.2.840.10008.5.1.4.1.1.6.1": _IodProfile(
        name="Ultrasound Image Storage",
        type1=_COMMON_TYPE1,
        type2=_COMMON_TYPE2,
    ),
    # Computed Radiography Image Storage
    "1.2.840.10008.5.1.4.1.1.1": _IodProfile(
        name="CR Image Storage",
        type1=_COMMON_TYPE1 + (
            (Tag.ImageType, "ImageType"),
        ),
        type2=_COMMON_TYPE2 + (
            (Tag.BodyPartExamined, "BodyPartExamined"),
        ),
    ),
    # Secondary Capture includes the image-pixel module baseline.
    "1.2.840.10008.5.1.4.1.1.7": _IodProfile(
        name="Secondary Capture Image Storage",
        type1=_COMMON_TYPE1,
        type2=_COMMON_TYPE2,
    ),
}


def validate_for_sop_class_detailed(
    dataset: DicomDataset,
    sop_class_uid: Optional[str] = None,
) -> List[ValidationIssue]:
    """Validate *dataset* against the mandatory attributes for its SOP Class.

    Checks DICOM Type 1 (required, non-empty) and Type 2 (required, may be
    empty) tag requirements for common image storage SOP Classes.  Type 3
    (optional) and conditional attributes are not checked.

    Supported SOP classes
    ---------------------
    * CT Image Storage (1.2.840.10008.5.1.4.1.1.2)
    * MR Image Storage (1.2.840.10008.5.1.4.1.1.4)
    * Ultrasound Image Storage (1.2.840.10008.5.1.4.1.1.6.1)
    * CR Image Storage (1.2.840.10008.5.1.4.1.1.1)
    * Secondary Capture Image Storage (1.2.840.10008.5.1.4.1.1.7)

    For unrecognised SOP Classes the function returns a single informational
    issue rather than raising, so callers can always iterate the result.

    Parameters
    ----------
    dataset:
        The dataset to validate.
    sop_class_uid:
        Override the SOP Class UID to validate against.  When *None* (the
        default) the value is read from ``dataset.SOPClassUID``.

    Returns
    -------
    List[ValidationIssue]
        Structured issue objects, empty when no issues are found.  Messages are
        prefixed with ``[error]`` (Type 1 violations) or ``[error]`` (Type 2
        violations) for compatibility with the string-only wrapper.

    Examples
    --------
    ::

        from dicomforge.api import validate_for_sop_class_detailed
        from dicomforge.uids import SopClassUID

        issues = validate_for_sop_class_detailed(dataset, SopClassUID.CTImageStorage)
        for issue in issues:
            print(issue.severity, issue.tag, issue.message)
    """
    dataset = as_dataset(dataset)
    uid = sop_class_uid or str(dataset.get(Tag.SOPClassUID) or "").strip()
    if not uid:
        return [
            ValidationIssue(
                severity="error",
                message=(
                    "[error] SOPClassUID is absent — cannot determine which IOD "
                    "to validate against."
                ),
                code="missing-sop-class",
                tag=Tag.SOPClassUID,
                label="SOPClassUID",
            )
        ]

    profile = _IOD_PROFILES.get(uid)
    if profile is None:
        return [
            ValidationIssue(
                severity="warning",
                message=(
                    f"[warning] SOP Class {uid!r} is not in the built-in IOD profile table. "
                    "No mandatory-attribute checks were performed."
                ),
                code="unsupported-sop-class-profile",
                sop_class_uid=uid,
                assessed=False,
            )
        ]

    issues: List[ValidationIssue] = []

    for tag, label in profile.type1:
        val = dataset.get(tag)
        if _empty_value(val):
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=(
                        f"[error] {profile.name} requires {label} {tag} "
                        "(Type 1 — must be present and non-empty)."
                    ),
                    code="missing-type1-attribute",
                    tag=tag,
                    label=label,
                    requirement="Type 1",
                    sop_class_uid=uid,
                    sop_class_name=profile.name,
                )
            )

    for tag, label in profile.type2:
        if tag not in dataset:
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=(
                        f"[error] {profile.name} requires {label} {tag} "
                        "(Type 2 — must be present, may be empty)."
                    ),
                    code="missing-type2-attribute",
                    tag=tag,
                    label=label,
                    requirement="Type 2",
                    sop_class_uid=uid,
                    sop_class_name=profile.name,
                )
            )

    return issues


def _empty_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (bytes, bytearray, list, tuple, DicomDataset)):
        return len(value) == 0
    return False


def validate_elements_detailed(dataset: DicomDataset) -> List[ValidationIssue]:
    """VR/VM and UID checks with indexed paths, separate from IOD conformance.

    Empty required attributes are checked by the SOP profile, not this lint.
    Private UN values remain opaque. An unrecognized public VR is not a pass.
    """
    from dicomforge.dictionary import NUMERIC_VR_FORMATS, standard_dictionary
    from collections.abc import Sequence
    dataset = as_dataset(dataset)
    issues: List[ValidationIssue] = []
    for path, element in dataset.iter_paths():
        value, vr, tag = element.value, element.vr, element.tag
        code = None
        if _empty_value(value):
            continue
        values = list(value) if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ) else [value]
        if vr == "UI" and any(not is_valid_uid(str(item)) for item in values):
            code = "invalid-element-uid"
        elif vr in NUMERIC_VR_FORMATS:
            import math
            import struct
            try:
                fmt = NUMERIC_VR_FORMATS[vr]
                for item in values:
                    if vr in {"FL", "FD"}:
                        if not math.isfinite(float(item)):
                            raise ValueError
                    struct.pack("<" + fmt, item)
            except (TypeError, ValueError, OverflowError, struct.error):
                code = "invalid-numeric-value"
        elif vr == "SQ" and (not isinstance(value, (list, tuple)) or any(
            not isinstance(item, DicomDataset) for item in values
        )):
            code = "invalid-sequence-value"
        entry = standard_dictionary().get(f"{tag.group:04X}{tag.element:04X}")
        if code is None and entry is not None and vr != "SQ":
            vm = entry[2]
            count = len(values)
            try:
                if "-" not in vm:
                    valid_vm = count == int(vm)
                else:
                    low, high = vm.split("-", 1)
                    valid_vm = count >= int(low) and (
                        high == "n" or (high.endswith("n") and count % int(high[:-1]) == 0)
                        or (high.isdigit() and count <= int(high)))
                if not valid_vm:
                    code = "invalid-value-multiplicity"
            except ValueError:
                pass
        if code:
            issues.append(ValidationIssue("error", code.replace("-", " "), code,
                                           tag=tag, path=path,
                                           standard="PS3.5 VR/VM; dictionary=pydicom-3.0.2"))
    return issues


def validate_for_sop_class(
    dataset: DicomDataset,
    sop_class_uid: Optional[str] = None,
) -> List[str]:
    """Return human-readable mandatory-attribute issues for a SOP Class.

    This compatibility wrapper preserves the original list-of-strings API.
    Use :func:`validate_for_sop_class_detailed` for structured severity, tag,
    and requirement fields.
    """

    return [
        str(issue)
        for issue in validate_for_sop_class_detailed(dataset, sop_class_uid)
    ]


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
    destinations: Dict[Path, List[Path]] = {}
    for raw_path in input_paths:
        source = Path(raw_path)
        destinations.setdefault((output_directory / source.name).resolve(), []).append(source)
    source_paths = {Path(path).resolve() for path in input_paths}
    for raw_path in input_paths:
        src = Path(raw_path)
        dest = output_directory / src.name
        try:
            if len(destinations[dest.resolve()]) > 1 or dest.resolve() in source_paths:
                raise ValueError("Batch destination collision; use release_collection for UID naming")
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
