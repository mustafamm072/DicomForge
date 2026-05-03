# Compatibility Matrix

DICOMForge is currently tested against the Python versions listed below.

| Area | Status |
| --- | --- |
| Python 3.9 | Supported in CI |
| Python 3.10 | Supported in CI |
| Python 3.11 | Supported in CI |
| Python 3.12 | Supported in CI |
| Python 3.13 | Supported in CI |
| pydicom 2.4+ | Optional IO backend |
| NumPy/Pillow | Planned optional pixel backend |
| pynetdicom | Planned full DIMSE backend |

## DICOM Scope

| Capability | Current Status |
| --- | --- |
| Typed tag normalization | Implemented |
| Transfer syntax classification | Implemented for common syntaxes |
| Codec capability registry | Implemented |
| Native pixel metadata validation | Implemented |
| Compressed pixel decode | Planned |
| pydicom-backed read/write | Implemented |
| Starter de-identification plan | Implemented |
| Full DICOM PS3.15 de-identification | Planned |
| Async command lifecycle tests | Implemented |
| DICOM Upper Layer wire compatibility | Planned |
| DICOMweb | Planned |
