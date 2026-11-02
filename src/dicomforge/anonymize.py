"""De-identification planning primitives."""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import timedelta as _timedelta
from enum import Enum
from hashlib import sha256
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from dicomforge.dataset import DicomDataset
from dicomforge.tags import Tag, TagInput
from dicomforge.uids import is_valid_uid


class AnonymizationAction(str, Enum):
    DELETE = "delete"
    EMPTY = "empty"
    REPLACE = "replace"
    REMAP_UID = "remap_uid"
    UID_REMAP = "remap_uid"
    SHIFT_DATE = "shift_date"


class PrivateTagAction(str, Enum):
    REMOVE = "remove"
    KEEP = "keep"


@dataclass(frozen=True)
class Rule:
    tag: Tag
    action: AnonymizationAction
    replacement: object = field(default="", repr=False)


@dataclass(frozen=True)
class AnonymizationEvent:
    """One de-identification action that was applied or skipped."""

    tag: Tag
    action: AnonymizationAction
    before_present: bool
    after_present: bool
    replacement: object = field(default=None, repr=False)
    path: Tuple[Tag, ...] = ()
    previous_value: object = field(default=None, repr=False)
    new_value: object = field(default=None, repr=False)
    item_path: Tuple[object, ...] = ()

    def to_dict(self, *, include_values: bool = False) -> dict[str, object]:
        result: dict[str, object] = {
            "tag": str(self.tag),
            "action": self.action.value,
            "before_present": self.before_present,
            "after_present": self.after_present,
            "path": [str(tag) for tag in self.path],
            "item_path": [str(item) if isinstance(item, Tag) else item for item in self.item_path],
        }
        if include_values:
            result.update(replacement=self.replacement, previous_value=self.previous_value,
                          new_value=self.new_value)
        return result


@dataclass(frozen=True)
class AnonymizationReport:
    """Summary of a de-identification run."""

    events: Sequence[AnonymizationEvent]
    private_tags_removed: int
    private_tag_action: PrivateTagAction = PrivateTagAction.REMOVE

    def to_dict(self, *, include_values: bool = False) -> dict[str, object]:
        return {
            "events": [event.to_dict(include_values=include_values) for event in self.events],
            "private_tags_removed": self.private_tags_removed,
            "private_tag_action": self.private_tag_action.value,
        }


AuditEvent = AnonymizationEvent
AuditReport = AnonymizationReport


class UidRemapper:
    """Deterministically replace UIDs while preserving equality relationships."""

    def __init__(
        self, root: str = "2.25", *, salt: str = "dicomforge",
        key: Optional[bytes] = None, namespace: str = "",
    ) -> None:
        normalized_root = root.strip().rstrip(".")
        if not is_valid_uid(normalized_root) or len(normalized_root) > 24:
            raise ValueError(
                "UID root must contain numeric components separated by dots and leave room "
                "for a full 128-bit suffix (root length at most 24)."
            )
        self.root = normalized_root
        self.salt = salt
        self._key = key if key is not None else salt.encode("utf-8")
        if not self._key:
            raise ValueError("UID mapping key cannot be empty")
        self._namespace = namespace.encode("utf-8")
        self.strategy = "hmac-sha256-v1"

    def remap(self, uid: object) -> str:
        original = str(uid).strip()
        if not original:
            return ""
        digest = hmac.new(self._key, b"dicomforge-uid-v1\0" + self._namespace + b"\0"
                          + original.encode("utf-8"), sha256).digest()
        return f"{self.root}.{int.from_bytes(digest[:16], 'big')}"


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
        # Deduplicate by tag: when the same tag appears in multiple rules the
        # LAST rule wins.  Rules are applied in the order of their first
        # appearance, so callers can override built-in profile rules simply by
        # appending their custom rules after the profile rules.
        #
        # Without deduplication the result depends on action combination and
        # insertion order in a non-obvious way — for example EMPTY followed by
        # REPLACE gives "Anonymous", but REPLACE followed by EMPTY gives "".
        seen: Dict[Tag, Rule] = {}
        for rule in rules:
            seen[rule.tag] = rule  # later entry overwrites earlier for same tag
        self._rules = list(seen.values())
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
            Rule(rule.tag, AnonymizationAction.REPLACE if rule.tag in replacement_map
                 else rule.action, replacement_map.get(rule.tag, rule.replacement))
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
        capture_values: bool = False,
    ) -> AnonymizationReport:
        events: List[AnonymizationEvent] = []
        self._apply_to_dataset(dataset, events, path=(), recursive=recursive,
                               capture_values=capture_values, item_path=())
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
        capture_values: bool = False,
        item_path: Tuple[object, ...] = (),
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
                if before_present or (not path and rule.tag in _ALWAYS_SET_TAGS):
                    dataset.set(rule.tag, rule.replacement)
            elif rule.action == AnonymizationAction.REMAP_UID:
                if before_present:
                    dataset.set(rule.tag, self._remap_value(dataset[rule.tag]))
            elif rule.action == AnonymizationAction.SHIFT_DATE:
                if before_present:
                    offset = rule.replacement
                    if not isinstance(offset, int):
                        raise ValueError(
                            f"SHIFT_DATE rule for {rule.tag} requires an integer day offset "
                            f"in rule.replacement, got {type(offset).__name__!r}."
                        )
                    dataset.set(rule.tag, _shift_date_value(dataset[rule.tag], offset))
            events.append(
                AnonymizationEvent(
                    tag=rule.tag,
                    action=rule.action,
                    before_present=before_present,
                    after_present=rule.tag in dataset,
                    replacement=self._audit_replacement(rule, dataset) if capture_values else None,
                    path=path,
                    previous_value=previous_value if capture_values else None,
                    new_value=dataset.get(rule.tag) if capture_values else None,
                    item_path=item_path + (rule.tag,),
                )
            )
        if recursive:
            for tag, value in list(dataset.items()):
                for index, child in enumerate(_iter_sequence_items(value)):
                    self._apply_to_dataset(child, events, path=path + (tag,), recursive=True,
                                           capture_values=capture_values,
                                           item_path=item_path + (tag, index))

    def audit(self, *, include_values: bool = False) -> list[dict[str, object]]:
        return [
            {"tag": str(rule.tag), "action": rule.action.value,
             **({"replacement": rule.replacement} if include_values else {})}
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
    elif isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, DicomDataset):
                yield item


def _shift_date_value(value: Any, offset_days: int) -> Any:
    """Shift a DICOM date or datetime value by *offset_days* calendar days.

    Handles two DICOM value representations:

    * **DA** (Date) — ``YYYYMMDD``, exactly 8 characters.
    * **DT** (DateTime) — starts with ``YYYYMMDD``; any trailing time
      component (``HHmmSS.FFFFFF±HHMM``) is preserved verbatim.

    If *value* is not a string, is empty, shorter than 8 characters, or
    does not begin with a valid calendar date, it is returned unchanged
    rather than raising — partial or missing dates should not crash a
    de-identification run.

    Parameters
    ----------
    value:
        Raw tag value from the dataset.
    offset_days:
        Number of days to add (positive = future, negative = past).
    """
    if not isinstance(value, str) or len(value) < 8:
        return value
    date_part = value[:8]
    rest = value[8:]  # preserved time component for DT values
    try:
        year = int(date_part[0:4])
        month = int(date_part[4:6])
        day = int(date_part[6:8])
        shifted = _date(year, month, day) + _timedelta(days=offset_days)
        return shifted.strftime("%Y%m%d") + rest
    except (ValueError, OverflowError):
        # Malformed date — return as-is rather than crashing the plan
        return value
