"""De-identification planning primitives."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dicomforge.dataset import DicomDataset
from dicomforge.tags import Tag, TagInput


class AnonymizationAction(str, Enum):
    DELETE = "delete"
    EMPTY = "empty"
    REPLACE = "replace"
    REMAP_UID = "remap_uid"
    UID_REMAP = "remap_uid"


class PrivateTagAction(str, Enum):
    REMOVE = "remove"
    KEEP = "keep"


@dataclass(frozen=True)
class Rule:
    tag: Tag
    action: AnonymizationAction
    replacement: object = ""


@dataclass(frozen=True)
class AnonymizationEvent:
    """One de-identification action that was applied or skipped."""

    tag: Tag
    action: AnonymizationAction
    before_present: bool
    after_present: bool
    replacement: object = ""
    path: Tuple[Tag, ...] = ()
    previous_value: object = None
    new_value: object = None

    def to_dict(self) -> dict[str, object]:
        return {
            "tag": str(self.tag),
            "action": self.action.value,
            "before_present": self.before_present,
            "after_present": self.after_present,
            "replacement": self.replacement,
            "path": [str(tag) for tag in self.path],
            "previous_value": self.previous_value,
            "new_value": self.new_value,
        }


@dataclass(frozen=True)
class AnonymizationReport:
    """Summary of a de-identification run."""

    events: Sequence[AnonymizationEvent]
    private_tags_removed: int
    private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE

    def to_dict(self) -> dict[str, object]:
        return {
            "events": [event.to_dict() for event in self.events],
            "private_tags_removed": self.private_tags_removed,
            "private_tag_action": self.private_tag_action.value,
        }


AuditEvent = AnonymizationEvent
AuditReport = AnonymizationReport


class UidRemapper:
    """Deterministically replace UIDs while preserving equality relationships."""

    def __init__(self, root: str = "2.25", *, salt: str = "dicomforge") -> None:
        normalized_root = root.strip().rstrip(".")
        if not _UID_ROOT_PATTERN.match(normalized_root) or len(normalized_root) > 60:
            raise ValueError(
                "UID root must contain numeric components separated by dots and leave room "
                "for a generated suffix."
            )
        self.root = normalized_root
        self.salt = salt
        self._cache: Dict[str, str] = {}
        self._lock = threading.Lock()

    def remap(self, uid: object) -> str:
        original = str(uid).strip()
        if not original:
            return ""
        with self._lock:
            cached = self._cache.get(original)
            if cached is not None:
                return cached
            digest = sha256(f"{self.salt}\0{original}".encode("utf-8")).digest()
            suffix = str(int.from_bytes(digest[:16], "big"))
            available = 64 - len(self.root) - 1
            remapped = f"{self.root}.{suffix[:available]}"
            self._cache[original] = remapped
            return remapped


_UID_TAGS = (
    Tag.StudyInstanceUID,
    Tag.SeriesInstanceUID,
    Tag.SOPInstanceUID,
    Tag.FrameOfReferenceUID,
    Tag.MediaStorageSOPInstanceUID,
    Tag.ReferencedSOPInstanceUID,
)

_BASIC_PROFILE_RULES = (
    # Patient identity
    Rule(Tag.PatientName, AnonymizationAction.REPLACE, "Anonymous"),
    Rule(Tag.PatientID, AnonymizationAction.REPLACE, "ANON"),
    Rule(Tag.PatientBirthDate, AnonymizationAction.EMPTY),
    Rule(Tag.PatientSex, AnonymizationAction.EMPTY),
    Rule(Tag.PatientAddress, AnonymizationAction.DELETE),
    Rule(Tag.PatientTelephoneNumbers, AnonymizationAction.DELETE),
    Rule(Tag.OtherPatientIDs, AnonymizationAction.DELETE),
    Rule(Tag.PatientAge, AnonymizationAction.EMPTY),
    Rule(Tag.PatientWeight, AnonymizationAction.DELETE),
    Rule(Tag.PatientSize, AnonymizationAction.DELETE),
    Rule(Tag.PatientComments, AnonymizationAction.DELETE),
    Rule(Tag.EthnicGroup, AnonymizationAction.DELETE),
    Rule(Tag.PregnancyStatus, AnonymizationAction.DELETE),
    Rule(Tag.SmokingStatus, AnonymizationAction.DELETE),
    Rule(Tag.MedicalAlerts, AnonymizationAction.DELETE),
    Rule(Tag.Allergies, AnonymizationAction.DELETE),
    Rule(Tag.AdmittingDiagnosesDescription, AnonymizationAction.DELETE),
    # Dates and times
    Rule(Tag.AccessionNumber, AnonymizationAction.EMPTY),
    Rule(Tag.StudyDate, AnonymizationAction.EMPTY),
    Rule(Tag.SeriesDate, AnonymizationAction.EMPTY),
    Rule(Tag.AcquisitionDate, AnonymizationAction.EMPTY),
    Rule(Tag.ContentDate, AnonymizationAction.EMPTY),
    Rule(Tag.AcquisitionDateTime, AnonymizationAction.EMPTY),
    Rule(Tag.StudyTime, AnonymizationAction.EMPTY),
    Rule(Tag.SeriesTime, AnonymizationAction.EMPTY),
    Rule(Tag.AcquisitionTime, AnonymizationAction.EMPTY),
    Rule(Tag.ContentTime, AnonymizationAction.EMPTY),
    # Institution / personnel
    Rule(Tag.InstitutionName, AnonymizationAction.EMPTY),
    Rule(Tag.InstitutionAddress, AnonymizationAction.DELETE),
    Rule(Tag.InstitutionalDepartmentName, AnonymizationAction.DELETE),
    Rule(Tag.ReferringPhysicianName, AnonymizationAction.EMPTY),
    Rule(Tag.PerformingPhysicianName, AnonymizationAction.EMPTY),
    Rule(Tag.OperatorsName, AnonymizationAction.EMPTY),
    Rule(Tag.AttendingPhysicianName, AnonymizationAction.EMPTY),
    Rule(Tag.RequestingPhysician, AnonymizationAction.DELETE),
    Rule(Tag.RequestedProcedureDescription, AnonymizationAction.EMPTY),
    # Equipment identification
    Rule(Tag.StationName, AnonymizationAction.EMPTY),
    Rule(Tag.DeviceSerialNumber, AnonymizationAction.DELETE),
    Rule(Tag.StudyID, AnonymizationAction.EMPTY),
    # De-identification markers (always set)
    Rule(Tag.LongitudinalTemporalInformationModified, AnonymizationAction.REPLACE, "REMOVED"),
    Rule(Tag.PatientIdentityRemoved, AnonymizationAction.REPLACE, "YES"),
    Rule(
        Tag.DeidentificationMethod,
        AnonymizationAction.REPLACE,
        "DICOMForge Basic Application Confidentiality Profile subset",
    ),
)

_ALWAYS_SET_TAGS = frozenset(
    {
        Tag.LongitudinalTemporalInformationModified,
        Tag.PatientIdentityRemoved,
        Tag.DeidentificationMethod,
    }
)

_UID_ROOT_PATTERN = re.compile(r"^[0-9]+(?:\.[0-9]+)*$")


class AnonymizationPlan:
    """A deterministic de-identification plan that can be audited before use.

    The built-in profile is a practical subset for common non-pixel identifiers,
    not a complete DICOM PS3.15 Basic Application Confidentiality Profile.
    """

    def __init__(
        self,
        rules: Iterable[Rule],
        *,
        uid_remapper: Optional[UidRemapper] = None,
        private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE,
    ) -> None:
        self._rules = list(rules)
        self._uid_remapper = uid_remapper or UidRemapper()
        self._private_tag_action = private_tag_action

    @classmethod
    def starter_profile(
        cls,
        replacements: Optional[Mapping[TagInput, object]] = None,
        *,
        uid_root: str = "2.25",
        uid_salt: str = "dicomforge",
        private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE,
    ) -> "AnonymizationPlan":
        replacement_map: Dict[Tag, object] = {
            Tag.parse(tag): value for tag, value in (replacements or {}).items()
        }
        rules = [
            Rule(rule.tag, rule.action, replacement_map.get(rule.tag, rule.replacement))
            for rule in _BASIC_PROFILE_RULES
        ]
        rules.extend(Rule(tag, AnonymizationAction.REMAP_UID) for tag in _UID_TAGS)
        return cls(
            rules,
            uid_remapper=UidRemapper(root=uid_root, salt=uid_salt),
            private_tag_action=private_tag_action,
        )

    @classmethod
    def basic_profile(
        cls,
        replacements: Optional[Mapping[TagInput, object]] = None,
        *,
        uid_root: str = "2.25",
        uid_salt: str = "dicomforge",
        private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE,
    ) -> "AnonymizationPlan":
        """Compatibility alias for :meth:`starter_profile`."""

        return cls.starter_profile(
            replacements=replacements,
            uid_root=uid_root,
            uid_salt=uid_salt,
            private_tag_action=private_tag_action,
        )

    def apply(
        self,
        dataset: DicomDataset,
        *,
        remove_private_tags: Optional[bool] = None,
        recursive: bool = True,
    ) -> DicomDataset:
        self.apply_with_report(
            dataset,
            remove_private_tags=remove_private_tags,
            recursive=recursive,
        )
        return dataset

    def apply_with_report(
        self,
        dataset: DicomDataset,
        *,
        remove_private_tags: Optional[bool] = None,
        recursive: bool = True,
    ) -> AnonymizationReport:
        events: List[AnonymizationEvent] = []
        self._apply_to_dataset(dataset, events, path=(), recursive=recursive)
        should_remove_private = (
            remove_private_tags
            if remove_private_tags is not None
            else self._private_tag_action == PrivateTagAction.REMOVE
        )
        private_tags_removed = (
            dataset.remove_private_tags(recursive=recursive) if should_remove_private else 0
        )
        return AnonymizationReport(
            events=tuple(events),
            private_tags_removed=private_tags_removed,
            private_tag_action=(
                PrivateTagAction.REMOVE if should_remove_private else PrivateTagAction.KEEP
            ),
        )

    def _apply_to_dataset(
        self,
        dataset: DicomDataset,
        events: List[AnonymizationEvent],
        *,
        path: Tuple[Tag, ...],
        recursive: bool,
    ) -> None:
        for rule in self._rules:
            before_present = rule.tag in dataset
            previous_value = dataset.get(rule.tag)
            if rule.action == AnonymizationAction.DELETE:
                if before_present:
                    dataset.pop(rule.tag, None)
            elif rule.action == AnonymizationAction.EMPTY:
                if before_present:
                    dataset.set(rule.tag, "")
            elif rule.action == AnonymizationAction.REPLACE:
                if before_present or rule.tag in _ALWAYS_SET_TAGS:
                    dataset.set(rule.tag, rule.replacement)
            elif rule.action == AnonymizationAction.REMAP_UID:
                if before_present:
                    dataset.set(rule.tag, self._remap_value(dataset[rule.tag]))
            events.append(
                AnonymizationEvent(
                    tag=rule.tag,
                    action=rule.action,
                    before_present=before_present,
                    after_present=rule.tag in dataset,
                    replacement=self._audit_replacement(rule, dataset),
                    path=path,
                    previous_value=previous_value,
                    new_value=dataset.get(rule.tag),
                )
            )
        if recursive:
            for tag, value in list(dataset.items()):
                for child in _iter_sequence_items(value):
                    self._apply_to_dataset(child, events, path=path + (tag,), recursive=True)

    def audit(self) -> list[dict[str, object]]:
        return [
            {"tag": str(rule.tag), "action": rule.action.value, "replacement": rule.replacement}
            for rule in self._rules
        ]

    def _remap_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._uid_remapper.remap(value)
        if isinstance(value, tuple):
            return tuple(self._uid_remapper.remap(item) for item in value)
        if isinstance(value, list):
            return [self._uid_remapper.remap(item) for item in value]
        return self._uid_remapper.remap(value)

    def _audit_replacement(self, rule: Rule, dataset: DicomDataset) -> object:
        if rule.action == AnonymizationAction.REMAP_UID:
            return dataset.get(rule.tag, "")
        return rule.replacement


def _iter_sequence_items(value: object) -> Iterable[DicomDataset]:
    if isinstance(value, DicomDataset):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, DicomDataset):
                yield item
