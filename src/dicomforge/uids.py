"""Selected DICOM UID constants and UID utility helpers."""

from __future__ import annotations

import re
import uuid as _uuid
from typing import Optional

# ---------------------------------------------------------------------------
# UID helpers
# ---------------------------------------------------------------------------

_UID_ROOT_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


def is_valid_uid(uid: object) -> bool:
    """Return *True* if *uid* conforms to the DICOM UID grammar (PS3.5 §9.1).

    A well-formed DICOM UID:

    * is a non-empty string of digits and dots,
    * has a total length of at most 64 characters,
    * contains no empty component (no leading, trailing, or consecutive dots),
    * has no component with a leading zero unless that component is ``"0"``.

    Parameters
    ----------
    uid:
        Value to test.  Non-string values always return *False*.

    Examples
    --------
    >>> is_valid_uid("1.2.840.10008.5.1.4.1.1.2")
    True
    >>> is_valid_uid("1.2.03.4")   # leading zero in component
    False
    >>> is_valid_uid("1.2." + "3" * 63)  # too long
    False
    """
    if not isinstance(uid, str) or not uid or len(uid) > 64:
        return False
    components = uid.split(".")
    for component in components:
        # Empty component → leading/trailing/consecutive dot
        if not component:
            return False
        # Components must be all-digit
        if not component.isdigit():
            return False
        # Leading zero only allowed when the component is the single digit "0"
        if len(component) > 1 and component[0] == "0":
            return False
    return True


def generate_uid(root: Optional[str] = None) -> str:
    """Generate a new, globally unique DICOM UID.

    Uses the *2.25* organisational root by default, which is the DICOM-
    standard way to derive a UID from a UUID (PS3.5 §B.2).  A UUID4 integer
    rendered as a decimal number produces at most 39 digits, so the resulting
    UID is at most 45 characters — well within the 64-character limit.

    A custom organisational root may be supplied when you have been assigned
    one by a registration authority.

    Parameters
    ----------
    root:
        Dot-separated numeric UID root (e.g. ``"1.2.840.99999"``).
        Leading/trailing dots and whitespace are stripped automatically.
        Defaults to ``"2.25"`` (UUID-derived UIDs).

    Returns
    -------
    str
        A valid DICOM UID string of length ≤ 64.

    Raises
    ------
    ValueError
        If *root* contains non-numeric components or is too long to leave
        room for a unique suffix.

    Examples
    --------
    >>> uid = generate_uid()
    >>> uid.startswith("2.25.")
    True
    >>> is_valid_uid(uid)
    True
    >>> generate_uid("1.2.840.99999")  # doctest: +ELLIPSIS
    '1.2.840.99999...'
    """
    active_root = "2.25" if root is None else root.strip().strip(".")
    if not _UID_ROOT_RE.match(active_root):
        raise ValueError(
            f"UID root must contain only numeric dot-separated components, "
            f"got {root!r}."
        )
    max_suffix_len = 64 - len(active_root) - 1  # reserve 1 char for the separating dot
    if max_suffix_len < 1:
        raise ValueError(
            f"UID root {root!r} is too long ({len(active_root)} chars); "
            "no room remains for a unique suffix."
        )
    suffix = str(_uuid.uuid4().int)  # decimal integer, at most 39 digits
    return f"{active_root}.{suffix[:max_suffix_len]}"


class SopClassUID:
    """Well-known SOP Class UIDs from DICOM PS3.4."""

    # Infrastructure
    Verification = "1.2.840.10008.1.1"

    # Query / Retrieve
    StudyRootQueryRetrieveInformationModelFind = "1.2.840.10008.5.1.4.1.2.2.1"
    StudyRootQueryRetrieveInformationModelMove = "1.2.840.10008.5.1.4.1.2.2.2"
    StudyRootQueryRetrieveInformationModelGet = "1.2.840.10008.5.1.4.1.2.2.3"
    PatientRootQueryRetrieveInformationModelFind = "1.2.840.10008.5.1.4.1.2.1.1"
    PatientRootQueryRetrieveInformationModelMove = "1.2.840.10008.5.1.4.1.2.1.2"
    PatientRootQueryRetrieveInformationModelGet = "1.2.840.10008.5.1.4.1.2.1.3"

    # Storage — Radiology
    CTImageStorage = "1.2.840.10008.5.1.4.1.1.2"
    EnhancedCTImageStorage = "1.2.840.10008.5.1.4.1.1.2.1"
    MRImageStorage = "1.2.840.10008.5.1.4.1.1.4"
    EnhancedMRImageStorage = "1.2.840.10008.5.1.4.1.1.4.1"
    MRSpectroscopyStorage = "1.2.840.10008.5.1.4.1.1.4.2"
    UltrasoundImageStorage = "1.2.840.10008.5.1.4.1.1.6.1"
    UltrasoundMultiFrameImageStorage = "1.2.840.10008.5.1.4.1.1.3.1"
    SecondaryCaptureImageStorage = "1.2.840.10008.5.1.4.1.1.7"
    MultiFrameGrayscaleByteSecondaryCaptureImageStorage = "1.2.840.10008.5.1.4.1.1.7.2"
    MultiFrameGrayscaleWordSecondaryCaptureImageStorage = "1.2.840.10008.5.1.4.1.1.7.3"
    MultiFrameTrueColorSecondaryCaptureImageStorage = "1.2.840.10008.5.1.4.1.1.7.4"

    # Storage — Nuclear Medicine / PET
    NuclearMedicineImageStorage = "1.2.840.10008.5.1.4.1.1.20"
    PositronEmissionTomographyImageStorage = "1.2.840.10008.5.1.4.1.1.128"
    EnhancedPETImageStorage = "1.2.840.10008.5.1.4.1.1.130"

    # Storage — X-Ray
    DigitalXRayImageStorageForPresentation = "1.2.840.10008.5.1.4.1.1.1.1"
    DigitalXRayImageStorageForProcessing = "1.2.840.10008.5.1.4.1.1.1.1.1"
    DigitalMammographyXRayImageStorageForPresentation = "1.2.840.10008.5.1.4.1.1.1.2"
    XRayRadiofluoroscopicImageStorage = "1.2.840.10008.5.1.4.1.1.12.2"
    XRay3DAngiographicImageStorage = "1.2.840.10008.5.1.4.1.1.13.1.1"
    CRImageStorage = "1.2.840.10008.5.1.4.1.1.1"

    # Storage — Radiotherapy
    RTImageStorage = "1.2.840.10008.5.1.4.1.1.481.1"
    RTDoseStorage = "1.2.840.10008.5.1.4.1.1.481.2"
    RTStructureSetStorage = "1.2.840.10008.5.1.4.1.1.481.3"
    RTBeamsTreatmentRecordStorage = "1.2.840.10008.5.1.4.1.1.481.4"

    # Storage — Pathology / Visible Light
    VLWholeSlideMicroscopyImageStorage = "1.2.840.10008.5.1.4.1.1.77.1.6"

    # Structured Reporting
    BasicTextSRStorage = "1.2.840.10008.5.1.4.1.1.88.11"
    EnhancedSRStorage = "1.2.840.10008.5.1.4.1.1.88.22"
    ComprehensiveSRStorage = "1.2.840.10008.5.1.4.1.1.88.33"
    MammographyCADSRStorage = "1.2.840.10008.5.1.4.1.1.88.50"
    KeyObjectSelectionDocumentStorage = "1.2.840.10008.5.1.4.1.1.88.59"


class TransferSyntaxUID:
    """Well-known Transfer Syntax UIDs from DICOM PS3.5."""

    ImplicitVRLittleEndian = "1.2.840.10008.1.2"
    ExplicitVRLittleEndian = "1.2.840.10008.1.2.1"
    DeflatedExplicitVRLittleEndian = "1.2.840.10008.1.2.1.99"
    ExplicitVRBigEndian = "1.2.840.10008.1.2.2"

    # JPEG
    JPEGBaselineProcess1 = "1.2.840.10008.1.2.4.50"
    JPEGExtendedProcess2and4 = "1.2.840.10008.1.2.4.51"
    JPEGLossless = "1.2.840.10008.1.2.4.70"

    # JPEG-LS
    JPEGLSLossless = "1.2.840.10008.1.2.4.80"
    JPEGLSNearLossless = "1.2.840.10008.1.2.4.81"

    # JPEG 2000
    JPEG2000Lossless = "1.2.840.10008.1.2.4.90"
    JPEG2000 = "1.2.840.10008.1.2.4.91"

    # Other lossless
    RLELossless = "1.2.840.10008.1.2.5"

    # High-throughput
    HighThroughputJPEG2000Lossless = "1.2.840.10008.1.2.4.201"
    HighThroughputJPEG2000 = "1.2.840.10008.1.2.4.202"


class ImplementationUID:
    """DICOMForge implementation identifiers."""

    DicomForge = "2.25.232704779933803271156482379682968710367"


class DimseStatusCode:
    """Common DIMSE status codes from DICOM service class behavior."""

    Success = 0x0000
    Pending = 0xFF00
    Cancel = 0xFE00
    UnableToProcess = 0xC000
    OutOfResources = 0xA700
    IdentifierDoesNotMatchSOPClass = 0xA900
    DataSetDoesNotMatchSOPClass = 0xA101
    CannotUnderstand = 0xC000
