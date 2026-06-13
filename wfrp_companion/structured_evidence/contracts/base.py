from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any


@dataclass(frozen=True)
class ContractIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ContractValidationResult:
    ok: bool
    payload: dict[str, Any]
    issues: tuple[ContractIssue, ...] = ()

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues)


def normalize_identity(text: str) -> str:
    without_apostrophes = text.lower().replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", " ", without_apostrophes).strip()
    return re.sub(r"\s+", " ", normalized)


def reject_label_identity(identity: str) -> bool:
    normalized = normalize_identity(identity)
    if normalized in _LABEL_IDENTITIES:
        return True
    if normalized.startswith(("race ", "career ")):
        return True
    return normalized in {_MAIN_PROFILE_HEADER, _SECONDARY_PROFILE_HEADER, "ay int fel"}


def cloned_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(payload))


def issue(code: str, message: str) -> ContractIssue:
    return ContractIssue(code=code, message=message)


def result(payload: dict[str, Any], issues: list[ContractIssue]) -> ContractValidationResult:
    return ContractValidationResult(ok=not issues, payload=payload, issues=tuple(issues))


def required_mapping(
    payload: Mapping[str, Any],
    field_name: str,
    issues: list[ContractIssue],
) -> dict[str, Any]:
    value = payload.get(field_name)
    if isinstance(value, Mapping):
        return dict(value)
    issues.append(issue(f"{field_name}_missing", f"{field_name} must be an object"))
    return {}


def required_identity_name(
    payload: dict[str, Any],
    issues: list[ContractIssue],
    *,
    field_name: str = "name_raw",
) -> str:
    identity = required_mapping(payload, "identity", issues)
    raw_name = identity.get(field_name)
    if not isinstance(raw_name, str) or not raw_name.strip():
        issues.append(issue("identity_missing", "identity name is required"))
        return ""
    normalized = normalize_identity(raw_name)
    identity[f"{field_name.removesuffix('_raw')}_normalized"] = normalized
    payload["identity"] = identity
    if reject_label_identity(raw_name):
        issues.append(issue("identity_is_label", "identity is a label, not an entity name"))
    return normalized


def require_source(payload: Mapping[str, Any], issues: list[ContractIssue]) -> None:
    source = required_mapping(payload, "source", issues)
    for field_name in ("book_id", "text_snapshot_sha256"):
        value = source.get(field_name)
        if not isinstance(value, str) or not value.strip():
            issues.append(
                issue(
                    f"source_{field_name}_missing",
                    f"source.{field_name} is required",
                )
            )


def has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def has_nonempty_list(value: object) -> bool:
    return isinstance(value, list) and bool(value)


_LABEL_IDENTITIES = {
    normalize_identity(value)
    for value in (
        "Main Profile",
        "Secondary Profile",
        "Skills",
        "Talents",
        "Armour",
        "Armour Points",
        "Career",
        "Weapons",
        "Race",
        "Trappings",
    )
}
_MAIN_PROFILE_HEADER = normalize_identity("WS BS S T Ag Int WP Fel")
_SECONDARY_PROFILE_HEADER = normalize_identity("A W SB TB M Mag IP FP")
