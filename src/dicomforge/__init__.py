"""Lightweight DICOM processing primitives."""

from dicomforge.anonymize import (
    AnonymizationAction,
    AnonymizationEvent,
    AnonymizationPlan,
    AnonymizationReport,
    AuditEvent,
    AuditReport,
    PrivateTagAction,
    Rule,
    UidRemapper,
)
from dicomforge.api import DicomFile, batch_anonymize, quick_anonymize, validate_dataset
from dicomforge.codecs import Codec, CodecRegistry
from dicomforge.dataset import DicomDataset
from dicomforge.dicomweb import (
    DicomwebClient,
    DicomwebError,
    DicomwebResponse,
    DicomwebTransport,
    MultipartPart,
    QidoQuery,
    UrllibDicomwebTransport,
    build_multipart_related,
    dataset_from_dicom_json,
    dataset_to_dicom_json,
    datasets_from_dicom_json,
    parse_multipart_related,
)
from dicomforge.errors import (
    DicomForgeError,
    DicomValidationError,
    MissingBackendError,
    UnsupportedTransferSyntaxError,
)
from dicomforge.network import (
    Association,
    AssociationClosedError,
    AssociationRejectedError,
    AssociationRequest,
    DimseServer,
    DimseStatus,
    NetworkError,
    open_association,
    start_dimse_server,
)
from dicomforge.pixels import (
    FrameMetadata,
    PixelCapability,
    PixelMetadataError,
    VoiLut,
    apply_voi_window,
    apply_voi_window_from_dataset,
    assert_pixel_data_length,
    check_pixel_capability,
    expected_samples_per_pixel,
    is_monochrome,
    needs_inversion,
    normalize_photometric_interpretation,
    rescale_from_dataset,
    rescale_value,
    rescale_values,
    voi_window_bounds,
)
from dicomforge.tags import Tag
from dicomforge.transfer_syntax import TransferSyntax
from dicomforge.uids import DimseStatusCode, ImplementationUID, SopClassUID, TransferSyntaxUID

__all__ = [
    # Anonymization
    "AnonymizationAction",
    "AnonymizationEvent",
    "AnonymizationPlan",
    "AnonymizationReport",
    "AuditEvent",
    "AuditReport",
    "PrivateTagAction",
    "Rule",
    "UidRemapper",
    # High-level API
    "DicomFile",
    "batch_anonymize",
    "quick_anonymize",
    "validate_dataset",
    # Codecs
    "Codec",
    "CodecRegistry",
    # Core types
    "DicomDataset",
    "Tag",
    "TransferSyntax",
    # Errors
    "DicomForgeError",
    "DicomValidationError",
    "MissingBackendError",
    "NetworkError",
    "PixelMetadataError",
    "UnsupportedTransferSyntaxError",
    # DICOMweb
    "DicomwebClient",
    "DicomwebError",
    "DicomwebResponse",
    "DicomwebTransport",
    "MultipartPart",
    "QidoQuery",
    "UrllibDicomwebTransport",
    "build_multipart_related",
    "dataset_from_dicom_json",
    "dataset_to_dicom_json",
    "datasets_from_dicom_json",
    "parse_multipart_related",
    # Networking
    "Association",
    "AssociationClosedError",
    "AssociationRejectedError",
    "AssociationRequest",
    "DimseServer",
    "DimseStatus",
    "DimseStatusCode",
    "open_association",
    "start_dimse_server",
    # Pixels
    "FrameMetadata",
    "PixelCapability",
    "VoiLut",
    "apply_voi_window",
    "apply_voi_window_from_dataset",
    "assert_pixel_data_length",
    "check_pixel_capability",
    "expected_samples_per_pixel",
    "is_monochrome",
    "needs_inversion",
    "normalize_photometric_interpretation",
    "rescale_from_dataset",
    "rescale_value",
    "rescale_values",
    "voi_window_bounds",
    # UIDs
    "ImplementationUID",
    "SopClassUID",
    "TransferSyntaxUID",
]
