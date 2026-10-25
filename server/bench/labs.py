"""Lab loader: labs/<lab_id>/lab.yaml + manual.md + schematic.svg (CONTRACTS §6)."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


@dataclass
class Lab:
    id: str
    dir: Path
    data: dict[str, Any]
    manual_md: str

    @property
    def schematic_url(self) -> str | None:
        return f"/labs/{self.id}/schematic.svg" if (self.dir / "schematic.svg").exists() else None

    def wire(self) -> dict[str, Any]:
        """The `lab` payload: lab.yaml as JSON plus manual_md and schematic_url."""
        return {**self.data, "manual_md": self.manual_md, "schematic_url": self.schematic_url}

    def net(self, net_id: str) -> dict[str, Any] | None:
        return next((n for n in self.data.get("nets", []) if n.get("id") == net_id), None)


def load_lab(lab_dir: Path) -> Lab:
    data = yaml.safe_load((lab_dir / "lab.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("lab.yaml is not a mapping")
    manual = lab_dir / "manual.md"
    return Lab(
        id=str(data.get("id") or lab_dir.name),
        dir=lab_dir,
        data=data,
        manual_md=manual.read_text(encoding="utf-8") if manual.exists() else "",
    )


def load_labs(*roots: Path) -> dict[str, Lab]:
    """Load every lab under the given roots. Earlier roots win on duplicate ids. Broken labs are skipped."""
    labs: dict[str, Lab] = {}
    for root in roots:
        for yml in sorted(root.glob("*/lab.yaml")):
            try:
                lab = load_lab(yml.parent)
            except Exception as e:  # a broken lab file must not take the server down
                log.warning("skipping %s: %s", yml, e)
                continue
            labs.setdefault(lab.id, lab)
    return labs
