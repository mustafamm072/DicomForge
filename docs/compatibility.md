# Compatibility contract (0.12)

| Capability | Status | Boundary |
| --- | --- | --- |
| Python 3.9–3.14 | Supported | Installed-wheel matrix, core and extras, CLI subprocess tests |
| Zero mandatory dependencies | Supported | Optional backends are not imported by core import; wheel smoke test |
| Standard dictionary | Bundled snapshot | 5,091 entries, pydicom 3.0.2 provenance; explicit VR takes precedence |
| Native uncompressed/deflated I/O | Supported | Four syntaxes; contextual implicit signed VRs; bounded inflation; no byte-for-byte guarantee |
| Metadata-only scans | mmap | Stops before native pixel payload; deflate expands the dataset |
| pydicom adapters | 2.4 / 3.x | Explicit backend; normalized sequences/fragments; tested cross-writes |
| RLE dataset compression | Native | Supported standard 8/16-bit combinations; 32-bit image encoding rejected |
| JPEG/JPEG-LS/JPEG 2000 | Optional | pydicom plus installed decoder plugin; no bundled native JPEG encoders |
| Native integer arrays | Optional NumPy | 1/8/16/32/64 allocation, stored-bit normalization, native YBR_FULL_422 |
| JPEG display previews | Optional NumPy/Pillow | Rescale/linear VOI; not complete presentation-state or diagnostic rendering |
| VR/VM/UID validation | Supported lint | Indexed paths; separate from full IOD conformance |
| Image-profile validation | Partial | CT/MR/US/CR/SC baseline, not all modules/conditions |
| Collection validation | Conventional CT/MR | Single-frame geometry, reference closure, resources; explicit unchecked scopes |
| Reproducible release | Conventional CT/MR metadata | Project key, scalar/multi-valued date shifts, external pixel review, atomic files, manifests, resume |
| Confidentiality profile | Subset | No universal PS3.15, OCR, recognizable-anatomy, SR or document cleaning claim |
| DICOM JSON | Preserved VR/PN/null/bulk | BulkDataURI unresolved; not auto-fetched |
| DICOMweb streams | Supported mechanics | Strict framing, closeable responses, chunk sinks and size limits |
| Retry | Safe methods by default | Replayable bodies, attempt/time budget; uploads need explicit safe semantics |
| STOW outcomes | Typed response parser | Per-instance stored/failed/warnings; empty response is unassessed |
| DIMSE networking | pynetdicom integration | Historical JSON protocol is experimental, not wire compatible |
| Vendor/PACS certification | Not claimed | Requires integration evidence against the deployment's actual versions |

The package keeps its MIT license. Optional dependency licensing and the bundled
dictionary's source license are documented in THIRD_PARTY_NOTICES.md. Python
3.9 can use pydicom 2.4 when newer releases require a newer interpreter.

See [migration](migration-0.12.md), [conformance](conformance.md), and
[release verification](release-verification-0.12.md) for changes and measured results.
