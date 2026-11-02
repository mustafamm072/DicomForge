"""Dependency-free study validation and reproducible local data releases.

The declared release scope is conventional CT/MR metadata. Pixel identity,
recognizable anatomy, and acquisition completeness require external assessment.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Union

from dicomforge import io
from dicomforge.anonymize import AnonymizationAction, AnonymizationPlan, Rule, UidRemapper
from dicomforge.api import _empty_value, validate_dataset_detailed, validate_elements_detailed
from dicomforge.dataset import DicomDataset, as_dataset
from dicomforge.errors import DicomValidationError
from dicomforge.pixels import FrameMetadata
from dicomforge.storage import write_bytes
from dicomforge.tags import Tag
from dicomforge.uids import SopClassUID

PathLike = Union[str, Path]
_SUPPORTED = {SopClassUID.CTImageStorage, SopClassUID.MRImageStorage}
_VERSION = "1"


@dataclass(frozen=True)
class CollectionIssue:
    code: str
    severity: str
    instance: int
    message: str


@dataclass
class CollectionReport:
    instances: int
    bytes_on_disk: int
    max_decoded_frame_bytes: int
    issues: list[CollectionIssue]
    scope: str = "conventional-ct-mr-metadata-v1"
    unchecked: tuple[str, ...] = ("pixel-identity", "recognizable-anatomy", "acquisition-completeness")

    @property
    def status(self) -> str:
        if any(issue.severity == "error" for issue in self.issues):
            return "quarantined"
        return "needs_review" if self.issues else "accepted"

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": _VERSION, "status": self.status, "scope": self.scope,
                "instances": self.instances, "bytes_on_disk": self.bytes_on_disk,
                "max_decoded_frame_bytes": self.max_decoded_frame_bytes,
                "unchecked": list(self.unchecked), "issues": [
                    {"code": issue.code, "severity": issue.severity, "instance": issue.instance,
                     "message": issue.message} for issue in self.issues]}


def validate_collection(
    datasets: Iterable[Any], *, require_reference_closure: bool = False,
    max_frame_bytes: int = 512 * 1024 * 1024,
) -> CollectionReport:
    """Validate datasets or read-only pydicom views without copying pixel buffers.

    Findings identify inputs by ordinal, never by patient identifier or filename.
    'accepted' refers only to the explicitly declared metadata scope.
    """
    if max_frame_bytes <= 0:
        raise ValueError("max_frame_bytes must be positive")
    items = [as_dataset(dataset) for dataset in datasets]
    report = CollectionReport(len(items), 0, 0, [])
    def issue(code: str, severity: str, index: int, message: str) -> None:
        report.issues.append(CollectionIssue(code, severity, index, message))
    if not items:
        issue("empty-collection", "error", 0, "No DICOM instances were supplied")
        return report
    seen: dict[str, int] = {}
    series: dict[str, list[tuple[int, DicomDataset]]] = {}
    for index, ds in enumerate(items):
        for finding in validate_dataset_detailed(ds):
            issue(finding.code, finding.severity, index, finding.code.replace("-", " "))
        for finding in validate_elements_detailed(ds):
            issue(finding.code, finding.severity, index, finding.code.replace("-", " "))
        uid = str(ds.get(Tag.SOPInstanceUID) or "")
        if uid in seen:
            issue("duplicate-instance", "error", index, "Repeated SOP instance identity")
        seen[uid] = index
        if str(ds.get(Tag.SOPClassUID)) not in _SUPPORTED:
            issue("unsupported-collection-scope", "warning", index,
                  "Geometry/release policy supports conventional CT and MR only")
        if int(ds.get(Tag.NumberOfFrames) or 1) != 1:
            issue("unsupported-multiframe-geometry", "warning", index,
                  "Per-frame functional group geometry was not assessed")
        if any(tag.group in range(0x6000, 0x6020) or tag == Tag.parse("EncapsulatedDocument")
               or tag == Tag.parse("ContentSequence") for tag in ds):
            issue("unsupported-identity-content", "warning", index,
                  "Overlays, documents, and structured text require a separate policy")
        if str(ds.get(Tag.BurnedInAnnotation) or "").upper() != "NO":
            issue("pixel-identity-unassessed", "warning", index,
                  "Pixel identity requires external review")
        try:
            meta = FrameMetadata.from_dataset(ds)
            size = meta.frame_values * max(1, meta.bytes_per_sample)
            report.max_decoded_frame_bytes = max(report.max_decoded_frame_bytes, size)
            if size > max_frame_bytes:
                issue("frame-budget-exceeded", "error", index, "Decoded frame exceeds job budget")
        except (ValueError, TypeError):
            pass  # structural validation already records invalid pixel metadata
        series.setdefault(str(ds.get(Tag.SeriesInstanceUID) or ""), []).append((index, ds))
    for group in series.values():
        baseline = group[0][1]
        positions: list[tuple[int, float]] = []
        for index, ds in group:
            for tag in (Tag.StudyInstanceUID, Tag.FrameOfReferenceUID, Tag.Rows, Tag.Columns,
                        Tag.PixelSpacing, Tag.ImageOrientationPatient, Tag.Modality,
                        Tag.RescaleSlope, Tag.RescaleIntercept):
                if ds.get(tag) != baseline.get(tag):
                    issue("inconsistent-series-metadata", "error", index,
                          f"Series metadata disagrees at {tag}")
            orientation = ds.get(Tag.ImageOrientationPatient)
            position = ds.get(Tag.ImagePositionPatient)
            spacing = ds.get(Tag.PixelSpacing)
            try:
                if len(orientation) != 6 or len(position) != 3 or len(spacing) != 2:
                    raise ValueError
                row, column = [float(v) for v in orientation[:3]], [float(v) for v in orientation[3:]]
                vectors = row + column + [float(v) for v in position] + [float(v) for v in spacing]
                if not all(math.isfinite(v) for v in vectors) or any(float(v) <= 0 for v in spacing):
                    raise ValueError
                if any(abs(sum(v * v for v in axis) - 1) > 1e-4 for axis in (row, column)):
                    raise ValueError
                if abs(sum(a * b for a, b in zip(row, column))) > 1e-4:
                    raise ValueError
                normal = [row[1]*column[2] - row[2]*column[1],
                          row[2]*column[0] - row[0]*column[2],
                          row[0]*column[1] - row[1]*column[0]]
                positions.append((index, sum(a * float(b) for a, b in zip(normal, position))))
            except (TypeError, ValueError, IndexError):
                issue("geometry-unassessed", "warning", index,
                      "Missing or invalid orientation, position, or pixel spacing")
        ordered = sorted(positions, key=lambda item: item[1])
        gaps = [b[1] - a[1] for a, b in zip(ordered, ordered[1:])]
        if any(abs(gap) < 1e-5 for gap in gaps):
            issue("duplicate-plane", "error", ordered[0][0], "Repeated spatial plane in series")
        if len(gaps) > 1 and max(gaps) - min(gaps) > max(1e-3, abs(gaps[0]) * 0.01):
            issue("irregular-slice-spacing", "warning", ordered[0][0],
                  "Series does not form a regularly spaced volume")
    if require_reference_closure:
        for index, ds in enumerate(items):
            for _, element in ds.iter_paths():
                if element.tag == Tag.ReferencedSOPInstanceUID and str(element.value) not in seen:
                    issue("missing-reference", "error", index, "Referenced instance is outside collection")
    return report


def inspect_collection(
    paths: Iterable[PathLike], *, max_input_bytes: int = 2 * 1024 ** 3,
    max_frame_bytes: int = 512 * 1024 * 1024, require_reference_closure: bool = False,
) -> CollectionReport:
    """Read metadata with the native mmap reader and report job resource requirements."""
    if max_input_bytes <= 0:
        raise ValueError("max_input_bytes must be positive")
    datasets = []
    total = 0
    for path in paths:
        size = Path(path).stat().st_size
        if size > max_input_bytes:
            raise DicomValidationError("Input exceeds max_input_bytes")
        total += size
        datasets.append(io.read(path, stop_before_pixels=True))
    report = validate_collection(datasets, max_frame_bytes=max_frame_bytes,
                                 require_reference_closure=require_reference_closure)
    report.bytes_on_disk = total
    return report


@dataclass(frozen=True)
class ReleasePolicy:
    """Explicit project key and policy identity; no key appears in repr/manifests."""

    namespace: str
    key: bytes = field(repr=False)
    version: str = "ct-mr-metadata-v1"
    longitudinal_dates: bool = False
    pixels_reviewed: bool = False

    def __post_init__(self) -> None:
        if not self.namespace or len(self.key) < 32:
            raise ValueError("Release requires a namespace and at least 32 key bytes")

    def _digest(self, purpose: str, value: str) -> bytes:
        data = json.dumps([self.namespace, purpose, value], separators=(",", ":")).encode()
        return hmac.new(self.key, data, hashlib.sha256).digest()

    def fingerprint(self) -> str:
        """Detect policy/key changes on resume without recording the key."""
        config = json.dumps([self.version, self.longitudinal_dates, self.pixels_reviewed])
        return self._digest("policy", config).hex()

    def transform(self, dataset: DicomDataset) -> DicomDataset:
        from dicomforge.anonymize import _shift_date_value
        ds = dataset.copy(deep=True)
        if str(ds.get(Tag.SOPClassUID)) not in _SUPPORTED:
            raise DicomValidationError("Release scope supports conventional CT/MR only")
        if not self.pixels_reviewed:
            raise DicomValidationError("Release requires explicit external pixel identity review")
        if int(ds.get(Tag.NumberOfFrames) or 1) != 1:
            raise DicomValidationError("Multiframe release geometry is not yet supported")
        subject = json.dumps([str(ds.get("IssuerOfPatientID") or ""),
                              str(ds.get(Tag.PatientID) or "")])
        if not ds.get(Tag.PatientID):
            raise DicomValidationError("Subject linkage requires PatientID and optional issuer")
        pseudonym = self._digest("subject", subject).hex()[:32]
        remapper = UidRemapper(key=self.key, namespace=self.namespace)
        base = AnonymizationPlan.starter_profile()
        rules = list(base._rules)
        if self.longitudinal_dates:
            offset = int.from_bytes(self._digest("dates", subject)[:4], "big") % 7301 - 3650
            offset = offset or 1
            for _, element in ds.iter_paths():
                if element.vr in {"DA", "DT"} and element.value:
                    values = element.value if isinstance(element.value, (list, tuple)) else [element.value]
                    for value in values:
                        if not isinstance(value, str) or len(value) < 8 or (
                            _shift_date_value(value, offset) == value
                        ):
                            raise DicomValidationError("Partial or invalid date requires policy review")
                    rules.append(Rule(element.tag, AnonymizationAction.SHIFT_DATE, offset))
            rules.append(Rule(Tag.LongitudinalTemporalInformationModified,
                              AnonymizationAction.REPLACE, "MODIFIED"))
        rules.extend([Rule(Tag.PatientID, AnonymizationAction.REPLACE, pseudonym),
                      Rule(Tag.PatientName, AnonymizationAction.REPLACE, f"Subject^{pseudonym[:12]}")])
        # Unstructured descriptions can contain identifiers even in conventional images.
        for name in ("StudyDescription", "SeriesDescription", "ProtocolName", "ImageComments",
                     "IssuerOfPatientID", "InstanceCreationDate", "InstanceCreationTime"):
            rules.append(Rule(Tag.parse(name), AnonymizationAction.DELETE))
        AnonymizationPlan(rules, uid_remapper=remapper).apply(ds)
        # Conservative residual text/date handling beyond named starter rules.
        for path, element in list(ds.iter_paths()):
            if _empty_value(element.value):
                continue  # Preserve empty Type 2 attributes; they contain no identity value.
            target = ds
            for offset in range(0, len(path) - 1, 2):
                target = target[path[offset]][path[offset + 1]]
            tag, vr = element.tag, element.vr
            if vr == "PN" and tag != Tag.PatientName:
                target[tag] = ""
            elif vr in {"LT", "ST", "UT"}:
                target.pop(tag, None)
            elif vr in {"LO", "SH"} and tag not in {
                Tag.PatientID, Tag.DeidentificationMethod, Tag.RescaleType,
                Tag.Manufacturer, Tag.ManufacturerModelName, Tag.SoftwareVersions,
            } and tag.group != 2:
                target.pop(tag, None)
            elif vr in {"DA", "DT", "TM"} and not self.longitudinal_dates:
                target[tag] = ""
        return ds


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def release_collection(
    paths: Iterable[PathLike], output_dir: PathLike, policy: ReleasePolicy, *,
    dry_run: bool = False, resume: bool = False, max_input_bytes: int = 2 * 1024 ** 3,
    max_frame_bytes: int = 512 * 1024 * 1024,
) -> dict[str, Any]:
    """Preflight, transform, reopen, validate, and checkpoint a local release.

    Each instance and checkpoint is atomic. The whole collection is not one
    filesystem transaction. On interruption, resume verifies source and output
    integrity before reusing completed instances. Manifests omit source paths,
    original UIDs and patient values. Treat even keyed tokens as controlled data.
    """
    from dicomforge import __version__
    sources = [Path(path).resolve() for path in paths]
    report = inspect_collection(sources, max_input_bytes=max_input_bytes,
                                 max_frame_bytes=max_frame_bytes, require_reference_closure=True)
    blocking = [issue for issue in report.issues if issue.severity == "error" or (
        issue.code != "pixel-identity-unassessed" or not policy.pixels_reviewed)]
    if blocking:
        raise DicomValidationError("Collection requires review: " + ", ".join(sorted({i.code for i in blocking})))
    destination = Path(output_dir).resolve()
    if any(destination == path.parent or destination in path.parents for path in sources):
        raise DicomValidationError("Release output must be separate from source directories")
    manifest: dict[str, Any] = {
        "schema_version": _VERSION, "tool": "dicomforge", "tool_version": __version__,
        "policy_version": policy.version, "policy_fingerprint": policy.fingerprint(),
        "mapping_strategy": "hmac-sha256-v1", "backend": "native", "completed": False,
        "unchecked": ["recognizable-anatomy", "acquisition-completeness"], "instances": [],
    }
    manifest_path = destination / "manifest.json"
    if dry_run:
        return {**manifest, "dry_run": True, "plan": report.to_dict()}
    destination.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        if not resume:
            raise FileExistsError("Release manifest already exists; use resume explicitly")
        previous = json.loads(manifest_path.read_text())
        if previous.get("policy_fingerprint") != manifest["policy_fingerprint"] or (
            previous.get("tool_version") != __version__
        ):
            raise DicomValidationError("Resume requires identical tool, policy and key")
        manifest = previous
    completed = {item["source_token"]: item for item in manifest["instances"]}
    tokens = [policy._digest("source", _file_digest(path)).hex() for path in sources]
    source_set = policy._digest("collection", json.dumps(sorted(tokens))).hex()
    if manifest_path.exists() and resume and manifest.get("source_set") != source_set:
        raise DicomValidationError("Resume requires the same source collection")
    manifest["source_set"] = source_set
    if resume and not set(completed).issubset(tokens):
        raise DicomValidationError("Resume source collection changed")
    def checkpoint() -> None:
        write_bytes(manifest_path, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    checkpoint()
    for path, token in zip(sources, tokens):
        if token in completed:
            record = completed[token]
            output = destination / record["file"]
            if output.resolve().parent != destination or output.is_symlink() or (
                _file_digest(output) != record["sha256"]
            ):
                raise DicomValidationError("Completed output failed integrity verification")
            continue
        source_dataset = io.read(path)
        if policy._digest("source", _file_digest(path)).hex() != token:
            raise DicomValidationError("Source changed during release processing")
        transformed = policy.transform(source_dataset)
        uid = str(transformed.require(Tag.SOPInstanceUID))
        output = destination / f"{uid}.dcm"
        if output.exists():
            # Recover a crash after instance publication but before checkpoint.
            expected = hashlib.sha256(__import__("dicomforge.part10", fromlist=["dumps"]).dumps(transformed)).hexdigest()
            if not resume or _file_digest(output) != expected:
                raise FileExistsError("Release destination already exists or conflicts")
        else:
            io.write(output, transformed, overwrite=False)
        restored = io.read(output)
        if any(issue.is_error for issue in validate_dataset_detailed(restored)):
            raise DicomValidationError("Saved output failed structural validation")
        record = {"source_token": token, "file": output.name, "sha256": _file_digest(output),
                  "status": "accepted"}
        manifest["instances"].append(record)
        completed[token] = record
        checkpoint()
    manifest["completed"] = True
    checkpoint()
    return manifest
