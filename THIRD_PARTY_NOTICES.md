# Third-party notices

DICOMForge source is MIT licensed. Core operation requires only Python's standard
library. Optional extras are installed and licensed separately:

- pydicom: MIT; file/data and pixel-codec integration.
- NumPy: BSD-3-Clause source; tested wheel also declares 0BSD, MIT, Zlib and
  CC0-1.0 components; optional arrays.
- Pillow: MIT-CMU in the tested current release (older releases used HPND);
  optional previews.
- requests: Apache-2.0; optional HTTP transport.
- pynetdicom: MIT; optional DIMSE integration.

The bundled compressed dictionary is derived from pydicom 3.0.2's DicomDictionary.
The original license is included at src/dicomforge/data/PYDICOM-LICENSE. Its
snapshot/provenance is recorded beside the artifact and regenerated using the
pinned development tool. It is not a runtime dependency on pydicom.

External JPEG-family plugins, NumPy transitive components, operating-system TLS,
and deployment infrastructure have their own licenses. Review the installed
artifact set for your deployment. `python -m pip inspect` can record the resolved
dependency inventory; CI's built wheel and lock/deployment choices should be
retained with a commercial validation record.
