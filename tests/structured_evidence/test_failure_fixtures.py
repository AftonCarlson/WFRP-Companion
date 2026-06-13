from __future__ import annotations

from pathlib import Path


def test_structured_evidence_fixture_readme_defines_private_safe_rules() -> None:
    readme = Path("tests/fixtures/structured_evidence/README.md")

    text = readme.read_text(encoding="utf-8")

    assert "synthetic" in text.lower()
    assert "do not copy" in text.lower()
    assert "wfrp" in text.lower()
    assert "private" in text.lower()
