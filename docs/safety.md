# Safety Notes

DICOMForge is intended for developer workflows around DICOM metadata, pixel
safety checks, and integration boundaries. It is not a medical device and does
not provide diagnostic interpretation.

## Clinical Use

Before clinical use, validate behavior against:

- your PACS or VNA
- modality-generated studies
- de-identification policy requirements
- file validation tools used by your organization
- real-world character sets and private tags present in your data

## De-Identification

The built-in starter profile reduces common direct identifiers and remaps core
UIDs, but it is not a complete privacy guarantee. Production de-identification
requires a site-specific policy, review of burned-in annotations, private tag
handling, longitudinal UID strategy, and regulatory sign-off.

## Networking

The in-core networking module is for API shape, lifecycle, and backpressure
testing. It is not wire-compatible with PACS systems. Use a DICOM Upper Layer
implementation for real DIMSE interoperability.
