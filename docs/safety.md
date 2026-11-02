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

## Pixel Previews

`adapt.to_pil_image` and `adapt.to_jpeg_preview` are display and integration
helpers. JPEG previews are lossy 8-bit renderings after optional windowing and
photometric conversion; do not use them as diagnostic-quality derived images or
as a substitute for validated modality, presentation state, and viewer behavior.

## Character Sets

`dicomforge.charset` prevents common non-ASCII text mistakes by making
`SpecificCharacterSet` explicit and rejecting text that cannot be encoded with
the declared charset. Legacy DICOM character sets, especially ISO 2022
code-extension data from real modalities, should still be validated with
site-specific fixtures before regulated clinical use.

## Research release policies and manifests (0.12)

A collection acceptance decision names the metadata scope it assessed. Pixel
identity, recognizable anatomy and acquisition completeness remain explicit
unchecked scopes. A NO burned-in annotation flag is not independent proof that
pixels are anonymous. ReleasePolicy requires an explicit external review choice.

Use a managed project key and namespace for confidential pseudonyms. The
low-level starter profile's public default salt is for convenience, not secret
linkage. Do not mix the 0.11 and 0.12 mapping strategies in one collection.
Routine reports and repr omit values; sensitive diagnostic capture and export
are explicit. Preserve access controls on manifests too: hashes and pseudonyms
can still link records. Keep raw mapping registries separate.

Release outputs are atomically published per instance. They are not one atomic
transaction across a whole cohort. Resume verifies completed output integrity
and unchanged source content/key/policy. Keep immutable source inputs during a
job and retain the resulting tool/policy versions with your research record.
