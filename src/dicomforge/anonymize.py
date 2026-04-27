"""De-identification planning primitives."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, Mapping, Optional

from dicomforge.dataset import DicomDataset
from dicomforge.tags import Tag, TagInput


class AnonymizationAction(str, Enum):
    DELETE = "delete"
    EMPTY = "empty"
    REPLACE = "replace"


@dataclass(frozen=True)
class Rule:
    tag: Tag
    action: AnonymizationAction
    replacement: object = ""


class AnonymizationPlan:
    """A deterministic plan that can be audited before mutating a dataset."""

    def __init__(self, rules: Iterable[Rule]) -> None:
        self._rules = list(rules)

    @classmethod
    def basic_profile(
        cls,
        replacements: Optional[Mapping[TagInput, object]] = None,
    ) -> "AnonymizationPlan":
        replacement_map: Dict[Tag, object] = {
            Tag.parse(tag): value for tag, value in (replacements or {}).items()
        }
        default_rules = [
            Rule(Tag.PatientName, AnonymizationAction.REPLACE, "Anonymous"),
            Rule(Tag.PatientID, AnonymizationAction.REPLACE, "ANON"),
            Rule(Tag.PatientBirthDate, AnonymizationAction.EMPTY),
            Rule(Tag.PatientSex, AnonymizationAction.EMPTY),
        ]
        rules = [
            Rule(rule.tag, rule.action, replacement_map.get(rule.tag, rule.replacement))
            for rule in default_rules
        ]
        return cls(rules)

    def apply(self, dataset: DicomDataset, *, remove_private_tags: bool = True) -> DicomDataset:
        for rule in self._rules:
            if rule.action == AnonymizationAction.DELETE:
                dataset.pop(rule.tag, None)
            elif rule.action == AnonymizationAction.EMPTY:
                dataset.set(rule.tag, "")
            elif rule.action == AnonymizationAction.REPLACE:
                dataset.set(rule.tag, rule.replacement)
        if remove_private_tags:
            dataset.remove_private_tags()
        return dataset

    def audit(self) -> list[dict[str, object]]:
        return [
            {"tag": str(rule.tag), "action": rule.action.value, "replacement": rule.replacement}
            for rule in self._rules
        ]
