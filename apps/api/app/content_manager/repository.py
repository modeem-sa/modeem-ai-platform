"""Durable, packaged prompt assets for the content-manager agent."""

from pathlib import Path


class PromptRepository:
    """Load prompt material packaged with the API, never from a client request."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = root or Path(__file__).with_name("prompts")

    def system_prompt(self) -> str:
        return "\n\n".join(
            self._read(name)
            for name in (
                "identity.md",
                "rules.md",
                "shared-rules.md",
                "templates.md",
                "instructions.md",
            )
        )

    def scope(self) -> tuple[tuple[str, ...], str]:
        lines = self._read("scope.md").splitlines()
        redirect = next(
            (
                line.split(":", 1)[1].strip().strip('"')
                for line in lines
                if line.startswith("redirect_message:")
            ),
            "هذا المساعد مخصص لإعداد وتحرير مستندات العمل.",
        )
        signals: list[str] = []
        collecting = False
        for line in lines:
            if line.startswith("out_of_scope_signals:"):
                collecting = True
                continue
            if collecting and line.startswith("supported_signals:"):
                break
            if collecting and line.lstrip().startswith("- "):
                signals.append(line.split("- ", 1)[1].strip())
        return tuple(signals), redirect

    def _read(self, name: str) -> str:
        return (self._root / name).read_text(encoding="utf-8").strip()
