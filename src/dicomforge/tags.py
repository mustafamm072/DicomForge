"""DICOM tag primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Dict, Tuple, Union

from dicomforge.errors import InvalidTagError

TagInput = Union["Tag", int, str, Tuple[int, int]]


@dataclass(frozen=True, order=True)
class Tag:
    """A DICOM tag represented by group and element numbers."""

    group: int
    element: int

    _KEYWORDS: ClassVar[Dict[str, "Tag"]] = {}

    PatientName: ClassVar["Tag"]
    PatientID: ClassVar["Tag"]
    PatientBirthDate: ClassVar["Tag"]
    PatientSex: ClassVar["Tag"]
    PatientAddress: ClassVar["Tag"]
    PatientTelephoneNumbers: ClassVar["Tag"]
    OtherPatientIDs: ClassVar["Tag"]
    PatientAge: ClassVar["Tag"]
    AccessionNumber: ClassVar["Tag"]
    StudyDate: ClassVar["Tag"]
    SeriesDate: ClassVar["Tag"]
    AcquisitionDate: ClassVar["Tag"]
    ContentDate: ClassVar["Tag"]
    StudyTime: ClassVar["Tag"]
    SeriesTime: ClassVar["Tag"]
    AcquisitionTime: ClassVar["Tag"]
    ContentTime: ClassVar["Tag"]
    InstitutionName: ClassVar["Tag"]
    InstitutionAddress: ClassVar["Tag"]
    ReferringPhysicianName: ClassVar["Tag"]
    PerformingPhysicianName: ClassVar["Tag"]
    OperatorsName: ClassVar["Tag"]
    StationName: ClassVar["Tag"]
    StudyID: ClassVar["Tag"]
    StudyInstanceUID: ClassVar["Tag"]
    SeriesInstanceUID: ClassVar["Tag"]
    SOPInstanceUID: ClassVar["Tag"]
    SOPClassUID: ClassVar["Tag"]
    FrameOfReferenceUID: ClassVar["Tag"]
    LongitudinalTemporalInformationModified: ClassVar["Tag"]
    PatientIdentityRemoved: ClassVar["Tag"]
    DeidentificationMethod: ClassVar["Tag"]
    Modality: ClassVar["Tag"]
    TransferSyntaxUID: ClassVar["Tag"]
    SamplesPerPixel: ClassVar["Tag"]
    PhotometricInterpretation: ClassVar["Tag"]
    PlanarConfiguration: ClassVar["Tag"]
    NumberOfFrames: ClassVar["Tag"]
    Rows: ClassVar["Tag"]
    Columns: ClassVar["Tag"]
    BitsAllocated: ClassVar["Tag"]
    BitsStored: ClassVar["Tag"]
    HighBit: ClassVar["Tag"]
    PixelRepresentation: ClassVar["Tag"]
    WindowCenter: ClassVar["Tag"]
    WindowWidth: ClassVar["Tag"]
    RescaleIntercept: ClassVar["Tag"]
    RescaleSlope: ClassVar["Tag"]
    RescaleType: ClassVar["Tag"]
    PixelData: ClassVar["Tag"]

    def __post_init__(self) -> None:
        if not 0 <= self.group <= 0xFFFF or not 0 <= self.element <= 0xFFFF:
            raise InvalidTagError(f"Invalid DICOM tag ({self.group:04X},{self.element:04X})")

    @property
    def value(self) -> int:
        """Return the packed 32-bit integer representation."""

        return (self.group << 16) | self.element

    @property
    def is_private(self) -> bool:
        """Return whether this tag belongs to a private group."""

        return self.group % 2 == 1

    def __str__(self) -> str:
        return f"({self.group:04X},{self.element:04X})"

    @classmethod
    def parse(cls, value: TagInput) -> "Tag":
        """Parse common DICOM tag representations."""

        if isinstance(value, Tag):
            return value
        if isinstance(value, tuple):
            if len(value) != 2:
                raise InvalidTagError(f"Expected a two-item tag tuple, got {value!r}")
            return cls(int(value[0]), int(value[1]))
        if isinstance(value, int):
            return cls((value >> 16) & 0xFFFF, value & 0xFFFF)
        if isinstance(value, str):
            normalized = value.strip()
            keyword = cls._KEYWORDS.get(normalized)
            if keyword is not None:
                return keyword
            if normalized.startswith("(") and normalized.endswith(")"):
                normalized = normalized[1:-1]
            normalized = normalized.replace(" ", "")
            if "," in normalized:
                group, element = normalized.split(",", 1)
                return cls(int(group, 16), int(element, 16))
            if len(normalized) == 8:
                return cls(int(normalized[:4], 16), int(normalized[4:], 16))
        raise InvalidTagError(f"Cannot parse DICOM tag from {value!r}")


def _register_keyword(name: str, group: int, element: int) -> Tag:
    tag = Tag(group, element)
    Tag._KEYWORDS[name] = tag
    return tag


Tag.PatientName = _register_keyword("PatientName", 0x0010, 0x0010)
Tag.PatientID = _register_keyword("PatientID", 0x0010, 0x0020)
Tag.PatientBirthDate = _register_keyword("PatientBirthDate", 0x0010, 0x0030)
Tag.PatientSex = _register_keyword("PatientSex", 0x0010, 0x0040)
Tag.PatientAddress = _register_keyword("PatientAddress", 0x0010, 0x1040)
Tag.PatientTelephoneNumbers = _register_keyword("PatientTelephoneNumbers", 0x0010, 0x2154)
Tag.OtherPatientIDs = _register_keyword("OtherPatientIDs", 0x0010, 0x1000)
Tag.PatientAge = _register_keyword("PatientAge", 0x0010, 0x1010)
Tag.AccessionNumber = _register_keyword("AccessionNumber", 0x0008, 0x0050)
Tag.StudyDate = _register_keyword("StudyDate", 0x0008, 0x0020)
Tag.SeriesDate = _register_keyword("SeriesDate", 0x0008, 0x0021)
Tag.AcquisitionDate = _register_keyword("AcquisitionDate", 0x0008, 0x0022)
Tag.ContentDate = _register_keyword("ContentDate", 0x0008, 0x0023)
Tag.StudyTime = _register_keyword("StudyTime", 0x0008, 0x0030)
Tag.SeriesTime = _register_keyword("SeriesTime", 0x0008, 0x0031)
Tag.AcquisitionTime = _register_keyword("AcquisitionTime", 0x0008, 0x0032)
Tag.ContentTime = _register_keyword("ContentTime", 0x0008, 0x0033)
Tag.InstitutionName = _register_keyword("InstitutionName", 0x0008, 0x0080)
Tag.InstitutionAddress = _register_keyword("InstitutionAddress", 0x0008, 0x0081)
Tag.ReferringPhysicianName = _register_keyword("ReferringPhysicianName", 0x0008, 0x0090)
Tag.PerformingPhysicianName = _register_keyword("PerformingPhysicianName", 0x0008, 0x1050)
Tag.OperatorsName = _register_keyword("OperatorsName", 0x0008, 0x1070)
Tag.StationName = _register_keyword("StationName", 0x0008, 0x1010)
Tag.StudyID = _register_keyword("StudyID", 0x0020, 0x0010)
Tag.StudyInstanceUID = _register_keyword("StudyInstanceUID", 0x0020, 0x000D)
Tag.SeriesInstanceUID = _register_keyword("SeriesInstanceUID", 0x0020, 0x000E)
Tag.SOPInstanceUID = _register_keyword("SOPInstanceUID", 0x0008, 0x0018)
Tag.SOPClassUID = _register_keyword("SOPClassUID", 0x0008, 0x0016)
Tag.FrameOfReferenceUID = _register_keyword("FrameOfReferenceUID", 0x0020, 0x0052)
Tag.LongitudinalTemporalInformationModified = _register_keyword(
    "LongitudinalTemporalInformationModified", 0x0028, 0x0303
)
Tag.PatientIdentityRemoved = _register_keyword("PatientIdentityRemoved", 0x0012, 0x0062)
Tag.DeidentificationMethod = _register_keyword("DeidentificationMethod", 0x0012, 0x0063)
Tag.Modality = _register_keyword("Modality", 0x0008, 0x0060)
Tag.TransferSyntaxUID = _register_keyword("TransferSyntaxUID", 0x0002, 0x0010)
Tag.SamplesPerPixel = _register_keyword("SamplesPerPixel", 0x0028, 0x0002)
Tag.PhotometricInterpretation = _register_keyword("PhotometricInterpretation", 0x0028, 0x0004)
Tag.PlanarConfiguration = _register_keyword("PlanarConfiguration", 0x0028, 0x0006)
Tag.NumberOfFrames = _register_keyword("NumberOfFrames", 0x0028, 0x0008)
Tag.Rows = _register_keyword("Rows", 0x0028, 0x0010)
Tag.Columns = _register_keyword("Columns", 0x0028, 0x0011)
Tag.BitsAllocated = _register_keyword("BitsAllocated", 0x0028, 0x0100)
Tag.BitsStored = _register_keyword("BitsStored", 0x0028, 0x0101)
Tag.HighBit = _register_keyword("HighBit", 0x0028, 0x0102)
Tag.PixelRepresentation = _register_keyword("PixelRepresentation", 0x0028, 0x0103)
Tag.WindowCenter = _register_keyword("WindowCenter", 0x0028, 0x1050)
Tag.WindowWidth = _register_keyword("WindowWidth", 0x0028, 0x1051)
Tag.RescaleIntercept = _register_keyword("RescaleIntercept", 0x0028, 0x1052)
Tag.RescaleSlope = _register_keyword("RescaleSlope", 0x0028, 0x1053)
Tag.RescaleType = _register_keyword("RescaleType", 0x0028, 0x1054)
Tag.PixelData = _register_keyword("PixelData", 0x7FE0, 0x0010)
