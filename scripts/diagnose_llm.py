"""Diagnostic script: send a translation request to the real LLM and trace parsing."""

import asyncio
import json
import re
import sys

sys.path.insert(0, "src")

from probos.config import load_config
from probos.cognitive.llm_client import OpenAICompatibleClient
from probos.cognitive.decomposer import IntentDecomposer, _LEGACY_SYSTEM_PROMPT
from probos.cognitive.working_memory import WorkingMemoryManager
from probos.types import LLMRequest


async def main():
    config = load_config("config/system.yaml")
    client = OpenAICompatibleClient(config=config.cognitive)
    wm = WorkingMemoryManager()
    decomposer = IntentDecomposer(llm_client=client, working_memory=wm, timeout=30.0)

    test_input = "translate hello into japanese"

    # Step 1: Raw LLM call
    print("=" * 60)
    print(f"INPUT: {test_input}")
    print("=" * 60)

    request = LLMRequest(
        prompt=test_input,
        system_prompt=_LEGACY_SYSTEM_PROMPT,
        tier="fast",
    )
    resp = await client.complete(request)

    print(f"\nModel: {resp.model}, Tier: {resp.tier}")
    print(f"Error: {resp.error}")
    print()
    print("--- RAW RESPONSE (repr) ---")
    print(repr(resp.content))
    print()
    print("--- RAW RESPONSE (display) ---")
    print(resp.content)

    # Step 2: Strip think tags
    stripped = re.sub(r"<think>.*?</think>", "", resp.content, flags=re.DOTALL).strip()
    print()
    print("--- AFTER THINK-TAG STRIP ---")
    print(repr(stripped))

    # Step 3: Try _extract_json
    print()
    print("--- _extract_json ---")
    try:
        json_str = decomposer._extract_json(resp.content)
        print(f"Extracted: {repr(json_str[:300])}")
        data = json.loads(json_str)
        print(f"Parsed OK: {json.dumps(data, indent=2)}")
        print(f"  capability_gap: {data.get('capability_gap', 'MISSING')}")
        print(f"  intents: {data.get('intents', 'MISSING')}")
        print(f"  response: {data.get('response', 'MISSING')}")
    except Exception as e:
        print(f"FAILED: {e}")

    # Step 4: Full decompose pipeline
    print()
    print("--- FULL DECOMPOSE ---")
    dag = await decomposer.decompose(test_input)
    print(f"  nodes: {len(dag.nodes)}")
    print(f"  response repr: {repr(dag.response)}")
    print(f"  response bool: {bool(dag.response)}")
    print(f"  capability_gap: {dag.capability_gap}")
    print(f"  reflect: {dag.reflect}")

    # Step 5: Check if self-mod would trigger
    from probos.cognitive.decomposer import is_capability_gap as is_gap_fn

    if not dag.nodes:
        is_gap = dag.capability_gap or (dag.response and is_gap_fn(dag.response))
        if dag.response and not is_gap:
            print(f"\n  RESULT: Conversational response (self-mod SKIPPED)")
        elif is_gap:
            print(f"\n  RESULT: Capability gap detected (self-mod WOULD TRIGGER)")
        else:
            print(f"\n  RESULT: Empty response (self-mod would trigger)")
    else:
        print(f"\n  RESULT: {len(dag.nodes)} intents parsed (normal execution)")

    # Step 6: Full runtime pipeline test
    print()
    print("=" * 60)
    print("STEP 6: FULL RUNTIME PIPELINE")
    print("=" * 60)
    import logging
    logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    runtime = None
    try:
        from probos.runtime import ProbOSRuntime
        import tempfile
        data_dir = tempfile.mkdtemp(prefix="probos_diag_")
        runtime = ProbOSRuntime(data_dir=data_dir, llm_client=client)
        await runtime.start()

        print(f"  self_mod_pipeline: {runtime.self_mod_pipeline is not None}")
        print(f"  self_mod enabled: {runtime.config.self_mod.enabled}")

        # Step 6a: Check _extract_unhandled_intent
        print()
        print("--- _extract_unhandled_intent ---")
        intent_meta = await runtime._extract_unhandled_intent(test_input)
        if intent_meta:
            print(f"  OK: {json.dumps(intent_meta, indent=2)}")
        else:
            print("  RETURNED None!")

        # Step 6b: Full process_natural_language
        print()
        print("--- process_natural_language ---")
        result = await runtime.process_natural_language(test_input)
        print(f"  result keys: {list(result.keys())}")
        if "dag" in result:
            d = result["dag"]
            print(f"  dag.nodes: {len(d.nodes)}")
            print(f"  dag.response: {repr(d.response)}")
            print(f"  dag.capability_gap: {d.capability_gap}")
        if "self_mod" in result:
            print(f"  self_mod: {result['self_mod']}")
        if "response" in result:
            print(f"  response: {repr(result['response'][:200])}")
        print(f"  Full result: {json.dumps({k: str(v)[:100] for k, v in result.items()}, indent=2)}")

    except Exception as e:
        import traceback
        print(f"  ERROR: {e}")
        traceback.print_exc()
    finally:
        if runtime:
            await runtime.stop()


if __name__ == "__main__":
    asyncio.run(main())
