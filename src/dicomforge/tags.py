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
    MediaStorageSOPClassUID: ClassVar["Tag"]
    MediaStorageSOPInstanceUID: ClassVar["Tag"]
    ImplementationClassUID: ClassVar["Tag"]

    # Study / Series / Instance
    StudyDescription: ClassVar["Tag"]
    SeriesDescription: ClassVar["Tag"]
    SeriesNumber: ClassVar["Tag"]
    InstanceNumber: ClassVar["Tag"]
    ImageType: ClassVar["Tag"]
    AcquisitionNumber: ClassVar["Tag"]
    AcquisitionDateTime: ClassVar["Tag"]
    ProtocolName: ClassVar["Tag"]
    RequestedProcedureDescription: ClassVar["Tag"]

    # Equipment
    Manufacturer: ClassVar["Tag"]
    ManufacturerModelName: ClassVar["Tag"]
    DeviceSerialNumber: ClassVar["Tag"]
    SoftwareVersions: ClassVar["Tag"]
    InstitutionalDepartmentName: ClassVar["Tag"]

    # Patient clinical context
    BodyPartExamined: ClassVar["Tag"]
    PatientPosition: ClassVar["Tag"]
    ViewPosition: ClassVar["Tag"]
    PatientComments: ClassVar["Tag"]
    PatientWeight: ClassVar["Tag"]
    PatientSize: ClassVar["Tag"]
    EthnicGroup: ClassVar["Tag"]
    PregnancyStatus: ClassVar["Tag"]
    SmokingStatus: ClassVar["Tag"]
    MedicalAlerts: ClassVar["Tag"]
    Allergies: ClassVar["Tag"]
    AttendingPhysicianName: ClassVar["Tag"]
    RequestingPhysician: ClassVar["Tag"]
    AdmittingDiagnosesDescription: ClassVar["Tag"]

    # Image geometry
    PixelSpacing: ClassVar["Tag"]
    ImagerPixelSpacing: ClassVar["Tag"]
    SliceThickness: ClassVar["Tag"]
    SliceLocation: ClassVar["Tag"]
    SpacingBetweenSlices: ClassVar["Tag"]
    ImagePositionPatient: ClassVar["Tag"]
    ImageOrientationPatient: ClassVar["Tag"]

    # Pixel processing
    SmallestImagePixelValue: ClassVar["Tag"]
    LargestImagePixelValue: ClassVar["Tag"]
    BurnedInAnnotation: ClassVar["Tag"]

    # Referenced SOP sequences
    ReferencedStudySequence: ClassVar["Tag"]
    ReferencedSeriesSequence: ClassVar["Tag"]
    ReferencedSOPClassUID: ClassVar["Tag"]
    ReferencedSOPInstanceUID: ClassVar["Tag"]

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

    def __repr__(self) -> str:
        keyword = next(
            (k for k, v in self._KEYWORDS.items() if v == self), None
        )
        if keyword:
            return f"Tag.{keyword}"
        return f"Tag({self.group:04X},{self.element:04X})"

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
Tag.MediaStorageSOPClassUID = _register_keyword("MediaStorageSOPClassUID", 0x0002, 0x0002)
Tag.MediaStorageSOPInstanceUID = _register_keyword("MediaStorageSOPInstanceUID", 0x0002, 0x0003)
Tag.ImplementationClassUID = _register_keyword("ImplementationClassUID", 0x0002, 0x0012)
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

# --- Study / Series / Instance identification ---
Tag.StudyDescription = _register_keyword("StudyDescription", 0x0008, 0x1030)
Tag.SeriesDescription = _register_keyword("SeriesDescription", 0x0008, 0x103E)
Tag.SeriesNumber = _register_keyword("SeriesNumber", 0x0020, 0x0011)
Tag.InstanceNumber = _register_keyword("InstanceNumber", 0x0020, 0x0013)
Tag.ImageType = _register_keyword("ImageType", 0x0008, 0x0008)
Tag.AcquisitionNumber = _register_keyword("AcquisitionNumber", 0x0020, 0x0012)
Tag.AcquisitionDateTime = _register_keyword("AcquisitionDateTime", 0x0008, 0x002A)
Tag.ProtocolName = _register_keyword("ProtocolName", 0x0018, 0x1030)
Tag.RequestedProcedureDescription = _register_keyword(
    "RequestedProcedureDescription", 0x0032, 0x1070
)

# --- Equipment ---
Tag.Manufacturer = _register_keyword("Manufacturer", 0x0008, 0x0070)
Tag.ManufacturerModelName = _register_keyword("ManufacturerModelName", 0x0008, 0x1090)
Tag.DeviceSerialNumber = _register_keyword("DeviceSerialNumber", 0x0018, 0x1000)
Tag.SoftwareVersions = _register_keyword("SoftwareVersions", 0x0018, 0x1020)
Tag.InstitutionalDepartmentName = _register_keyword(
    "InstitutionalDepartmentName", 0x0008, 0x1040
)

# --- Patient clinical context ---
Tag.BodyPartExamined = _register_keyword("BodyPartExamined", 0x0018, 0x0015)
Tag.PatientPosition = _register_keyword("PatientPosition", 0x0018, 0x5100)
Tag.ViewPosition = _register_keyword("ViewPosition", 0x0018, 0x5101)
Tag.PatientComments = _register_keyword("PatientComments", 0x0010, 0x4000)
Tag.PatientWeight = _register_keyword("PatientWeight", 0x0010, 0x1030)
Tag.PatientSize = _register_keyword("PatientSize", 0x0010, 0x1020)
Tag.EthnicGroup = _register_keyword("EthnicGroup", 0x0010, 0x2160)
Tag.PregnancyStatus = _register_keyword("PregnancyStatus", 0x0010, 0x21C0)
Tag.SmokingStatus = _register_keyword("SmokingStatus", 0x0010, 0x21A0)
Tag.MedicalAlerts = _register_keyword("MedicalAlerts", 0x0010, 0x2000)
Tag.Allergies = _register_keyword("Allergies", 0x0010, 0x2110)
Tag.AttendingPhysicianName = _register_keyword("AttendingPhysicianName", 0x0008, 0x1048)
Tag.RequestingPhysician = _register_keyword("RequestingPhysician", 0x0032, 0x1032)
Tag.AdmittingDiagnosesDescription = _register_keyword(
    "AdmittingDiagnosesDescription", 0x0008, 0x1080
)

# --- Image geometry ---
Tag.PixelSpacing = _register_keyword("PixelSpacing", 0x0028, 0x0030)
Tag.ImagerPixelSpacing = _register_keyword("ImagerPixelSpacing", 0x0018, 0x1164)
Tag.SliceThickness = _register_keyword("SliceThickness", 0x0050, 0x0018)
Tag.SliceLocation = _register_keyword("SliceLocation", 0x0020, 0x1041)
Tag.SpacingBetweenSlices = _register_keyword("SpacingBetweenSlices", 0x0018, 0x0088)
Tag.ImagePositionPatient = _register_keyword("ImagePositionPatient", 0x0020, 0x0032)
Tag.ImageOrientationPatient = _register_keyword("ImageOrientationPatient", 0x0020, 0x0037)

# --- Pixel processing ---
Tag.SmallestImagePixelValue = _register_keyword("SmallestImagePixelValue", 0x0028, 0x0106)
Tag.LargestImagePixelValue = _register_keyword("LargestImagePixelValue", 0x0028, 0x0107)
Tag.BurnedInAnnotation = _register_keyword("BurnedInAnnotation", 0x0028, 0x0301)

# --- Referenced SOP sequences ---
Tag.ReferencedStudySequence = _register_keyword("ReferencedStudySequence", 0x0008, 0x1110)
Tag.ReferencedSeriesSequence = _register_keyword("ReferencedSeriesSequence", 0x0008, 0x1115)
Tag.ReferencedSOPClassUID = _register_keyword("ReferencedSOPClassUID", 0x0008, 0x1150)
Tag.ReferencedSOPInstanceUID = _register_keyword("ReferencedSOPInstanceUID", 0x0008, 0x1155)
