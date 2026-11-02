"""Versioned DICOM dictionary snapshot and Value Representation metadata.

This module is the single source of truth for the small VR data dictionary the
library uses when it needs to know a tag's Value Representation without an
explicit VR in the byte stream (Implicit VR Little Endian) or when serialising a
:class:`~dicomforge.dataset.DicomDataset` to disk.

It is deliberately dependency-free.  The dictionary covers the tags DicomForge
models natively; tags outside the dictionary resolve to ``"UN"`` (Unknown),
which the native reader/writer treats as opaque bytes so that unrecognised
private or vendor attributes are never silently corrupted.
"""

from __future__ import annotations

from typing import Optional
from functools import lru_cache

from dicomforge.tags import Tag

# ---------------------------------------------------------------------------
# Value Representation categories (DICOM PS3.5 §6.2, §7.1)
# ---------------------------------------------------------------------------

#: VRs whose *explicit* encoding uses a 4-byte length preceded by two reserved
#: bytes (the "long form" header).  All other VRs use a 2-byte length.
LONG_FORM_VRS = frozenset(
    {"OB", "OD", "OF", "OL", "OV", "OW", "SQ", "UC", "UN", "UR", "UT", "SV", "UV"}
)

#: VRs whose value is opaque binary data, surfaced to Python as ``bytes``.
BYTES_VRS = frozenset({"OB", "OD", "OF", "OL", "OV", "OW", "UN"})

#: Numeric binary VRs mapped to their ``struct`` format character (one element).
#: ``struct`` byte-order prefixes (``"<"``/``">"``) are applied by the caller.
NUMERIC_VR_FORMATS = {
    "US": "H",
    "SS": "h",
    "UL": "I",
    "SL": "i",
    "FL": "f",
    "FD": "d",
    "SV": "q",
    "UV": "Q",
}

#: VRs whose value is character data (surfaced to Python as ``str``).
TEXT_VRS = frozenset(
    {
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
        "UI",
        "UR",
        "UT",
    }
)

#: Text VRs that may *not* be split on ``"\\"`` into multiple values: the long
#: text VRs treat backslash as an ordinary character, and ``UR`` holds a single
#: URI.  Every other text VR uses ``"\\"`` as the value-multiplicity separator.
SINGLE_VALUE_TEXT_VRS = frozenset({"LT", "ST", "UT", "UR"})

#: Text VRs that carry numbers and are coerced to ``float`` / ``int`` on read.
NUMERIC_STRING_VRS = frozenset({"DS", "IS"})
ALL_VRS = TEXT_VRS | BYTES_VRS | frozenset(NUMERIC_VR_FORMATS) | {"SQ", "AT"}

#: Character-set-sensitive text VRs.  Other text VRs are restricted to the
#: DICOM default repertoire and are always handled as ASCII.
CHARSET_TEXT_VRS = frozenset({"LO", "LT", "PN", "SH", "ST", "UC", "UT"})

#: Special "item" tags used to frame sequence items and encapsulated fragments.
ITEM_TAG = Tag(0xFFFE, 0xE000)
ITEM_DELIMITER_TAG = Tag(0xFFFE, 0xE00D)
SEQUENCE_DELIMITER_TAG = Tag(0xFFFE, 0xE0DD)

#: Length value marking a defined-as-undefined (delimited) item or element.
UNDEFINED_LENGTH = 0xFFFFFFFF


def padding_byte(vr: str) -> bytes:
    """Return the byte used to pad an odd-length *vr* value to even length."""

    if vr == "UI":
        return b"\x00"
    if vr in TEXT_VRS:
        return b"\x20"  # space
    return b"\x00"


# ---------------------------------------------------------------------------
# Tag → VR dictionary
# ---------------------------------------------------------------------------

#: VR for each tag DicomForge models natively.  Used for Implicit VR decoding
#: and for serialisation.  Tags absent here resolve to ``"UN"``.
KNOWN_VR = {
    Tag.SpecificCharacterSet: "CS",
    Tag.PatientName: "PN",
    Tag.PatientID: "LO",
    Tag.PatientBirthDate: "DA",
    Tag.PatientSex: "CS",
    Tag.PatientAge: "AS",
    Tag.PatientAddress: "LO",
    Tag.PatientTelephoneNumbers: "SH",
    Tag.OtherPatientIDs: "LO",
    Tag.PatientComments: "LT",
    Tag.PatientWeight: "DS",
    Tag.PatientSize: "DS",
    Tag.EthnicGroup: "SH",
    Tag.PregnancyStatus: "US",
    Tag.SmokingStatus: "CS",
    Tag.MedicalAlerts: "LO",
    Tag.Allergies: "LO",
    Tag.AdmittingDiagnosesDescription: "LT",
    Tag.AccessionNumber: "SH",
    Tag.StudyDate: "DA",
    Tag.SeriesDate: "DA",
    Tag.AcquisitionDate: "DA",
    Tag.ContentDate: "DA",
    Tag.StudyTime: "TM",
    Tag.SeriesTime: "TM",
    Tag.AcquisitionTime: "TM",
    Tag.ContentTime: "TM",
    Tag.InstitutionName: "LO",
    Tag.InstitutionAddress: "ST",
    Tag.ReferringPhysicianName: "PN",
    Tag.PerformingPhysicianName: "PN",
    Tag.OperatorsName: "PN",
    Tag.StationName: "SH",
    Tag.StudyID: "SH",
    Tag.StudyInstanceUID: "UI",
    Tag.SeriesInstanceUID: "UI",
    Tag.SOPInstanceUID: "UI",
    Tag.SOPClassUID: "UI",
    Tag.MediaStorageSOPClassUID: "UI",
    Tag.MediaStorageSOPInstanceUID: "UI",
    Tag.Modality: "CS",
    Tag.TransferSyntaxUID: "UI",
    Tag.ImplementationClassUID: "UI",
    Tag.SamplesPerPixel: "US",
    Tag.PhotometricInterpretation: "CS",
    Tag.PlanarConfiguration: "US",
    Tag.NumberOfFrames: "IS",
    Tag.Rows: "US",
    Tag.Columns: "US",
    Tag.BitsAllocated: "US",
    Tag.BitsStored: "US",
    Tag.HighBit: "US",
    Tag.PixelRepresentation: "US",
    Tag.WindowCenter: "DS",
    Tag.WindowWidth: "DS",
    Tag.RescaleIntercept: "DS",
    Tag.RescaleSlope: "DS",
    Tag.RescaleType: "LO",
    # Study / Series / Instance identification
    Tag.StudyDescription: "LO",
    Tag.SeriesDescription: "LO",
    Tag.SeriesNumber: "IS",
    Tag.InstanceNumber: "IS",
    Tag.ImageType: "CS",
    Tag.AcquisitionNumber: "IS",
    Tag.AcquisitionDateTime: "DT",
    Tag.ProtocolName: "LO",
    Tag.RequestedProcedureDescription: "LO",
    Tag.FrameOfReferenceUID: "UI",
    Tag.LongitudinalTemporalInformationModified: "CS",
    Tag.PatientIdentityRemoved: "CS",
    Tag.DeidentificationMethod: "LO",
    # Equipment
    Tag.Manufacturer: "LO",
    Tag.ManufacturerModelName: "LO",
    Tag.DeviceSerialNumber: "LO",
    Tag.SoftwareVersions: "LO",
    Tag.InstitutionalDepartmentName: "LO",
    # Acquisition parameters
    Tag.KVP: "DS",
    Tag.ScanningSequence: "CS",
    Tag.SequenceVariant: "CS",
    # Patient clinical context
    Tag.BodyPartExamined: "CS",
    Tag.PatientPosition: "CS",
    Tag.ViewPosition: "CS",
    Tag.AttendingPhysicianName: "PN",
    Tag.RequestingPhysician: "PN",
    Tag.BurnedInAnnotation: "CS",
    # Image geometry
    Tag.PixelSpacing: "DS",
    Tag.ImagerPixelSpacing: "DS",
    Tag.SliceThickness: "DS",
    Tag.SliceLocation: "DS",
    Tag.SpacingBetweenSlices: "DS",
    Tag.ImagePositionPatient: "DS",
    Tag.ImageOrientationPatient: "DS",
    # Pixel value range
    Tag.SmallestImagePixelValue: "US",
    Tag.LargestImagePixelValue: "US",
    # Referenced SOP sequences
    Tag.ReferencedStudySequence: "SQ",
    Tag.ReferencedSeriesSequence: "SQ",
    Tag.ReferencedSOPClassUID: "UI",
    Tag.ReferencedSOPInstanceUID: "UI",
}


@lru_cache(maxsize=1)
def standard_dictionary() -> dict[str, list[str]]:
    """Load the bundled versioned dictionary on first use (stdlib only)."""
    import gzip
    import json
    from pathlib import Path

    with gzip.open(Path(__file__).with_name("data") / "dictionary.json.gz", "rt") as stream:
        result: dict[str, list[str]] = json.load(stream)
    return result


def vr_for_tag(
    tag: Tag, *, bits_allocated: Optional[int] = None,
    pixel_representation: Optional[int] = None,
) -> str:
    """Return the Value Representation DicomForge uses for *tag*.

    ``PixelData`` resolves to ``"OB"`` for 8-bit data and ``"OW"`` otherwise
    (controlled by *bits_allocated*).  Group-length elements ``(gggg,0000)``
    resolve to ``"UL"``.  Tags outside :data:`KNOWN_VR` resolve to ``"UN"``.
    """

    if tag == Tag.PixelData:
        if bits_allocated is None:
            return "OW"
        try:
            return "OB" if int(bits_allocated) <= 8 else "OW"
        except (TypeError, ValueError):
            return "OW"
    if tag.element == 0x0000:
        return "UL"  # group length
    entry = standard_dictionary().get(f"{tag.group:04X}{tag.element:04X}")
    vr = entry[0] if entry else KNOWN_VR.get(tag, "UN")
    if " or " in vr:
        if vr == "US or SS":
            return "SS" if pixel_representation == 1 else "US"
        if vr == "OB or OW":
            return "OB" if bits_allocated is not None and bits_allocated <= 8 else "OW"
        return "UN"  # Context-dependent LUT VRs need an explicit declaration.
    return vr
