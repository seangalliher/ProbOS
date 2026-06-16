"""AD-1013: skills-only Capability-Pack loader (#948).

The lowest-risk loader tier. It loads a pack's declared **folder-skills** (a
subdirectory containing a ``SKILL.md``) into the cognitive skill catalog. A
``SKILL.md`` is markdown *instructions* consumed by the LLM at reasoning time —
**not executable code** — so this tier loads nothing that runs. Agent code
(``.py``) and hooks / MCP servers are deliberately OUT of scope (they execute,
and belong to the AD-1014 self-mod-chain loader slice).

**Reuse over reinvention.** Each folder-skill is loaded through the existing
AD-596d :meth:`CognitiveSkillCatalog.import_skill` path, which validates the
``SKILL.md``, dedup-guards by skill name, copies the skill into the catalog's
skills directory, and registers it. This module is only the orchestration that
walks a pack's declared skills and calls that path once per skill, recording a
per-skill outcome. Honest-degrade: a duplicate or invalid skill is recorded as
*skipped* with a reason — a load run always completes and never raises.

**Consent + gating live in the CALLER**, not here. A caller must check
``config.packs.enabled`` (default OFF) and obtain operator consent — the Ship's
Locker preview (AD-1003e/f) is the review surface — before invoking the loader.
The loader is pure mechanism so it is testable in isolation and adds no live
behavior on its own (mechanism-first, mirroring the AD-1004 hook-bus precedent).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from probos.packs.scanner import preview_pack

if TYPE_CHECKING:
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PackLoadResult:
    """Outcome of loading one pack's skills.

    ``loaded`` holds the skill names successfully registered; ``skipped`` holds
    ``(component_name, reason)`` for components that were not loaded (a
    duplicate, an invalid ``SKILL.md``, or a shape out of scope for the
    skills-only tier). A load run always produces this summary — honest-degrade
    means it never raises.
    """

    pack_name: str
    loaded: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def loaded_count(self) -> int:
        return len(self.loaded)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


async def load_pack_skills(
    pack_dir: str | Path,
    catalog: CognitiveSkillCatalog,
    *,
    origin_prefix: str = "pack",
) -> PackLoadResult | None:
    """Load a pack's declared folder-skills into ``catalog``.

    Returns ``None`` when ``pack_dir`` has no valid manifest (nothing to load).
    Otherwise loads each declared folder-skill (a subdirectory with a
    ``SKILL.md``) via
    ``catalog.import_skill(skill_dir, origin="<origin_prefix>:<pack>")`` and
    returns a :class:`PackLoadResult`. A standalone ``.md`` skill (no
    ``SKILL.md`` folder) is skipped with a reason — the structured folder-skill
    is the only shape the AgentSkills.io importer accepts. The ``origin`` tag
    records pack provenance so a pack's skills can be identified (and later
    removed) as a unit. Never raises.
    """
    base = Path(pack_dir)
    contents = preview_pack(base)
    if contents is None:
        return None

    loaded: list[str] = []
    skipped: list[tuple[str, str]] = []
    origin = f"{origin_prefix}:{contents.name}"

    for comp in contents.skills:
        skill_path = base / comp.rel
        if not (skill_path.is_dir() and (skill_path / "SKILL.md").is_file()):
            skipped.append(
                (comp.name, "standalone-md skill not supported (needs a SKILL.md folder)")
            )
            continue
        try:
            entry = await catalog.import_skill(skill_path, origin=origin)
            loaded.append(entry.name)
        except ValueError as exc:
            # Duplicate name or invalid SKILL.md — the expected honest-degrade.
            skipped.append((comp.name, str(exc)))
        except Exception:  # noqa: BLE001 — never let one bad skill brick a load
            logger.warning(
                "AD-1013: unexpected error loading skill %r from pack %s; skipped",
                comp.name, contents.name, exc_info=True,
            )
            skipped.append((comp.name, "unexpected load error"))

    logger.info(
        "AD-1013: pack '%s' skills loaded=%d skipped=%d",
        contents.name, len(loaded), len(skipped),
    )
    return PackLoadResult(pack_name=contents.name, loaded=loaded, skipped=skipped)
