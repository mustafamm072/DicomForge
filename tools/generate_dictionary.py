"""Regenerate the bundled dictionary from the pinned pydicom 3.0.2 snapshot.

This development-only dependency is not needed at runtime. Review source
licensing in src/dicomforge/data/PYDICOM-LICENSE before updating the snapshot.
"""

import gzip
import json
from pathlib import Path

import pydicom
from pydicom._dicom_dict import DicomDictionary

if pydicom.__version__ != "3.0.2":
    raise SystemExit("Dictionary generation requires pydicom==3.0.2")
entries = {f"{tag:08X}": [value[0], value[4], value[1]]
           for tag, value in DicomDictionary.items()}
destination = Path(__file__).resolve().parents[1] / "src/dicomforge/data/dictionary.json.gz"
destination.write_bytes(gzip.compress(json.dumps(entries, sort_keys=True,
                                                separators=(",", ":")).encode(), mtime=0))
print(f"Generated {len(entries)} entries")
