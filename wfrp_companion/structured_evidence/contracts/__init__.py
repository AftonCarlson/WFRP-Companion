from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from wfrp_companion.structured_evidence.contracts.base import (
    ContractValidationResult,
)
from wfrp_companion.structured_evidence.contracts.career_entry import (
    validate_career_entry_payload,
)
from wfrp_companion.structured_evidence.contracts.profile_card import (
    validate_profile_card_payload,
)
from wfrp_companion.structured_evidence.contracts.rules_entry import (
    validate_rules_entry_payload,
)
from wfrp_companion.structured_evidence.contracts.structured_table import (
    validate_structured_table_payload,
)

ContractValidator = Callable[[Mapping[str, Any]], ContractValidationResult]

_CONTRACT_VALIDATORS: dict[str, ContractValidator] = {
    "career_entry": validate_career_entry_payload,
    "profile_card": validate_profile_card_payload,
    "rules_entry": validate_rules_entry_payload,
    "structured_table": validate_structured_table_payload,
}


def validator_for_shape(object_shape: str) -> ContractValidator:
    try:
        return _CONTRACT_VALIDATORS[object_shape]
    except KeyError:
        raise ValueError(
            f"Unsupported structured evidence shape: {object_shape}"
        ) from None


def validate_contract_payload(payload: Mapping[str, Any]) -> ContractValidationResult:
    return validator_for_shape(str(payload.get("object_shape", "")))(payload)


__all__ = [
    "ContractValidator",
    "validate_contract_payload",
    "validator_for_shape",
]
