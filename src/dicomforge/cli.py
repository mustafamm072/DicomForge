"""Small JSON CLI over the same validation and release APIs used by Python callers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from dicomforge import __version__
from dicomforge.collection import ReleasePolicy, inspect_collection, release_collection
from dicomforge.errors import DicomForgeError


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Exit 0: accepted; 1: quarantined/needs review; 2: usage or operational error."""
    parser = argparse.ArgumentParser(prog="dicomforge", description="Validate and release DICOM collections")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("inventory", "validate", "plan", "release"):
        command = subparsers.add_parser(name)
        command.add_argument("paths", nargs="+", type=Path)
        command.add_argument("--max-input-bytes", type=int, default=2 * 1024 ** 3)
        command.add_argument("--max-frame-bytes", type=int, default=512 * 1024 * 1024)
        if name in {"plan", "release"}:
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--namespace", required=True)
            command.add_argument("--key-file", type=Path, required=True,
                                 help="File containing at least 32 secret bytes; never printed")
            command.add_argument("--longitudinal-dates", action="store_true")
            command.add_argument("--pixels-reviewed", action="store_true")
            command.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = []
        for path in args.paths:
            if path.is_dir():
                paths.extend(sorted(path.rglob("*.dcm")))
            else:
                paths.append(path)
        if args.command in {"inventory", "validate"}:
            result = inspect_collection(paths, max_input_bytes=args.max_input_bytes,
                                        max_frame_bytes=args.max_frame_bytes,
                                        require_reference_closure=args.command == "validate")
            print(json.dumps(result.to_dict(), sort_keys=True))
            return 0 if result.status == "accepted" else 1
        policy = ReleasePolicy(args.namespace, args.key_file.read_bytes(),
                                longitudinal_dates=args.longitudinal_dates,
                                pixels_reviewed=args.pixels_reviewed)
        manifest = release_collection(paths, args.output, policy, dry_run=args.command == "plan",
                                       resume=args.resume, max_input_bytes=args.max_input_bytes,
                                       max_frame_bytes=args.max_frame_bytes)
        print(json.dumps(manifest, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, DicomForgeError) as exc:
        # Backend messages and filesystem paths can contain patient identifiers.
        print(json.dumps({"error": type(exc).__name__, "message": "Operation failed; check inputs, policy, and output permissions"}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
