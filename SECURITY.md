# Security Policy

DICOMForge handles data shapes commonly used with protected health information.
Treat every real DICOM object as sensitive unless your organization has already
classified it otherwise.

## Supported Versions

The project is pre-1.0. Security fixes are expected to land on the latest
released version and the main development branch.

## Reporting a Vulnerability

Please report suspected vulnerabilities privately to the maintainers before
public disclosure. Include:

- affected version or commit
- minimal reproduction steps
- whether real patient data was involved
- expected impact

Do not include protected health information in vulnerability reports.

## Data Handling Expectations

- Do not use the starter de-identification profile as the only control for
  HIPAA, GDPR, or clinical trial release workflows.
- Do not send real DICOM files through examples, tests, or issue reports unless
  they are confirmed de-identified by your organization.
- Validate generated DICOM files with your production DICOM toolchain before
  clinical use.
- Use a wire-compatible DIMSE implementation, such as a future
  `dicomforge-network` backend or `pynetdicom`, for PACS interoperability.

## Private contact and response scope

Use the repository's private vulnerability-reporting facility when enabled:
[report privately](https://github.com/mustafamm072/DicomForge/security/advisories/new).
If that facility is unavailable, request a private reporting channel from the
maintainer via their GitHub profile without posting exploit details or data.
There is currently no guaranteed commercial response-time SLA.

For 0.12, routine audit and CLI output omit sensitive values by default. Explicit
sensitive diagnostics, project keys, identity stores, pseudonyms and release
manifests need deployment-specific access controls. Resource limits are part of
the parser/transport contract, not a claim that all untrusted input is safe.
Use the latest patch version and pin/record optional plugin versions in a release
validation record. See THIRD_PARTY_NOTICES.md for dependency provenance.
