from __future__ import annotations

from wfrp_companion.assistant import evidence_policy


def test_identity_satisfies_essential_terms_with_spelling_aliases() -> None:
    assert evidence_policy.identity_satisfies_essential_terms(
        "Armour Points by Location",
        ("armor", "location"),
    )


def test_identity_requires_all_essential_terms() -> None:
    assert not evidence_policy.identity_satisfies_essential_terms(
        "The Black Knight",
        ("black", "orc"),
    )


def test_essential_subject_terms_drop_provider_structural_filler() -> None:
    assert evidence_policy.essential_subject_terms(
        "hit location determination in combat",
    ) == ("hit", "location")


def test_essential_subject_terms_drop_empty_stat_and_duplicate_terms() -> None:
    assert evidence_policy.essential_subject_terms(None) == ()
    assert evidence_policy.essential_subject_terms("orc WS profile orc") == ("orc",)
    assert evidence_policy.essential_subject_terms("harpy rule table") == ("harpy",)
    assert evidence_policy.essential_subject_terms("harpy entries") == ("harpy",)
