"""Tests for Phase 6b: Dynamic Intent Discovery — PromptBuilder and descriptors."""

import pytest

from probos.agents.corrupted import CorruptedFileReaderAgent
from probos.agents.directory_list import DirectoryListAgent
from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_search import FileSearchAgent
from probos.agents.file_writer import FileWriterAgent
from probos.agents.heartbeat_monitor import SystemHeartbeatAgent
from probos.agents.http_fetch import HttpFetchAgent
from probos.agents.introspect import IntrospectionAgent
from probos.agents.red_team import RedTeamAgent
from probos.agents.shell_command import ShellCommandAgent
from probos.cognitive.decomposer import IntentDecomposer, SYSTEM_PROMPT
from probos.cognitive.llm_client import MockLLMClient
from probos.cognitive.prompt_builder import PromptBuilder
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.types import IntentDescriptor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_current_descriptors() -> list[IntentDescriptor]:
    """Collect all intent descriptors from the current set of user-facing agents."""
    descriptors: list[IntentDescriptor] = []
    seen: set[str] = set()
    for cls in [
        FileReaderAgent,
        FileWriterAgent,
        DirectoryListAgent,
        FileSearchAgent,
        ShellCommandAgent,
        HttpFetchAgent,
        IntrospectionAgent,
    ]:
        for d in cls.intent_descriptors:
            if d.name not in seen:
                seen.add(d.name)
                descriptors.append(d)
    return descriptors


# ---------------------------------------------------------------------------
# PromptBuilder unit tests
# ---------------------------------------------------------------------------

class TestPromptBuilder:

    def test_build_contains_all_current_intents(self):
        """Build prompt with current descriptors. Assert all 11 intents present."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        for name in [
            "read_file", "stat_file", "write_file", "list_directory",
            "search_files", "run_command", "http_fetch",
            "explain_last", "agent_info", "system_health", "why",
        ]:
            assert name in prompt, f"Intent {name!r} missing from dynamic prompt"

    def test_consensus_rules_generated(self):
        """Assert prompt contains consensus-true/false rules."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())

        # Consensus-true intents
        for name in ["write_file", "run_command"]:
            assert f'All {name} intents MUST have "use_consensus": true' in prompt

        # Consensus-false intents should appear in a combined rule
        for name in ["read_file", "stat_file", "list_directory", "search_files", "http_fetch"]:
            assert name in prompt

    def test_reflect_rules_generated(self):
        """Assert prompt mentions reflect for introspection intents."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())

        for name in ["explain_last", "agent_info", "system_health", "why"]:
            # These should appear in a consensus-false rule for reflect intents
            assert name in prompt

    def test_empty_descriptors(self):
        """Build with empty list. Assert preamble and format but no intent table entries."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt([])

        assert "You MUST respond with ONLY a JSON object" in prompt
        assert "## Response format" in prompt
        assert "## Available intents" in prompt
        # No intent names in the table
        assert "read_file" not in prompt.split("## Response format")[0].split("## Available intents")[1]

    def test_custom_descriptor_appears(self):
        """Custom IntentDescriptor appears in generated prompt."""
        builder = PromptBuilder()
        custom = IntentDescriptor(
            name="custom_action",
            params={"name": "..."},
            description="Do custom thing",
        )
        prompt = builder.build_system_prompt([custom])
        assert "custom_action" in prompt
        assert "Do custom thing" in prompt

    def test_prompt_contains_json_instruction(self):
        """Build prompt, assert it contains the critical JSON-only instruction."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "You MUST respond with ONLY a JSON object" in prompt

    def test_descriptors_sorted_by_name(self):
        """Pass descriptors in reverse order. Assert the intent table is alphabetically sorted."""
        builder = PromptBuilder()
        descs = [
            IntentDescriptor(name="zebra_action", params={}, description="Z action"),
            IntentDescriptor(name="alpha_action", params={}, description="A action"),
            IntentDescriptor(name="mid_action", params={}, description="M action"),
        ]
        prompt = builder.build_system_prompt(descs)

        # Extract the intent table section
        table_section = prompt.split("## Available intents")[1].split("## Response format")[0]
        alpha_pos = table_section.index("alpha_action")
        mid_pos = table_section.index("mid_action")
        zebra_pos = table_section.index("zebra_action")
        assert alpha_pos < mid_pos < zebra_pos

    def test_duplicate_intent_names_deduplicated(self):
        """Pass two descriptors with the same name. Assert it appears only once in the table."""
        builder = PromptBuilder()
        descs = [
            IntentDescriptor(name="dup_intent", params={}, description="First"),
            IntentDescriptor(name="dup_intent", params={}, description="Second"),
        ]
        prompt = builder.build_system_prompt(descs)
        # Extract the intent table section (between Available intents header and Response format)
        table = prompt.split("## Available intents")[1].split("## Response format")[0]
        assert table.count("dup_intent") == 1

    def test_prompt_contains_examples(self):
        """Assert the prompt contains the fixed example section."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "## Examples" in prompt
        assert 'User: "read the file at /tmp/test.txt"' in prompt

    def test_prompt_contains_response_format(self):
        """Assert the prompt contains the JSON response schema."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "## Response format" in prompt
        assert '"intents": [...]' in prompt
        assert '"reflect": false' in prompt

    def test_run_command_description_no_blank_check(self):
        """run_command descriptor should NOT say 'anything a shell can do'."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "anything a shell can do" not in prompt

    def test_anti_scripting_rule_present(self):
        """Prompt should contain explicit rule against python -c workarounds."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "NEVER use run_command to run Python" in prompt


class TestCapabilityGapExamples:
    """Capability-gap examples must be suppressed when matching intents exist."""

    def test_gap_examples_present_without_matching_intents(self):
        """With default intents (no translate/writing), both gap examples appear."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "translate 'hello world' to French" in prompt
        assert "capability_gap" in prompt
        assert "haiku about the ocean" in prompt

    def test_translate_gap_suppressed_when_translate_intent_exists(self):
        """Adding a translate_text intent suppresses the translate gap example."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(
                name="translate_text",
                params={"text": "...", "target_language": "..."},
                description="Translate text to a target language",
            ),
        ]
        prompt = builder.build_system_prompt(descs)
        # translate gap example should be gone
        assert "I don't have an intent for translation yet" not in prompt
        # creative writing gap should still be there
        assert "haiku about the ocean" in prompt

    def test_writing_gap_suppressed_when_writing_intent_exists(self):
        """Adding a creative_writing intent suppresses the haiku gap example."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(
                name="creative_writing",
                params={"prompt": "..."},
                description="Generate creative text",
            ),
        ]
        prompt = builder.build_system_prompt(descs)
        # writing gap should be gone
        assert "I don't have an intent for creative writing yet" not in prompt
        # translate gap should still be present
        assert "translate 'hello world' to French" in prompt

    def test_both_gaps_suppressed_when_both_intents_exist(self):
        """Both gap examples suppressed when matching intents exist."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(
                name="translate_text",
                params={"text": "..."},
                description="Translate",
            ),
            IntentDescriptor(
                name="creative_writing",
                params={"prompt": "..."},
                description="Write creatively",
            ),
        ]
        prompt = builder.build_system_prompt(descs)
        assert "I don't have an intent for translation yet" not in prompt
        assert "I don't have an intent for creative writing yet" not in prompt

    def test_lookup_gap_present_without_matching_intent(self):
        """Knowledge-lookup gap example appears when no lookup intent exists."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "who is Alan Turing?" in prompt
        assert "I don't have an intent for knowledge lookup yet" in prompt

    def test_lookup_gap_suppressed_when_lookup_intent_exists(self):
        """Adding a lookup_info intent suppresses the knowledge-lookup gap example."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(
                name="lookup_info",
                params={"query": "..."},
                description="Look up information about a topic",
            ),
        ]
        prompt = builder.build_system_prompt(descs)
        assert "I don't have an intent for knowledge lookup yet" not in prompt
        # Other gap examples should still be present
        assert "translate 'hello world' to French" in prompt

    def test_all_gaps_suppressed_when_all_intents_exist(self):
        """All gap examples suppressed when all matching intents exist."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(name="translate_text", params={}, description="x"),
            IntentDescriptor(name="creative_writing", params={}, description="x"),
            IntentDescriptor(name="lookup_info", params={}, description="x"),
        ]
        prompt = builder.build_system_prompt(descs)
        assert "I don't have an intent for translation yet" not in prompt
        assert "I don't have an intent for creative writing yet" not in prompt
        assert "I don't have an intent for knowledge lookup yet" not in prompt

    def test_core_examples_always_present(self):
        """Core examples (read_file, write_file, etc.) always present regardless."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(name="translate_text", params={}, description="x"),
            IntentDescriptor(name="creative_writing", params={}, description="x"),
        ]
        prompt = builder.build_system_prompt(descs)
        assert 'User: "read the file at /tmp/test.txt"' in prompt
        assert 'User: "write hello to /tmp/out.txt"' in prompt
        assert '## Examples' in prompt

    def test_qr_gap_example_present(self):
        """QR code gap example should appear when no QR intent exists."""
        builder = PromptBuilder()
        prompt = builder.build_system_prompt(_all_current_descriptors())
        assert "QR code" in prompt or "qr" in prompt.lower()
        assert "capability_gap" in prompt

    def test_qr_gap_suppressed_when_qr_intent_exists(self):
        """QR code gap example suppressed when a qr-related intent exists."""
        builder = PromptBuilder()
        descs = _all_current_descriptors() + [
            IntentDescriptor(
                name="generate_qr_code",
                params={"data": "..."},
                description="Generate a QR code",
            ),
        ]
        prompt = builder.build_system_prompt(descs)
        assert "I don't have an intent for QR code generation yet" not in prompt


# ---------------------------------------------------------------------------
# IntentDescriptor on agents
# ---------------------------------------------------------------------------

class TestAgentDescriptors:

    def test_all_agents_have_descriptors(self):
        """User-facing agents have non-empty intent_descriptors."""
        for cls in [
            FileReaderAgent, FileWriterAgent, DirectoryListAgent,
            FileSearchAgent, ShellCommandAgent, HttpFetchAgent,
            IntrospectionAgent,
        ]:
            assert len(cls.intent_descriptors) > 0, (
                f"{cls.__name__} should have intent_descriptors"
            )

    def test_non_intent_agents_have_empty_descriptors(self):
        """Non-intent agents have empty intent_descriptors."""
        for cls in [RedTeamAgent, CorruptedFileReaderAgent, SystemHeartbeatAgent]:
            assert len(cls.intent_descriptors) == 0, (
                f"{cls.__name__} should have empty intent_descriptors"
            )

    def test_descriptor_names_match_handled_intents(self):
        """Every descriptor name corresponds to an intent the agent recognizes."""
        for cls in [
            FileReaderAgent, FileWriterAgent, DirectoryListAgent,
            FileSearchAgent, ShellCommandAgent, HttpFetchAgent,
            IntrospectionAgent,
        ]:
            handled = getattr(cls, "_handled_intents", set())
            for desc in cls.intent_descriptors:
                assert desc.name in handled, (
                    f"{cls.__name__} declares descriptor {desc.name!r} "
                    f"but _handled_intents = {handled}"
                )


# ---------------------------------------------------------------------------
# Decomposer integration
# ---------------------------------------------------------------------------

class TestDecomposerIntegration:

    @pytest.mark.asyncio
    async def test_decomposer_uses_dynamic_prompt(self):
        """Decomposer with refresh_descriptors uses dynamic prompt and still works."""
        llm = MockLLMClient()
        wm = WorkingMemoryManager()
        decomposer = IntentDecomposer(llm_client=llm, working_memory=wm)
        decomposer.refresh_descriptors(_all_current_descriptors())

        dag = await decomposer.decompose("read the file at /tmp/test.txt")
        assert len(dag.nodes) == 1
        assert dag.nodes[0].intent == "read_file"

    @pytest.mark.asyncio
    async def test_decomposer_falls_back_to_legacy(self):
        """Decomposer without refresh_descriptors uses legacy prompt."""
        llm = MockLLMClient()
        wm = WorkingMemoryManager()
        decomposer = IntentDecomposer(llm_client=llm, working_memory=wm)
        # Do NOT call refresh_descriptors

        dag = await decomposer.decompose("read the file at /tmp/test.txt")
        assert len(dag.nodes) == 1
        assert dag.nodes[0].intent == "read_file"

    @pytest.mark.asyncio
    async def test_decomposer_refresh_adds_new_intent(self):
        """After refresh with custom descriptor, system prompt includes new intent."""
        llm = MockLLMClient()
        wm = WorkingMemoryManager()
        decomposer = IntentDecomposer(llm_client=llm, working_memory=wm)

        custom = IntentDescriptor(
            name="custom_greeting",
            params={"name": "..."},
            description="Generate a greeting",
        )
        descs = _all_current_descriptors() + [custom]
        decomposer.refresh_descriptors(descs)

        # The system prompt now includes the custom intent
        prompt = decomposer._prompt_builder.build_system_prompt(decomposer._intent_descriptors)
        assert "custom_greeting" in prompt
