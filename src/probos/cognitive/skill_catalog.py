"""AD-596a: Cognitive Skill Catalog — discovers, indexes, and serves SKILL.md files.

Ship's Computer infrastructure service (no identity, no crew status).
Provides progressive disclosure: descriptions at startup, full instructions on-demand.

Adopts AgentSkills.io open standard for T2 cognitive skill files.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

# Rank ordering for rank-based filtering
_RANK_ORDER: dict[str, int] = {
    "ensign": 0,
    "lieutenant": 1,
    "commander": 2,
    "senior_officer": 3,
}

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS cognitive_skill_catalog (
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    skill_dir TEXT NOT NULL,
    license TEXT DEFAULT '',
    compatibility TEXT DEFAULT '',
    department TEXT DEFAULT '*',
    skill_id TEXT DEFAULT '',
    min_proficiency INTEGER DEFAULT 1,
    min_rank TEXT DEFAULT 'ensign',
    intents TEXT DEFAULT '[]',
    origin TEXT DEFAULT 'internal',
    loaded_at REAL NOT NULL
);
"""


@dataclass
class CognitiveSkillEntry:
    """Metadata for a discovered cognitive skill."""

    name: str
    description: str
    skill_dir: Path
    license: str = ""
    compatibility: str = ""
    # ProbOS governance (from metadata block, all optional)
    department: str = "*"
    skill_id: str = ""
    min_proficiency: int = 1
    min_rank: str = "ensign"
    intents: list[str] = field(default_factory=list)
    origin: str = "internal"
    loaded_at: float = 0.0
    activation: str = "discovery"  # AD-626: "discovery", "augmentation", or "both"
    triggers: list[str] = field(default_factory=list)  # AD-643a: action tags this skill enhances


@dataclass
class SkillValidationResult:
    """Result of validating a cognitive skill."""

    skill_name: str
    valid: bool  # True if zero errors (warnings are OK)
    errors: list[str]  # Must fix
    warnings: list[str]  # Should fix

    def to_dict(self) -> dict:
        return {
            "skill_name": self.skill_name,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def parse_skill_file(path: Path) -> CognitiveSkillEntry | None:
    """Parse a SKILL.md file and return a CognitiveSkillEntry, or None on error."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        logger.warning("AD-596a: Cannot read skill file: %s", path)
        return None

    # Extract YAML frontmatter between --- delimiters
    if not content.startswith("---"):
        logger.warning("AD-596a: No frontmatter delimiters in %s", path)
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        logger.warning("AD-596a: Incomplete frontmatter delimiters in %s", path)
        return None

    yaml_text = parts[1]
    try:
        fm = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        logger.warning("AD-596a: Invalid YAML in %s", path)
        return None

    if not isinstance(fm, dict):
        logger.warning("AD-596a: Frontmatter is not a mapping in %s", path)
        return None

    name = fm.get("name")
    if not name:
        logger.warning("AD-596a: Missing required 'name' field in %s", path)
        return None

    description = fm.get("description")
    if not description:
        logger.warning("AD-596a: Missing required 'description' field in %s", path)
        return None

    # ProbOS metadata extensions
    meta = fm.get("metadata") or {}
    intents_str = str(meta.get("probos-intents", "")).strip()
    # AD-626: Handle both comma-separated and space-separated intents
    if "," in intents_str:
        intents = [i.strip() for i in intents_str.split(",") if i.strip()]
    else:
        intents = intents_str.split() if intents_str else []

    # AD-626: Parse activation mode
    _raw_activation = str(meta.get("probos-activation", "discovery")).strip().lower()
    activation = _raw_activation if _raw_activation in ("discovery", "augmentation", "both") else "discovery"

    # AD-643a: Parse trigger tags for intent-driven activation
    triggers_str = str(meta.get("probos-triggers", "")).strip()
    if "," in triggers_str:
        triggers = [t.strip().lower() for t in triggers_str.split(",") if t.strip()]
    else:
        triggers = [t.lower() for t in triggers_str.split() if t] if triggers_str else []

    return CognitiveSkillEntry(
        name=str(name).strip(),
        description=str(description).strip(),
        skill_dir=path.parent,
        license=str(fm.get("license", "")),
        compatibility=str(fm.get("compatibility", "")),
        department=str(meta.get("probos-department", "*")) or "*",
        skill_id=str(meta.get("probos-skill-id", "")),
        min_proficiency=int(meta.get("probos-min-proficiency", 1)),
        min_rank=str(meta.get("probos-min-rank", "ensign")),
        intents=intents,
        origin="internal",
        loaded_at=time.time(),
        activation=activation,
        triggers=triggers,
    )


def get_skill_body(path: Path) -> str | None:
    """Return the markdown body (below frontmatter) from a SKILL.md file."""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return None

    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    return parts[2].strip()


def _validate_spec(entry: CognitiveSkillEntry) -> list[str]:
    """AgentSkills.io structural validation — Layer 1.

    Returns a list of error strings. Empty list means spec-compliant.
    """
    errors: list[str] = []

    # Name format: lowercase alphanumeric with hyphens, no leading/trailing/consecutive hyphens
    if not re.fullmatch(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?", entry.name):
        errors.append(
            "Name must be lowercase alphanumeric with hyphens, "
            "no leading/trailing/consecutive hyphens"
        )
    elif "--" in entry.name:
        errors.append(
            "Name must be lowercase alphanumeric with hyphens, "
            "no leading/trailing/consecutive hyphens"
        )

    # Name length
    if len(entry.name) > 64:
        errors.append("Name exceeds 64 characters")

    # Name matches directory
    if entry.name != entry.skill_dir.name:
        errors.append(
            f"Name '{entry.name}' does not match directory name '{entry.skill_dir.name}'"
        )

    # Description length
    if len(entry.description) > 1024:
        errors.append("Description exceeds 1024 characters")

    # Compatibility length
    if entry.compatibility and len(entry.compatibility) > 500:
        errors.append("Compatibility exceeds 500 characters")

    return errors


class CognitiveSkillCatalog:
    """Ship's Computer service — discovers, indexes, and serves cognitive skill files.

    Infrastructure tier (no identity). Provides progressive disclosure:
    descriptions at startup, full instructions on-demand.
    """

    def __init__(
        self,
        skills_dir: Path | None = None,
        db_path: str | None = None,
        connection_factory: "ConnectionFactory | None" = None,
    ) -> None:
        self._skills_dir = skills_dir
        self._db_path = db_path
        self._db: DatabaseConnection | None = None
        self._cache: dict[str, CognitiveSkillEntry] = {}
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory

            self._connection_factory = default_factory

    async def start(self) -> None:
        """Initialize SQLite table and scan skills directory."""
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            # Load existing entries from DB into cache
            cursor = await self._db.execute("SELECT * FROM cognitive_skill_catalog")
            rows = await cursor.fetchall()
            for row in rows:
                entry = self._row_to_entry(row)
                self._cache[entry.name] = entry

        # Scan for skill files
        if self._skills_dir and self._skills_dir.exists():
            await self.scan_and_register()

    async def stop(self) -> None:
        """Close DB connection."""
        if self._db:
            await self._db.close()
            self._db = None

    async def scan_and_register(self) -> int:
        """Scan skills_dir for SKILL.md files, parse and register each.

        Returns count of skills registered. Idempotent — re-scanning updates existing.
        """
        if not self._skills_dir or not self._skills_dir.exists():
            return 0

        count = 0
        for skill_md in self._skills_dir.rglob("SKILL.md"):
            entry = parse_skill_file(skill_md)
            if entry:
                await self.register(entry)
                count += 1

        logger.info("AD-596a: Scanned %d cognitive skills from %s", count, self._skills_dir)

        # AD-626: Log activation modes so operators can verify augmentation skills are registered
        for entry in self._cache.values():
            logger.info(
                "AD-626: Skill '%s' registered — activation=%s, intents=%s",
                entry.name, entry.activation, entry.intents,
            )

        return count

    async def register(self, entry: CognitiveSkillEntry) -> None:
        """Add or update a skill in the catalog (in-memory cache + SQLite)."""
        self._cache[entry.name] = entry

        if self._db:
            await self._db.execute(
                """INSERT OR REPLACE INTO cognitive_skill_catalog
                   (name, description, skill_dir, license, compatibility,
                    department, skill_id, min_proficiency, min_rank,
                    intents, origin, loaded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    entry.name,
                    entry.description,
                    str(entry.skill_dir),
                    entry.license,
                    entry.compatibility,
                    entry.department,
                    entry.skill_id,
                    entry.min_proficiency,
                    entry.min_rank,
                    json.dumps(entry.intents),
                    entry.origin,
                    entry.loaded_at,
                ),
            )
            await self._db.commit()

    def get_entry(self, name: str) -> CognitiveSkillEntry | None:
        """Lookup by name."""
        return self._cache.get(name)

    def list_entries(
        self,
        department: str | None = None,
        min_rank: str | None = None,
    ) -> list[CognitiveSkillEntry]:
        """List skills, optionally filtered by department and rank."""
        entries = list(self._cache.values())

        if department:
            entries = [
                e for e in entries
                if e.department == "*" or e.department == department
            ]

        if min_rank:
            agent_rank_order = _RANK_ORDER.get(min_rank, 0)
            entries = [
                e for e in entries
                if _RANK_ORDER.get(e.min_rank, 0) <= agent_rank_order
            ]

        return entries

    def get_descriptions(
        self,
        department: str | None = None,
        agent_rank: str | None = None,
    ) -> list[tuple[str, str, str]]:
        """Return (name, description, skill_id) tuples for progressive disclosure.

        Only skills the agent is allowed to see (department + rank filtering).
        """
        entries = self.list_entries(department=department, min_rank=agent_rank)
        return [(e.name, e.description, e.skill_id) for e in entries]

    def get_instructions(self, name: str) -> str | None:
        """Load and return full SKILL.md content below the frontmatter.

        This is the on-demand loading for activation. Returns None if not found.
        """
        entry = self._cache.get(name)
        if not entry:
            return None

        skill_path = entry.skill_dir / "SKILL.md"
        return get_skill_body(skill_path)

    def get_intents(self, name: str) -> list[str]:
        """Return declared intents for a skill."""
        entry = self._cache.get(name)
        return list(entry.intents) if entry else []

    def find_by_intent(self, intent_name: str) -> list[CognitiveSkillEntry]:
        """Reverse lookup: which skills handle a given intent (discovery mode).

        AD-626: Only returns skills with activation 'discovery' or 'both'.
        Augmentation-only skills are excluded from the discovery path.
        """
        return [
            e for e in self._cache.values()
            if intent_name in e.intents and e.activation in ("discovery", "both")
        ]

    def find_augmentation_skills(
        self,
        intent_name: str,
        department: str | None = None,
        agent_rank: str | None = None,
    ) -> list[CognitiveSkillEntry]:
        """AD-626: Find skills that augment an already-handled intent.

        Returns skills where activation is 'augmentation' or 'both',
        intent_name is in the skill's declared intents, and department/rank
        filters pass.
        """
        results = []
        for entry in self._cache.values():
            if entry.activation not in ("augmentation", "both"):
                continue
            if intent_name not in entry.intents:
                continue
            if department and entry.department != "*" and entry.department != department:
                continue
            if agent_rank:
                agent_rank_order = _RANK_ORDER.get(agent_rank, 0)
                if _RANK_ORDER.get(entry.min_rank, 0) > agent_rank_order:
                    continue
            results.append(entry)
        return results

    def find_triggered_skills(
        self,
        intended_actions: list[str],
        intent_name: str,
        department: str | None = None,
        agent_rank: str | None = None,
    ) -> list[CognitiveSkillEntry]:
        """AD-643a: Find augmentation skills matching specific action triggers.

        Unlike find_augmentation_skills() which matches by intent name,
        this matches by action trigger tags declared in probos-triggers.
        Falls back to intent matching for skills without triggers (backward compat).
        """
        if not intended_actions:
            return []

        action_set = set(intended_actions)
        results = []
        for entry in self._cache.values():
            if entry.activation not in ("augmentation", "both"):
                continue
            # AD-643a: Match by triggers if declared
            if entry.triggers:
                if not action_set.intersection(entry.triggers):
                    continue
            else:
                # No triggers declared — fall back to intent matching (backward compat)
                if intent_name not in entry.intents:
                    continue
            # Department gate
            if department and entry.department != "*" and entry.department != department:
                continue
            # Rank gate
            if agent_rank:
                agent_rank_order = _RANK_ORDER.get(agent_rank, 0)
                if _RANK_ORDER.get(entry.min_rank, 0) > agent_rank_order:
                    continue
            results.append(entry)
        return results

    def get_eligible_triggers(
        self,
        department: str | None = None,
        agent_rank: str | None = None,
    ) -> dict[str, list[str]]:
        """AD-643b: Return {action_tag: [skill_names]} for eligible skills.

        Filters by department and rank. Used to inject trigger awareness
        into ANALYZE so agents know what actions load quality skills.
        """
        result: dict[str, list[str]] = {}
        for entry in self._cache.values():
            if entry.activation not in ("augmentation", "both"):
                continue
            if not entry.triggers:
                continue
            # Department gate
            if department and entry.department != "*" and entry.department != department:
                continue
            # Rank gate
            if agent_rank:
                agent_rank_order = _RANK_ORDER.get(agent_rank, 0)
                if _RANK_ORDER.get(entry.min_rank, 0) > agent_rank_order:
                    continue
            for tag in entry.triggers:
                result.setdefault(tag, []).append(entry.name)
        return result

    # ------------------------------------------------------------------
    # AD-596e: Skill validation + instruction linting
    # ------------------------------------------------------------------

    async def validate_skill(
        self,
        name: str,
        validation_context: dict | None = None,
    ) -> SkillValidationResult:
        """Validate a cognitive skill through three layers.

        Layer 1: AgentSkills.io structural validation (always runs).
        Layer 2: ProbOS metadata cross-references (requires validation_context).
        Layer 3: Callsign linting (requires known_callsigns in context).

        Returns SkillValidationResult with errors and warnings.
        """
        entry = self._cache.get(name)
        if not entry:
            return SkillValidationResult(
                skill_name=name,
                valid=False,
                errors=[f"Skill '{name}' not found in catalog"],
                warnings=[],
            )

        errors: list[str] = []
        warnings: list[str] = []

        # Layer 1: AgentSkills.io spec validation
        errors.extend(_validate_spec(entry))

        # Layer 2: ProbOS metadata validation (only if context provided)
        if validation_context:
            valid_departments = validation_context.get("valid_departments")
            if valid_departments and entry.department not in valid_departments:
                errors.append(
                    f"Invalid department '{entry.department}' — "
                    f"must be one of: {sorted(valid_departments)}"
                )

            valid_ranks = validation_context.get("valid_ranks")
            if valid_ranks and entry.min_rank not in valid_ranks:
                errors.append(
                    f"Invalid rank '{entry.min_rank}' — "
                    f"must be one of: {sorted(valid_ranks)}"
                )

            if entry.min_proficiency < 1 or entry.min_proficiency > 5:
                errors.append(
                    f"Invalid min_proficiency {entry.min_proficiency} — must be 1-5"
                )

            valid_skill_ids = validation_context.get("valid_skill_ids")
            if valid_skill_ids is not None and entry.skill_id:
                if entry.skill_id not in valid_skill_ids:
                    warnings.append(
                        f"skill_id '{entry.skill_id}' not found in SkillRegistry"
                    )

        # Layer 3: Callsign linting (only if known_callsigns in context)
        if validation_context:
            known_callsigns = validation_context.get("known_callsigns")
            if known_callsigns:
                skill_path = entry.skill_dir / "SKILL.md"
                body = get_skill_body(skill_path)
                if body:
                    for callsign in known_callsigns:
                        pattern = re.compile(
                            r"\b" + re.escape(callsign) + r"\b", re.IGNORECASE
                        )
                        if pattern.search(body):
                            warnings.append(
                                f"Callsign '{callsign}' found in instruction body"
                            )

        return SkillValidationResult(
            skill_name=name,
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    async def validate_all(
        self,
        validation_context: dict | None = None,
    ) -> list[SkillValidationResult]:
        """Validate all skills in the catalog.

        Returns a list of SkillValidationResult for every registered skill.
        """
        results: list[SkillValidationResult] = []
        for name in self._cache:
            result = await self.validate_skill(name, validation_context)
            results.append(result)
        return results

    # ------------------------------------------------------------------
    # AD-596d: External skill import, discovery, enrichment, removal
    # ------------------------------------------------------------------

    async def import_skill(
        self,
        source_path: Path,
        origin: str = "external",
    ) -> CognitiveSkillEntry:
        """Import an external skill from *source_path* into the catalog.

        Validates the SKILL.md, checks for duplicate names, copies into
        ``config/skills/``, overrides ``origin``, and registers.

        Raises ``ValueError`` for invalid skills or duplicates.
        """
        skill_md = source_path / "SKILL.md"
        if not skill_md.exists():
            raise ValueError(f"No SKILL.md found in {source_path}")

        entry = parse_skill_file(skill_md)
        if entry is None:
            raise ValueError(f"Invalid SKILL.md in {source_path}")

        # Duplicate guard
        if entry.name in self._cache:
            raise ValueError(
                f"Skill '{entry.name}' already exists in catalog (use a different name)"
            )

        if not self._skills_dir:
            raise ValueError("No skills directory configured — cannot import")

        # Copy skill directory into config/skills/<name>
        dest = self._skills_dir / entry.name
        shutil.copytree(str(source_path), str(dest))

        # Override origin + update skill_dir to destination
        entry.origin = origin
        entry.skill_dir = dest

        await self.register(entry)
        logger.info("AD-596d: Imported skill '%s' (origin=%s) from %s", entry.name, origin, source_path)
        return entry

    def discover_package_skills(self) -> list[dict]:
        """Discover SKILL.md files shipped with installed pip packages.

        Walks site-packages for the ``.agents/skills/*/SKILL.md`` convention.
        Returns a list of dicts with package, skill_name, description, source_path,
        and has_probos_metadata. Does NOT auto-import.
        """
        import site

        results: list[dict] = []
        try:
            paths = list(site.getsitepackages())
        except AttributeError:
            paths = []
        try:
            paths.append(site.getusersitepackages())
        except AttributeError:
            pass

        for sp in paths:
            sp_path = Path(sp)
            if not sp_path.exists():
                continue
            for skill_md in sp_path.rglob(".agents/skills/*/SKILL.md"):
                entry = parse_skill_file(skill_md)
                if not entry:
                    continue
                # Infer package name from path
                pkg_root = skill_md.parent
                while pkg_root.parent != sp_path and pkg_root.parent != pkg_root:
                    pkg_root = pkg_root.parent
                results.append({
                    "package": pkg_root.name,
                    "skill_name": entry.name,
                    "description": entry.description,
                    "source_path": str(skill_md.parent),
                    "has_probos_metadata": bool(entry.skill_id or entry.department != "*"),
                })

        return results

    async def enrich_skill(
        self,
        name: str,
        metadata: dict,
        validation_context: dict | None = None,
    ) -> CognitiveSkillEntry:
        """Update ProbOS metadata on an existing catalog entry.

        *metadata* may contain: department, skill_id, min_proficiency,
        min_rank, intents. Rewrites the SKILL.md frontmatter and re-registers.

        If *validation_context* is provided, runs post-enrichment validation
        and logs any warnings/errors (advisory, does not block).

        Raises ``ValueError`` if skill not found.
        """
        entry = self._cache.get(name)
        if not entry:
            raise ValueError(f"Skill '{name}' not found in catalog")

        # Apply metadata updates
        if "department" in metadata:
            entry.department = str(metadata["department"])
        if "skill_id" in metadata:
            entry.skill_id = str(metadata["skill_id"])
        if "min_proficiency" in metadata:
            entry.min_proficiency = int(metadata["min_proficiency"])
        if "min_rank" in metadata:
            entry.min_rank = str(metadata["min_rank"])
        if "intents" in metadata:
            entry.intents = list(metadata["intents"])

        # Rewrite SKILL.md frontmatter to include metadata block
        skill_md = entry.skill_dir / "SKILL.md"
        if skill_md.exists():
            self._rewrite_frontmatter(skill_md, entry)

        await self.register(entry)
        logger.info("AD-596d: Enriched skill '%s' with metadata %s", name, list(metadata.keys()))

        # AD-596e: Post-enrichment validation (advisory)
        if validation_context:
            result = await self.validate_skill(name, validation_context)
            if result.warnings:
                logger.warning(
                    "AD-596e: Enriched skill '%s' has warnings: %s", name, result.warnings
                )
            if result.errors:
                logger.warning(
                    "AD-596e: Enriched skill '%s' has errors: %s", name, result.errors
                )

        return entry

    @staticmethod
    def _rewrite_frontmatter(skill_md: Path, entry: CognitiveSkillEntry) -> None:
        """Rewrite the SKILL.md frontmatter to reflect current entry metadata."""
        content = skill_md.read_text(encoding="utf-8")
        if not content.startswith("---"):
            return

        parts = content.split("---", 2)
        if len(parts) < 3:
            return

        try:
            fm = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return

        # Rebuild metadata block
        meta = fm.get("metadata") or {}
        meta["probos-department"] = entry.department
        if entry.skill_id:
            meta["probos-skill-id"] = entry.skill_id
        meta["probos-min-proficiency"] = entry.min_proficiency
        meta["probos-min-rank"] = entry.min_rank
        if entry.intents:
            meta["probos-intents"] = " ".join(entry.intents)
        elif "probos-intents" in meta:
            del meta["probos-intents"]
        fm["metadata"] = meta

        # Write back preserving markdown body
        new_yaml = yaml.dump(fm, default_flow_style=False, sort_keys=False)
        skill_md.write_text(f"---\n{new_yaml}---{parts[2]}", encoding="utf-8")

    async def remove_skill(self, name: str) -> None:
        """Remove an external skill from catalog and filesystem.

        Only external skills can be removed. Internal skills are protected.
        Raises ``ValueError`` if not found or if skill is internal.
        """
        entry = self._cache.get(name)
        if not entry:
            raise ValueError(f"Skill '{name}' not found in catalog")
        if entry.origin != "external":
            raise ValueError(
                f"Cannot remove internal skill '{name}' — only external skills may be removed"
            )

        # Remove from cache
        del self._cache[name]

        # Remove from SQLite
        if self._db:
            await self._db.execute(
                "DELETE FROM cognitive_skill_catalog WHERE name = ?", (name,)
            )
            await self._db.commit()

        # Remove skill directory
        skill_dir = entry.skill_dir
        if skill_dir.exists():
            shutil.rmtree(str(skill_dir))

        logger.info("AD-596d: Removed skill '%s'", name)

    @staticmethod
    def _row_to_entry(row: Any) -> CognitiveSkillEntry:
        """Convert a database row to a CognitiveSkillEntry."""
        intents_raw = row[9] if len(row) > 9 else "[]"
        try:
            intents = json.loads(intents_raw) if intents_raw else []
        except (json.JSONDecodeError, TypeError):
            intents = []

        return CognitiveSkillEntry(
            name=row[0],
            description=row[1],
            skill_dir=Path(row[2]),
            license=row[3] or "",
            compatibility=row[4] or "",
            department=row[5] or "*",
            skill_id=row[6] or "",
            min_proficiency=row[7] or 1,
            min_rank=row[8] or "ensign",
            intents=intents,
            origin=row[10] or "internal",
            loaded_at=row[11] or 0.0,
        )


# Re-export for type checking
from typing import Any  # noqa: E402
