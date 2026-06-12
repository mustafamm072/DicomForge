"""File IO adapters."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from dicomforge.charset import PersonName, ensure_text_encodable
from dicomforge.dataset import DicomDataset
from dicomforge.errors import CharacterSetError, DicomValidationError, MissingBackendError
from dicomforge.tags import Tag
from dicomforge.uids import ImplementationUID, TransferSyntaxUID

PathLike = Union[str, Path]

_KNOWN_VR = {
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
    # Patient clinical context
    Tag.BodyPartExamined: "CS",
    Tag.PatientPosition: "CS",
    Tag.ViewPosition: "CS",
    Tag.PatientWeight: "DS",
    Tag.PatientSize: "DS",
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
    if tag == Tag.PixelData:
        bits_allocated = dataset.get(Tag.BitsAllocated, 16)
        try:
            return "OB" if int(bits_allocated) <= 8 else "OW"
        except (TypeError, ValueError):
            return "OW"
    return _KNOWN_VR.get(tag, "UN")


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


def read(path: PathLike, *, stop_before_pixels: bool = False, force: bool = False) -> DicomDataset:
    """Read a DICOM file through the optional pydicom backend."""

    try:
        import pydicom  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "Reading DICOM files requires the optional pydicom backend. "
            "Install with `pip install dicomforge[pydicom]`."
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
) -> None:
    """Write through pydicom using an optional template dataset."""

    try:
        import pydicom  # type: ignore[import-not-found]
    except ImportError as exc:
        raise MissingBackendError(
            "Writing DICOM files requires the optional pydicom backend. "
            "Install with `pip install dicomforge[pydicom]`."
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
