from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

from wfrp_companion.assistant import prompts


@dataclass(frozen=True)
class PromptSurface:
    role: str
    char_count: int
    sha256: str
    first_line: str

    def to_json(self) -> dict[str, object]:
        return {
            "role": self.role,
            "char_count": self.char_count,
            "sha256": self.sha256,
            "first_line": self.first_line,
        }


def prompt_surface_summary(
    messages: Sequence[prompts.PromptMessage],
) -> tuple[PromptSurface, ...]:
    return tuple(
        PromptSurface(
            role=message.role,
            char_count=len(message.content),
            sha256=hashlib.sha256(message.content.encode("utf-8")).hexdigest(),
            first_line=redacted_first_line(message.content),
        )
        for message in messages
    )


def redacted_first_line(content: str, *, max_chars: int = 80) -> str:
    first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
    scrubbed = prompts.scrub_private_paths(first_line)
    return scrubbed[:max_chars].rstrip()
