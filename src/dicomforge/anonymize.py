"""De-identification planning primitives."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from dicomforge.dataset import DicomDataset
from dicomforge.tags import Tag, TagInput


class AnonymizationAction(str, Enum):
    DELETE = "delete"
    EMPTY = "empty"
    REPLACE = "replace"
    REMAP_UID = "remap_uid"


@dataclass(frozen=True)
class Rule:
    tag: Tag
    action: AnonymizationAction
    replacement: object = ""


@dataclass(frozen=True)
class AnonymizationEvent:
    """One applied de-identification action."""

    tag: Tag
    action: AnonymizationAction
    path: Tuple[Tag, ...] = ()
    previous_value: object = None
    new_value: object = None

    def to_dict(self) -> dict[str, object]:
        return {
            "tag": str(self.tag),
            "action": self.action.value,
            "path": [str(tag) for tag in self.path],
            "previous_value": self.previous_value,
            "new_value": self.new_value,
        }


@dataclass(frozen=True)
class AnonymizationReport:
    """Audit report returned after applying a de-identification plan."""

    events: Tuple[AnonymizationEvent, ...]
    private_tags_removed: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "events": [event.to_dict() for event in self.events],
            "private_tags_removed": self.private_tags_removed,
        }


class UidRemapper:
    """Deterministically map DICOM UIDs into an organizational root."""

    def __init__(self, root: str = "2.25", *, salt: str = "dicomforge") -> None:
        normalized = root.strip().rstrip(".")
        if not normalized or len(normalized) > 54:
            raise ValueError("UID root must be non-empty and at most 54 characters.")
        self.root = normalized
        self.salt = salt
        self._cache: Dict[str, str] = {}

    def remap(self, uid: object) -> str:
        source = str(uid).strip()
        if not source:
            return ""
        existing = self._cache.get(source)
        if existing is not None:
            return existing
        digest = hashlib.sha256(f"{self.salt}:{source}".encode("utf-8")).digest()
        numeric = str(int.from_bytes(digest[:15], "big"))
        max_suffix = 64 - len(self.root) - 1
        remapped = f"{self.root}.{numeric[:max_suffix]}"
        self._cache[source] = remapped
        return remapped


class AnonymizationPlan:
    """A deterministic de-identification plan that can be audited before use.

    The built-in profile is intentionally small. It is a starter policy for
    common direct identifiers, not a complete DICOM PS3.15 Basic Application
    Confidentiality Profile implementation.
    """

    def __init__(
        self,
        rules: Iterable[Rule],
        *,
        uid_remapper: Optional[UidRemapper] = None,
    ) -> None:
        self._rules = list(rules)
        self.uid_remapper = uid_remapper or UidRemapper()

    @classmethod
    def starter_profile(
        cls,
        replacements: Optional[Mapping[TagInput, object]] = None,
        uid_root: str = "2.25",
        uid_salt: str = "dicomforge",
    ) -> "AnonymizationPlan":
        replacement_map: Dict[Tag, object] = {
            Tag.parse(tag): value for tag, value in (replacements or {}).items()
        }
        default_rules = [
            Rule(Tag.PatientName, AnonymizationAction.REPLACE, "Anonymous"),
            Rule(Tag.PatientID, AnonymizationAction.REPLACE, "ANON"),
            Rule(Tag.AccessionNumber, AnonymizationAction.EMPTY),
            Rule(Tag.PatientBirthDate, AnonymizationAction.EMPTY),
            Rule(Tag.PatientSex, AnonymizationAction.EMPTY),
            Rule(Tag.PatientAddress, AnonymizationAction.DELETE),
            Rule(Tag.ReferringPhysicianName, AnonymizationAction.EMPTY),
            Rule(Tag.InstitutionName, AnonymizationAction.EMPTY),
            Rule(Tag.StudyDate, AnonymizationAction.EMPTY),
            Rule(Tag.SeriesDate, AnonymizationAction.EMPTY),
            Rule(Tag.AcquisitionDate, AnonymizationAction.EMPTY),
            Rule(Tag.ContentDate, AnonymizationAction.EMPTY),
            Rule(Tag.StudyInstanceUID, AnonymizationAction.REMAP_UID),
            Rule(Tag.SeriesInstanceUID, AnonymizationAction.REMAP_UID),
            Rule(Tag.SOPInstanceUID, AnonymizationAction.REMAP_UID),
        ]
        rules = [
            Rule(rule.tag, rule.action, replacement_map.get(rule.tag, rule.replacement))
            for rule in default_rules
        ]
        return cls(rules, uid_remapper=UidRemapper(uid_root, salt=uid_salt))

    @classmethod
    def basic_profile(
        cls,
        replacements: Optional[Mapping[TagInput, object]] = None,
        uid_root: str = "2.25",
        uid_salt: str = "dicomforge",
    ) -> "AnonymizationPlan":
        """Compatibility alias for :meth:`starter_profile`.

        The name is retained for older callers, but the profile is not a full
        DICOM PS3.15 Basic Application Confidentiality Profile implementation.
        """

        return cls.starter_profile(
            replacements=replacements,
            uid_root=uid_root,
            uid_salt=uid_salt,
        )

    def apply(
        self,
        dataset: DicomDataset,
        *,
        remove_private_tags: bool = True,
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
        remove_private_tags: bool = True,
        recursive: bool = True,
    ) -> AnonymizationReport:
        events: List[AnonymizationEvent] = []
        self._apply_to_dataset(dataset, events, path=(), recursive=recursive)
        private_tags_removed = 0
        if remove_private_tags:
            private_tags_removed = dataset.remove_private_tags(recursive=recursive)
        return AnonymizationReport(tuple(events), private_tags_removed)

    def _apply_to_dataset(
        self,
        dataset: DicomDataset,
        events: List[AnonymizationEvent],
        *,
        path: Tuple[Tag, ...],
        recursive: bool,
    ) -> None:
        for rule in self._rules:
            previous = dataset.get(rule.tag)
            if rule.action == AnonymizationAction.DELETE:
                if rule.tag not in dataset:
                    continue
                dataset.pop(rule.tag, None)
                new_value: Any = None
            elif rule.action == AnonymizationAction.EMPTY:
                dataset.set(rule.tag, "")
                new_value = ""
            elif rule.action == AnonymizationAction.REPLACE:
                dataset.set(rule.tag, rule.replacement)
                new_value = rule.replacement
            elif rule.action == AnonymizationAction.REMAP_UID:
                if previous is None:
                    continue
                new_value = self.uid_remapper.remap(previous)
                dataset.set(rule.tag, new_value)
            else:
                continue
            events.append(
                AnonymizationEvent(
                    tag=rule.tag,
                    action=rule.action,
                    path=path,
                    previous_value=previous,
                    new_value=new_value,
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


def _iter_sequence_items(value: object) -> Iterable[DicomDataset]:
    if isinstance(value, DicomDataset):
        yield value
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, DicomDataset):
                yield item
