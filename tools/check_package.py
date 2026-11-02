"""Check the installed distribution, including a zero-extra core contract."""

import importlib.metadata
import json
import sys
from pathlib import Path

import dicomforge
from dicomforge.dictionary import standard_dictionary

assert dicomforge.__version__ == importlib.metadata.version("dicomforge")
assert len(standard_dictionary()) >= 5000
assert (Path(dicomforge.__file__).parent / "py.typed").is_file()
assert not {"numpy", "PIL", "pydicom", "requests", "pynetdicom"}.intersection(sys.modules)
requirements = importlib.metadata.requires("dicomforge") or []
assert all("extra ==" in requirement or "extra==" in requirement for requirement in requirements)
print(json.dumps({"version": dicomforge.__version__, "dictionary_entries": len(standard_dictionary()),
                  "core_dependencies": 0, "type_marker": True}))
