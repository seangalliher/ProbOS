"""Dynamic system prompt assembly from registered intent descriptors."""

from __future__ import annotations

import json
import platform
from typing import Any

from probos.types import IntentDescriptor


def get_platform_context() -> str:
    """Return a short platform description for inclusion in LLM prompts."""
    system = platform.system()       # e.g. "Windows", "Linux", "Darwin"
    release = platform.release()     # e.g. "10", "6.5.0-44-generic"
    if system == "Windows":
        shell = "PowerShell"
    elif system == "Darwin":
        shell = "zsh (macOS default)"
    else:
        shell = "bash"
    return (
        f"## Host platform\n\n"
        f"Operating system: {system} {release}\n"
        f"Default shell: {shell}\n"
        f"Use only {system}-compatible commands for run_command intents."
    )


PROMPT_PREAMBLE = """\
You MUST respond with ONLY a JSON object. No preamble, no explanation, no \
markdown code fences, no text before or after the JSON. Your entire response \
must be parseable as a single JSON object.

You are the intent decomposition engine of ProbOS, a probabilistic agent-native \
operating system runtime. You translate user requests into structured intents."""

PROMPT_RESPONSE_FORMAT = """\
## Response format

Your response MUST be exactly one JSON object with this structure:

{"intents": [...], "response": "optional text", "reflect": false, "capability_gap": false}

- "intents": array of intent objects (empty array if no actionable intents)
- "response": optional string — a brief message for the user. Use this for \
conversational replies, confirmations, or when no intents apply.
- "reflect": boolean — set to true when the user asks for analysis, \
interpretation, comparison, summary, or opinion about the results. Set to \
false for simple data retrieval or command execution.
- "capability_gap": boolean — set to true when the request is a task that \
no available intent can handle (translation, creative writing, etc.). \
Set to false for conversational replies and for tasks that map to an intent.

Each intent object:

{"id": "t1", "intent": "<name>", "params": {...}, "depends_on": [], "use_consensus": false}"""

PROMPT_EXAMPLES = """\
## Examples

User: "read the file at /tmp/test.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/test.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "read /tmp/a.txt and /tmp/b.txt"
{"intents": [{"id": "t1", "intent": "read_file", "params": {"path": "/tmp/a.txt"}, "depends_on": [], "use_consensus": false}, {"id": "t2", "intent": "read_file", "params": {"path": "/tmp/b.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "write hello to /tmp/out.txt"
{"intents": [{"id": "t1", "intent": "write_file", "params": {"path": "/tmp/out.txt", "content": "hello"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "hello"
{"intents": [], "response": "Hello! I'm ProbOS \u2014 a probabilistic agent-native OS that learns and evolves. I can search the web, read and summarize pages, check weather, get news, translate text, manage your notes and todos, set reminders, run commands, and answer questions about my own state. I also build new capabilities on the fly when you ask me something I can't do yet. What would you like to do?"}

User: "what can you do?"
{"intents": [], "response": "I can search the web, read and summarize pages, check weather, get news headlines, translate text, summarize content, do calculations, manage notes and todos, set reminders, read and write files, run shell commands, and answer questions about my own state. I learn from our interactions and build new capabilities when needed. Writes and commands go through consensus verification."}

User: "what is the weather in Denver?"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://wttr.in/Denver?format=3", "method": "GET"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "what time is it in Tokyo?"
{"intents": [{"id": "t1", "intent": "run_command", "params": {"command": "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"}, "depends_on": [], "use_consensus": true}], "reflect": true}

User: "list the files in /tmp/mydir"
{"intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp/mydir"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "find all .txt files in /home/user/docs"
{"intents": [{"id": "t1", "intent": "search_files", "params": {"path": "/home/user/docs", "pattern": "*.txt"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "run the command echo hello"
{"intents": [{"id": "t1", "intent": "run_command", "params": {"command": "echo hello"}, "depends_on": [], "use_consensus": true}], "reflect": false}

User: "fetch https://httpbin.org/get"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://httpbin.org/get", "method": "GET"}, "depends_on": [], "use_consensus": false}], "reflect": false}

User: "what is the largest file in /tmp/mydir?"
{"intents": [{"id": "t1", "intent": "list_directory", "params": {"path": "/tmp/mydir"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "fetch https://example.com and summarize it"
{"intents": [{"id": "t1", "intent": "http_fetch", "params": {"url": "https://example.com", "method": "GET"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "why did you use file_reader for that?"
{"intents": [{"id": "t1", "intent": "why", "params": {"question": "why did you use file_reader for that?"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "how healthy is the system?"
{"intents": [{"id": "t1", "intent": "system_health", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "what just happened?"
{"intents": [{"id": "t1", "intent": "explain_last", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "tell me about file_reader agents"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {"agent_type": "file_reader"}, "depends_on": [], "use_consensus": false}], "reflect": true}

User: "describe the agents" or "what agents are active?"
{"intents": [{"id": "t1", "intent": "agent_info", "params": {}, "depends_on": [], "use_consensus": false}], "reflect": true}"""

# Capability-gap examples conditionally appended when no matching intent
# exists.  Each entry: (user_input, gap_response, intent_keyword).
# When the matching keyword appears in any registered intent name, the
# example is suppressed so the LLM uses the intent table instead of
# mimicking the hardcoded gap example (critical for non-thinking models).
_GAP_EXAMPLES: list[tuple[str, str, str]] = [
    (
        "translate 'hello world' to French",
        "I don't have an intent for translation yet.",
        "translate",
    ),
    (
        "write me a haiku about the ocean",
        "I don't have an intent for creative writing yet.",
        "writing",
    ),
    (
        "who is Alan Turing?",
        "I don't have an intent for knowledge lookup yet.",
        "lookup",
    ),
    (
        "generate a QR code for https://example.com",
        "I don't have an intent for QR code generation yet.",
        "qr",
    ),
]


class PromptBuilder:
    """Assembles the decomposer system prompt dynamically from IntentDescriptors."""

    def build_system_prompt(self, descriptors: list[IntentDescriptor]) -> str:
        """Build the full system prompt with a dynamically generated intent table.

        The output is functionally equivalent to the legacy SYSTEM_PROMPT when
        given the same set of intents.  Descriptors are sorted by name for
        deterministic output.
        """
        # Deduplicate by name, keeping first occurrence
        seen: set[str] = set()
        unique: list[IntentDescriptor] = []
        for d in descriptors:
            if d.name not in seen:
                seen.add(d.name)
                unique.append(d)

        # Sort alphabetically for determinism
        unique.sort(key=lambda d: d.name)

        parts: list[str] = [PROMPT_PREAMBLE]

        # Platform context
        parts.append("")
        parts.append(get_platform_context())

        # Intent table
        parts.append("")
        parts.append(self._build_intent_table(unique))

        # Response format
        parts.append("")
        parts.append(PROMPT_RESPONSE_FORMAT)

        # Rules
        parts.append("")
        parts.append(self._build_rules(unique))

        # Examples
        parts.append("")
        parts.append(self._build_examples(unique))

        return "\n".join(parts)

    def _build_examples(self, descriptors: list[IntentDescriptor]) -> str:
        """Return examples block, conditionally including capability-gap entries.

        Capability-gap examples (e.g. translate → gap) are suppressed when a
        matching intent already exists in *descriptors*.  This prevents
        non-thinking models from blindly following the gap example instead of
        using the intent table.
        """
        intent_names = {d.name for d in descriptors}
        gap_lines: list[str] = []
        for user_input, response, keyword in _GAP_EXAMPLES:
            if any(keyword in name for name in intent_names):
                continue  # intent available — skip misleading gap example
            gap_lines.append(
                f'\nUser: "{user_input}"\n'
                f'{{"intents": [], "response": "{response}", '
                f'"capability_gap": true}}'
            )
        if gap_lines:
            return PROMPT_EXAMPLES + "".join(gap_lines)
        return PROMPT_EXAMPLES

    def _build_intent_table(self, descriptors: list[IntentDescriptor]) -> str:
        """Generate the '## Available intents' markdown table."""
        lines = [
            "## Available intents",
            "",
            "| Intent       | Params                                       | Description                    |",
            "|--------------|----------------------------------------------|--------------------------------|",
        ]
        for d in descriptors:
            params_str = json.dumps(d.params) if d.params else "{}"
            lines.append(
                f"| {d.name:<15s}| {params_str:<45s}| {d.description:<31s}|"
            )
        return "\n".join(lines)

    def _build_rules(self, descriptors: list[IntentDescriptor]) -> str:
        """Generate the '## Rules' section with consensus and reflect rules."""
        # Static rules that always apply
        rules = [
            '1. RESPOND ONLY WITH JSON. No natural language outside the JSON object. '
            'No markdown. No code fences. No commentary. Just the raw JSON object.',
            '2. Use sequential IDs: t1, t2, t3, \u2026',
            '3. Independent intents have "depends_on": [] and execute in parallel.',
            '4. If intent B needs the result of intent A, set "depends_on": ["t1"].',
        ]

        # Generate consensus rules
        consensus_true = [d.name for d in descriptors if d.requires_consensus]
        consensus_false = [d.name for d in descriptors if not d.requires_consensus]

        rule_num = 5
        for name in consensus_true:
            rules.append(
                f'{rule_num}. All {name} intents MUST have "use_consensus": true.'
            )
            rule_num += 1

        # Group non-consensus intents into a single rule if there are any
        if consensus_false:
            if len(consensus_false) > 1:
                names = ", ".join(consensus_false[:-1]) + " and " + consensus_false[-1]
            else:
                names = consensus_false[0]
            rules.append(
                f'{rule_num}. {names} intents should have "use_consensus": false.'
            )
            rule_num += 1

        # Static path and fallback rules
        rules.append(
            f'{rule_num}. Paths must be absolute. Use the path exactly as the user provides it.'
        )
        rule_num += 1
        rules.append(
            f'{rule_num}. If the request is conversational (greeting, help, small talk), respond with '
            '{"intents": [], "response": "a helpful reply"}. '
            'If the request is a task (translation, analysis, creative writing, knowledge/factual '
            'lookup, person lookup, etc.) that cannot be mapped to any available intent, respond with '
            '{"intents": [], "response": "I don\'t have an intent for <task type> yet.", "capability_gap": true}. '
            'NEVER answer factual questions or perform tasks yourself in the response field — '
            'you have no internet access and will hallucinate.'
        )
        rule_num += 1
        rules.append(f'{rule_num}. Never invent intents not in the table above.')
        rule_num += 1

        # Constrain run_command to prevent shell-as-programming-language abuse
        intent_names = {d.name for d in descriptors}
        if "run_command" in intent_names:
            rules.append(
                f'{rule_num}. ONLY use run_command when a real program or OS utility '
                'genuinely computes the answer (e.g. date/time, math, system info, '
                'pip install). NEVER use run_command to output hardcoded text you '
                'already know (echo, Write-Host, Write-Output, printf, print, etc.).'
            )
            rule_num += 1
            rules.append(
                f'{rule_num}. For tasks requiring intelligence or external data — translation, '
                'creative writing, summarization, knowledge questions, person/topic lookup, '
                'factual questions — if a matching intent exists in the '
                'table above, use it. If NO matching intent exists, return '
                '{"intents": [], "response": "I don\'t have an intent for <task type> yet.", "capability_gap": true}. '
                'NEVER answer factual questions or perform tasks yourself in the response field — '
                'you have no internet access and will hallucinate. '
                'Conversational replies (greetings, help, small talk) are fine as direct responses.'
            )
            rule_num += 1
            rules.append(
                f'{rule_num}. NEVER use run_command to run Python, Node, Ruby, or any '
                'programming language interpreter (e.g. python -c "...", node -e "...", '
                'ruby -e "...") as a workaround for missing capabilities. If the task '
                'requires a library or capability not in the intent table, return '
                '{"intents": [], "response": "I don\'t have that capability yet.", '
                '"capability_gap": true}. The system will design a dedicated agent.'
            )
            rule_num += 1

        rules.append(
            f'{rule_num}. Set "reflect" to true when the user asks for analysis, interpretation, '
            'comparison, summary, or opinion about results. Also set "reflect" to true for '
            'any intent that transforms, translates, generates, or produces content the user '
            'wants to see explained in natural language. Set to false only for simple data '
            'retrieval or command execution where the raw result is self-explanatory.'
        )
        rule_num += 1

        # Reflect rule for descriptors that require it
        reflect_intents = [d.name for d in descriptors if d.requires_reflect]
        if reflect_intents:
            names = ", ".join(reflect_intents)
            rules.append(
                f'{rule_num}. {names} intents MUST always have "reflect": true.'
            )
            rule_num += 1

        if "http_fetch" in intent_names:
            rules.append(
                f'{rule_num}. NEVER fabricate API keys, tokens, credentials, or authentication '
                'parameters in URLs. If a service requires an API key the user has not provided, '
                'respond with {"intents": [], "response": "That service requires an API key I '
                'don\'t have configured."}. For http_fetch, only use URLs that work without '
                'authentication.'
            )
            rule_num += 1

        lines = ["## Rules", ""]
        lines.extend(rules)
        return "\n".join(lines)
