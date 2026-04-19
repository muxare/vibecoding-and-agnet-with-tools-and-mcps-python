from dataclasses import dataclass
from pathlib import Path

PROMPTS_ROOT = Path(__file__).resolve().parents[3] / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    model: str | None
    description: str | None
    body: str

    def render(self, **values: str) -> str:
        rendered = self.body
        for key, value in values.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", value)
        return rendered


def _parse_frontmatter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        return {}, raw.strip()
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}, raw.strip()
    _, header, body = parts
    meta: dict[str, str] = {}
    for line in header.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, body.strip()


def load_prompt(name: str, version: str, *, root: Path | None = None) -> Prompt:
    """Load a prompt file `<root>/<name>/<name>.<version>.md`.

    Files may begin with a YAML-ish frontmatter block delimited by `---`.
    Recognised keys: `name`, `version`, `model`, `description`. Unknown keys
    are ignored. Files without frontmatter are accepted; metadata defaults
    to the values inferred from the filename.
    """
    base = root or PROMPTS_ROOT
    path = base / name / f"{name}.{version}.md"
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    return Prompt(
        name=meta.get("name", name),
        version=meta.get("version", version),
        model=meta.get("model"),
        description=meta.get("description"),
        body=body,
    )
