"""Selected DICOM UID constants used by DICOMForge APIs."""

from __future__ import annotations


class SopClassUID:
    """Well-known SOP Class UIDs from DICOM PS3.4."""

    Verification = "1.2.840.10008.1.1"
    StudyRootQueryRetrieveInformationModelFind = "1.2.840.10008.5.1.4.1.2.2.1"
    StudyRootQueryRetrieveInformationModelMove = "1.2.840.10008.5.1.4.1.2.2.2"
    CTImageStorage = "1.2.840.10008.5.1.4.1.1.2"
    MRImageStorage = "1.2.840.10008.5.1.4.1.1.4"
    SecondaryCaptureImageStorage = "1.2.840.10008.5.1.4.1.1.7"


class TransferSyntaxUID:
    """Well-known Transfer Syntax UIDs from DICOM PS3.5."""

    ImplicitVRLittleEndian = "1.2.840.10008.1.2"
    ExplicitVRLittleEndian = "1.2.840.10008.1.2.1"
    DeflatedExplicitVRLittleEndian = "1.2.840.10008.1.2.1.99"
    ExplicitVRBigEndian = "1.2.840.10008.1.2.2"
    JPEGBaselineProcess1 = "1.2.840.10008.1.2.4.50"
    JPEGLossless = "1.2.840.10008.1.2.4.70"
    JPEGLSLossless = "1.2.840.10008.1.2.4.80"
    JPEG2000Lossless = "1.2.840.10008.1.2.4.90"
    RLELossless = "1.2.840.10008.1.2.5"


class ImplementationUID:
    """DICOMForge implementation identifiers."""

    DicomForge = "2.25.232704779933803271156482379682968710367"


class DimseStatusCode:
    """Common DIMSE status codes from DICOM service class behavior."""

    Success = 0x0000
    Pending = 0xFF00
    Cancel = 0xFE00
    UnableToProcess = 0xC000
