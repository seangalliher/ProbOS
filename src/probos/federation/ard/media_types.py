"""AD-1040: ARD (Agentic Resource Discovery) media-type taxonomy.

DD-8 layer discipline: this module imports NOTHING from the rest of
``probos`` — it is pure stdlib constants. That non-import is the
byte-identical proof that the ARD envelope ships as types only.

The media types mirror the public ARD / ai-catalog ecosystem conventions
(MCP server cards, A2A agent cards, ai-skill, ai-catalog/registry).
``PROBOS_AXIS_TO_MEDIA_TYPE`` maps ProbOS's own capability axis labels onto
that public taxonomy so a future projector (AD-1041) can emit the right
media type per entry.
"""

MT_PROBOS_TOOL = "application/probos-tool+json"
MT_MCP_SERVER = "application/mcp-server-card+json"
MT_AI_SKILL = "application/ai-skill"
MT_A2A_AGENT = "application/a2a-agent-card+json"
MT_AI_CATALOG = "application/ai-catalog+json"
MT_AI_REGISTRY = "application/ai-registry+json"

PROBOS_AXIS_TO_MEDIA_TYPE: dict[str, str] = {
    "built_in": MT_PROBOS_TOOL,
    "extension": MT_PROBOS_TOOL,
    "mcp": MT_MCP_SERVER,
    "skill": MT_AI_SKILL,
    "mesh_intent": MT_A2A_AGENT,
    "agent": MT_A2A_AGENT,
    "pack": MT_AI_CATALOG,
}
