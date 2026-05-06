"""Selected DICOM UID constants used by DICOMForge APIs."""

from __future__ import annotations


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
