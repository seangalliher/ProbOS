# Configuration Reference

**Generated file — do not edit by hand.**
Regenerate with `python scripts/gen_config_reference.py`.
Every description below comes from the `Field(description=...)` in
`src/probos/config.py`, so the way to improve this page is to improve that.

ProbOS runs with **zero configuration** — every field has a default. The
shipped `config/system.yaml` deliberately does not list every knob; this page
does.

A value marked **default-OFF** ships inert. Turning it on is an operator
decision, and each one states what changes when you do.


## `system`

Top-level system identity.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `name` | `str` | `'ProbOS'` | — |  |
| `version` | `str` | `'0.1.0'` | — |  |
| `log_level` | `str` | `'INFO'` | — |  |

## `pools`

Agent pool configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `default_pool_size` | `int` | `3` | — |  |
| `max_pool_size` | `int` | `7` | — |  |
| `min_pool_size` | `int` | `2` | — |  |
| `spawn_cooldown_ms` | `int` | `500` | — |  |
| `health_check_interval_seconds` | `float` | `5.0` | — |  |

## `mesh`

Mesh communication configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `gossip_interval_ms` | `int` | `1000` | — |  |
| `hebbian_decay_rate` | `float` | `0.995` | — |  |
| `hebbian_social_decay_rate` | `float` | `0.995` | — |  |
| `intent_skill_map` | `dict[str, str]` | `{}` | — |  |
| `hebbian_reward` | `float` | `0.05` | — |  |
| `signal_ttl_seconds` | `float` | `30.0` | — |  |
| `capability_broadcast_interval_seconds` | `float` | `5.0` | — |  |
| `semantic_matching` | `bool` | `True` | — |  |
| `handler_latency_deterministic_ms` | `float` | `100.0` | — |  |
| `handler_latency_network_ms` | `float` | `10000.0` | — |  |
| `handler_latency_cognitive_ms` | `float` | `30000.0` | — |  |

## `consensus`

Consensus layer configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `min_votes` | `int` | `3` | — |  |
| `approval_threshold` | `float` | `0.6` | — |  |
| `use_confidence_weights` | `bool` | `True` | — |  |
| `verification_timeout_seconds` | `float` | `5.0` | — |  |
| `red_team_pool_size` | `int` | `2` | — |  |
| `trust_prior_alpha` | `float` | `2.0` | — |  |
| `trust_prior_beta` | `float` | `2.0` | — |  |
| `trust_decay_rate` | `float` | `0.999` | — |  |

## `cognitive`

Cognitive layer configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `llm_base_url` | `str` | `'http://127.0.0.1:8080/v1'` | — |  |
| `llm_api_key` | `str` | `''` | — |  |
| `llm_timeout_seconds` | `float` | `30.0` | — |  |
| `llm_model_fast` | `str` | `'claude-sonnet-4-6'` | — |  |
| `llm_model_standard` | `str` | `'claude-sonnet-4-6'` | — |  |
| `llm_model_deep` | `str` | `'claude-opus-4-6'` | — |  |
| `llm_health_min_consecutive_healthy` | `int` | `3` | — |  |
| `llm_base_url_fast` | `str | None` | `None` | — |  |
| `llm_api_key_fast` | `str | None` | `None` | — |  |
| `llm_timeout_fast` | `float | None` | `None` | — |  |
| `llm_api_format_fast` | `str | None` | `None` | — |  |
| `llm_base_url_standard` | `str | None` | `None` | — |  |
| `llm_api_key_standard` | `str | None` | `None` | — |  |
| `llm_timeout_standard` | `float | None` | `None` | — |  |
| `llm_api_format_standard` | `str | None` | `None` | — |  |
| `llm_base_url_deep` | `str | None` | `None` | — |  |
| `llm_api_key_deep` | `str | None` | `None` | — |  |
| `llm_timeout_deep` | `float | None` | `None` | — |  |
| `llm_api_format_deep` | `str | None` | `None` | — |  |
| `llm_base_url_vision` | `str | None` | `None` | — |  |
| `llm_api_key_vision` | `str | None` | `None` | — |  |
| `llm_model_vision` | `str | None` | `None` | — |  |
| `llm_timeout_vision` | `float | None` | `None` | — |  |
| `llm_api_format_vision` | `str | None` | `None` | — |  |
| `llm_base_url_compute_use` | `str | None` | `None` | — |  |
| `llm_api_key_compute_use` | `str | None` | `None` | — |  |
| `llm_model_compute_use` | `str | None` | `None` | — |  |
| `llm_timeout_compute_use` | `float | None` | `None` | — |  |
| `llm_api_format_compute_use` | `str | None` | `None` | — |  |
| `llm_temperature_compute_use` | `float | None` | `None` | — |  |
| `llm_top_p_compute_use` | `float | None` | `None` | — |  |
| `llm_max_tokens_compute_use` | `int | None` | `None` | — |  |
| `llm_base_url_vision_fast` | `str | None` | `None` | — |  |
| `llm_api_key_vision_fast` | `str | None` | `None` | — |  |
| `llm_model_vision_fast` | `str | None` | `None` | — |  |
| `llm_timeout_vision_fast` | `float | None` | `None` | — |  |
| `llm_api_format_vision_fast` | `str | None` | `None` | — |  |
| `whisper_model_path` | `str` | `'whisper/ggml-tiny.en.bin'` | — |  |
| `offline_stt_enabled` | `bool` | `False` | — |  |
| `primary_stt` | `Literal['transformers', 'whisper', 'browser']` | `'transformers'` | — | BF-301 (was AD-826): which STT engine the UI PTT handler arms first. transformers = local @huggingface/transformers Whisper running in a Web Worker (cross-browser, no operator setup, default since BF-301). whisper = DEPRECATED alias for transformers — retained for back-compat with saved operator configs; resolves to engine='transformers' in the health endpoint. browser = Web Speech API (Chrome-only reliable; flaky on Edge/Firefox/Safari). When transformers is selected AND offline_stt_enabled is False, the UI honest-degrades to the browser engine. Hot-reload. |
| `transformers_model` | `str` | `'Xenova/whisper-tiny.en'` | — | BF-301: HuggingFace model id for the browser-side transformers.js ASR pipeline. Browser fetches and caches; the runtime never holds the weights. Hot-reload. |
| `fallback_stt_enabled` | `bool` | `True` | — | AD-826: when True, two consecutive empty transcripts from the primary STT engine fall through to the other engine for the next press. When False, the primary engine is the only path and empty transcripts are surfaced as-is. Hot-reload. |
| `conversation_mode_enabled` | `bool` | `False` | — | AD-747: when ON, opening a DM thread arms an always-on conversation. Default OFF; press-to-talk preserved. Hot-reload. |
| `conversation_silence_timeout_ms` | `int` | `30000` | ≥ 1000, ≤ 300000 | AD-747: silence-timeout in ms after the agent's TTS reply finishes; expiry disarms the conversation and returns to wake-word. 30000 matches ChatGPT advanced voice mode. Hot-reload. |
| `conversation_barge_in_enabled` | `bool` | `True` | — | AD-747: when ON, VAD speech_start during agent_speaking stops the TTS mid-utterance and re-arms STT. Operators in noisy environments can disable; AD-747-1 forward marker for prosody-gated barge-in. Hot-reload. |
| `llm_base_url_image_gen` | `str | None` | `None` | — |  |
| `llm_api_key_image_gen` | `str | None` | `None` | — |  |
| `llm_model_image_gen` | `str | None` | `None` | — |  |
| `llm_timeout_image_gen` | `float | None` | `None` | — |  |
| `llm_api_format_image_gen` | `str | None` | `None` | — |  |
| `llm_temperature_fast` | `float | None` | `None` | — |  |
| `llm_temperature_standard` | `float | None` | `None` | — |  |
| `llm_temperature_deep` | `float | None` | `None` | — |  |
| `llm_temperature_vision` | `float | None` | `None` | — |  |
| `llm_top_p_fast` | `float | None` | `None` | — |  |
| `llm_top_p_standard` | `float | None` | `None` | — |  |
| `llm_top_p_deep` | `float | None` | `None` | — |  |
| `llm_top_p_vision` | `float | None` | `None` | — |  |
| `llm_max_tokens_fast` | `int | None` | `None` | — |  |
| `llm_max_tokens_standard` | `int | None` | `None` | — |  |
| `llm_max_tokens_deep` | `int | None` | `None` | — |  |
| `llm_max_tokens_vision` | `int | None` | `None` | — |  |
| `llm_system_prompt_suffix_fast` | `str | None` | `None` | — |  |
| `llm_system_prompt_suffix_standard` | `str | None` | `None` | — |  |
| `llm_system_prompt_suffix_deep` | `str | None` | `None` | — |  |
| `llm_system_prompt_suffix_vision` | `str | None` | `None` | — |  |
| `default_llm_tier` | `str` | `'fast'` | — |  |
| `ollama_keep_alive` | `str` | `'30m'` | — |  |
| `working_memory_token_budget` | `int` | `4000` | — |  |
| `decomposition_timeout_seconds` | `float` | `30.0` | — |  |
| `dag_execution_timeout_seconds` | `float` | `60.0` | — |  |
| `use_consensus_for_writes` | `bool` | `True` | — |  |
| `max_concurrent_tasks` | `int` | `8` | — |  |
| `deferred_capability_threshold` | `int` | `0` | — |  |
| `attention_decay_rate` | `float` | `0.95` | — |  |
| `focus_history_size` | `int` | `10` | — |  |
| `background_demotion_factor` | `float` | `0.25` | — |  |
| `captain_card_enabled` | `bool` | `True` | — | AD-739: inject the Captain Card into CognitiveAgent system prompts. Default ON — the Card is a benign context anchor. |
| `captain_card_path` | `str` | `'captain_card.json'` | — | AD-739: relative path under runtime.data_dir for the Captain Card JSON sidecar. |
| `captain_card_max_tokens` | `int` | `500` | ≥ 100, ≤ 1500 | AD-739: token budget for the rendered Card text injected into system prompts. Approximated as max chars / 4. |
| `captain_card_refresh_min_interval_seconds` | `int` | `3600` | ≥ 60 | AD-739: minimum interval between Dreaming-driven Card refreshes. |
| `artifact_fenced_threshold_lines` | `int` | `40` | ≥ 10 | AD-797: fenced code block line-count threshold for artifact extraction. Blocks shorter than this stay inline. |

## `memory`

Episodic memory configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `collection_name` | `str` | `'probos_episodes'` | — |  |
| `max_episodes` | `int` | `100000` | — |  |
| `access_policy` | `str` | `'permissive'` | — |  |
| `relevance_threshold` | `float` | `0.7` | — |  |
| `agent_recall_threshold` | `float` | `0.25` | — |  |
| `fts_keyword_semantic_floor` | `float` | `0.2` | — |  |
| `embedding_model` | `str` | `'multi-qa-MiniLM-L6-cos-v1'` | — |  |
| `query_reformulation_enabled` | `bool` | `True` | — |  |
| `similarity_threshold` | `float` | `0.6` | — |  |
| `verify_content_hash` | `bool` | `True` | — |  |
| `eviction_audit_enabled` | `bool` | `True` | — |  |
| `shutdown_consolidation_timeout_s` | `float` | `30.0` | — |  |
| `migration_timeout_s` | `float` | `300.0` | ≥ 10.0, ≤ 3600.0 | BF-295 (#748): per-migration timeout in seconds for episodic-memory startup migrations. Stuck migrations honest-degrade after this ceiling. Default 300s; range 10s–3600s. |
| `schema_version_tracking` | `bool` | `False` | — |  |
| `oracle_match_reason_enabled` | `bool` | `False` | — |  |
| `shutdown_drain_timeout_s` | `float` | `30.0` | ≥ 1.0, ≤ 300.0 | AD-825: max seconds to wait for write-holding tasks (dreaming, consolidation, episodic backup) to finish current operation before falling through to AD-824 cancel sweep. |
| `hnsw_sync_threshold` | `int` | `64` | ≥ 4, ≤ 10000 |  |
| `hnsw_batch_size` | `int` | `32` | ≥ 1, ≤ 10000 |  |
| `backup_enabled` | `bool` | `True` | — |  |
| `backup_retain_days` | `int` | `7` | ≥ 1, ≤ 365 |  |
| `recall_weights` | `dict[str, float]` | `{'semantic': 0.35, 'keyword': 0.2, 'trust': 0.1, 'hebbian': 0.05, 'recency': 0.15, 'anchor': 0.15}` | — |  |
| `recall_convergence_bonus` | `float` | `0.1` | — |  |
| `recall_rerank_enabled` | `bool` | `False` | — |  |
| `recall_rerank_weights` | `dict[str, float]` | `{'strength': 1.0, 'recency': 0.5, 'importance': 0.5, 'affect': 0.0}` | — |  |
| `affect_capture_enabled` | `bool` | `False` | — |  |
| `recall_temporal_match_weight` | `float` | `0.25` | — |  |
| `recall_temporal_mismatch_penalty` | `float` | `0.15` | — |  |
| `recall_confidence_weak_floor` | `float` | `0.45` | — |  |
| `hybrid_recall_enabled` | `bool` | `False` | — |  |
| `hybrid_rrf_k` | `int` | `60` | — |  |
| `recall_fok_logging_enabled` | `bool` | `False` | — |  |
| `remember_know_typing_enabled` | `bool` | `False` | — |  |
| `cross_agent_recall_enabled` | `bool` | `False` | — |  |
| `recall_confidence_gating_enabled` | `bool` | `False` | — |  |
| `reconsolidation_enabled` | `bool` | `False` | — |  |
| `transcript_grounded_recall_enabled` | `bool` | `False` | — |  |
| `transcript_grounding_max_threads` | `int` | `8` | — |  |
| `transcript_grounding_max_chars` | `int` | `1200` | — |  |
| `transcript_retention_days` | `int` | `0` | — |  |
| `transcript_reaper_interval_seconds` | `int` | `3600` | — |  |
| `group_episode_enrichment_enabled` | `bool` | `False` | — |  |
| `group_reflection_max_chars` | `int` | `600` | — |  |
| `episode_visual_binding_enabled` | `bool` | `False` | — |  |
| `recall_outcome_refs_enabled` | `bool` | `False` | — |  |
| `tcm_enabled` | `bool` | `True` | — |  |
| `tcm_dimension` | `int` | `16` | — |  |
| `tcm_drift_rate` | `float` | `0.95` | — |  |
| `tcm_weight` | `float` | `0.15` | — |  |
| `tcm_fallback_watch_weight` | `float` | `0.05` | — |  |
| `recall_context_budget_chars` | `int` | `4000` | — |  |
| `anchor_dimension_weights` | `dict[str, float]` | `{'temporal': 0.25, 'spatial': 0.25, 'social': 0.25, 'causal': 0.15, 'evidential': 0.1}` | — |  |
| `anchor_confidence_gate` | `float` | `0.3` | — |  |
| `composite_score_floor` | `float` | `0.35` | — |  |
| `max_recall_episodes` | `int` | `0` | — |  |
| `recall_quality_floor` | `float` | `0.4` | — |  |
| `recall_tiers` | `dict[str, dict[str, Any]]` | `{'basic': {'k': 3, 'context_budget': 1500, 'anchor_confidence_gate': 0.0, 'composite_score_floor': 0.0, 'max_recall_episodes': 0, 'recall_quality_floor': 0.0, 'use_salience_weights': False, 'cross_department_anchors': False}, 'enhanced': {'k': 5, 'context_budget': 4000, 'anchor_confidence_gate': 0.3, 'composite_score_floor': 0.35, 'max_recall_episodes': 0, 'recall_quality_floor': 0.4, 'use_salience_weights': True, 'cross_department_anchors': False}, 'full': {'k': 8, 'context_budget': 6000, 'anchor_confidence_gate': 0.3, 'composite_score_floor': 0.35, 'max_recall_episodes': 0, 'recall_quality_floor': 0.4, 'use_salience_weights': True, 'cross_department_anchors': True}, 'oracle': {'k': 10, 'context_budget': 8000, 'anchor_confidence_gate': 0.2, 'composite_score_floor': 0.0, 'max_recall_episodes': 0, 'recall_quality_floor': 0.0, 'use_salience_weights': True, 'cross_department_anchors': True}}` | — |  |

## `attention`

AD-1028: ContextAssembler / global token-budget configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `token_budget` | `int` | `120000` | ≥ 1000 |  |
| `salience_scoring` | `bool` | `False` | — |  |
| `w_rel` | `float` | `1.0` | ≥ 0.0 |  |
| `w_rec` | `float` | `0.5` | ≥ 0.0 |  |
| `w_imp` | `float` | `0.5` | ≥ 0.0 |  |
| `recency_half_life_seconds` | `float` | `86400.0` | > 0.0 |  |
| `camera_scene_bid_enabled` | `bool` | `True` | — |  |
| `camera_novelty_minimum` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 |  |
| `camera_novelty_ema_alpha` | `float` | `0.3` | > 0.0, ≤ 1.0 |  |
| `camera_recessive_suppress_threshold` | `float` | `0.15` | ≥ 0.0, ≤ 1.0 |  |
| `arousal_enabled` | `bool` | `False` | — |  |
| `arousal_red_budget_multiplier` | `float` | `0.5` | > 0.0, ≤ 1.0 |  |
| `arousal_full_decay_seconds` | `float` | `300.0` | > 0.0 |  |
| `arousal_repeat_window_seconds` | `float` | `60.0` | > 0.0 |  |

## `dreaming`

Dreaming / offline consolidation configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `organ_enabled` | `bool` | `False` | — |  |
| `idle_threshold_seconds` | `float` | `120.0` | — |  |
| `dream_interval_seconds` | `float` | `600.0` | — |  |
| `replay_episode_count` | `int` | `50` | — |  |
| `pathway_strengthening_factor` | `float` | `0.03` | — |  |
| `pathway_weakening_factor` | `float` | `0.02` | — |  |
| `prune_threshold` | `float` | `0.01` | — |  |
| `trust_boost` | `float` | `0.1` | — |  |
| `trust_penalty` | `float` | `0.1` | — |  |
| `pre_warm_top_k` | `int` | `5` | — |  |
| `notebook_consolidation_enabled` | `bool` | `True` | — |  |
| `notebook_consolidation_threshold` | `float` | `0.6` | — |  |
| `notebook_consolidation_min_entries` | `int` | `2` | — |  |
| `notebook_convergence_threshold` | `float` | `0.5` | — |  |
| `notebook_convergence_min_agents` | `int` | `3` | — |  |
| `notebook_convergence_min_departments` | `int` | `2` | — |  |
| `active_retrieval_enabled` | `bool` | `False` | — |  |
| `retrieval_episodes_per_cycle` | `int` | `3` | — |  |
| `retrieval_success_threshold` | `float` | `0.6` | — |  |
| `retrieval_partial_threshold` | `float` | `0.3` | — |  |
| `retrieval_initial_interval_hours` | `float` | `24.0` | — |  |
| `retrieval_max_interval_hours` | `float` | `168.0` | — |  |
| `retrieval_counselor_failure_streak` | `int` | `3` | — |  |
| `reminiscence_enabled` | `bool` | `True` | — |  |
| `reminiscence_episodes_per_session` | `int` | `3` | — |  |
| `reminiscence_concern_threshold` | `int` | `3` | — |  |
| `reminiscence_confabulation_alert` | `float` | `0.3` | — |  |
| `reminiscence_cooldown_hours` | `float` | `2.0` | — |  |
| `activation_enabled` | `bool` | `True` | — |  |
| `activation_decay_d` | `float` | `0.5` | — |  |
| `activation_prune_threshold` | `float` | `-2.0` | — |  |
| `activation_access_max_age_days` | `int` | `180` | — |  |
| `prune_min_age_hours` | `int` | `24` | — |  |
| `prune_max_fraction` | `float` | `0.1` | — |  |
| `reflection_enabled` | `bool` | `True` | — |  |
| `reflection_max_per_cycle` | `int` | `3` | — |  |
| `reflection_min_importance` | `int` | `8` | — |  |
| `per_agent_dream_attribution_enabled` | `bool` | `False` | — |  |
| `aggressive_prune_enabled` | `bool` | `True` | — |  |
| `aggressive_prune_min_age_hours` | `int` | `168` | — |  |
| `aggressive_prune_threshold` | `float` | `0.0` | — |  |
| `aggressive_prune_max_fraction` | `float` | `0.25` | — |  |
| `episode_pressure_threshold` | `int` | `5000` | — |  |
| `episode_pressure_multiplier` | `float` | `1.5` | — |  |
| `trace_exemplars_per_procedure` | `int` | `3` | — |  |
| `relationship_inference_enabled` | `bool` | `True` | — |  |
| `relationship_inference_max_pairs_per_run` | `int` | `50` | — |  |
| `relationship_inference_max_per_entity` | `int` | `5` | — |  |
| `relationship_inference_min_confidence` | `float` | `0.6` | — |  |

## `dream_wm`

AD-671: Dream-Working Memory bridge configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_priming_entries` | `int` | `3` | — |  |
| `flush_min_entries` | `int` | `5` | — |  |
| `priming_category` | `str` | `'observation'` | — |  |

## `scaling`

Adaptive pool scaling configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `scale_up_threshold` | `float` | `0.8` | — |  |
| `scale_down_threshold` | `float` | `0.2` | — |  |
| `scale_up_step` | `int` | `1` | — |  |
| `scale_down_step` | `int` | `1` | — |  |
| `cooldown_seconds` | `float` | `30.0` | — |  |
| `observation_window_seconds` | `float` | `60.0` | — |  |
| `idle_scale_down_seconds` | `float` | `120.0` | — |  |

## `federation`

Multi-node federation configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `node_id` | `str` | `'node-1'` | — |  |
| `bind_address` | `str` | `'tcp://127.0.0.1:5555'` | — |  |
| `peers` | `list[probos.config.PeerConfig]` | `[]` | — |  |
| `forward_timeout_ms` | `int` | `5000` | — |  |
| `gossip_interval_seconds` | `float` | `10.0` | — |  |
| `validate_remote_results` | `bool` | `True` | — |  |
| `memory_policy` | `str` | `'clean_room'` | — |  |
| `memory_policy_selective_tags` | `list[str]` | `[]` | — |  |
| `min_peer_trust_score` | `float` | `0.0` | — |  |
| `memory_access_policy` | `str` | `'shared_trust'` | — |  |
| `shared_trust_min_score` | `float` | `0.5` | ≥ 0.0, ≤ 1.0 |  |
| `dp_min_cohort_size` | `int` | `3` | ≥ 1 |  |

## `mcp_server`

AD-480a: Inbound MCP server — exposes ProbOS capabilities as MCP tools.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `bind_host` | `str` | `'127.0.0.1'` | — |  |
| `bind_port` | `int` | `8765` | ≥ 1, ≤ 65535 |  |
| `path_prefix` | `str` | `'/mcp'` | — |  |

## `a2a`

AD-480d / AD-480e: Inbound A2A server + outbound A2A clients.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `bind_host` | `str` | `'127.0.0.1'` | — |  |
| `bind_port` | `int` | `8766` | ≥ 1, ≤ 65535 |  |
| `agent_card_path` | `str` | `'/.well-known/agent.json'` | — |  |
| `outbound_peers` | `list[probos.config.A2APeerConfig]` | `[]` | — |  |

## `ard`

AD-1040: ARD (Agentic Resource Discovery) integration. Default-OFF.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `well_known_path` | `str` | `'/.well-known/ai-catalog.json'` | — |  |
| `discovery_endpoints` | `list[str]` | `[]` | — |  |
| `registry_url` | `str` | `''` | — |  |
| `publisher_namespace_domain` | `str` | `''` | — |  |
| `discovery_before_design` | `bool` | `False` | — |  |
| `federation_mode` | `Literal['none', 'referrals', 'auto']` | `'none'` | — |  |
| `max_referral_peers` | `int` | `5` | ≥ 0, ≤ 50 |  |

## `peer_trust`

AD-480g: Probationary trust prior for federated peers.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `probationary_alpha` | `float` | `1.0` | > 0.0 |  |
| `probationary_beta` | `float` | `3.0` | > 0.0 |  |

## `tls`

AD-479f: Federation TLS surface (NATS pass-through in v1).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `cert_file` | `str | None` | `None` | — |  |
| `key_file` | `str | None` | `None` | — |  |
| `ca_file` | `str | None` | `None` | — |  |
| `verify_peer` | `bool` | `True` | — |  |

## `discovery`

AD-479h: Multicast peer discovery (opt-in, default-False).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `multicast_enabled` | `bool` | `False` | — |  |
| `multicast_group` | `str` | `'239.255.42.99'` | — |  |
| `multicast_port` | `int` | `5556` | — |  |
| `announce_interval_seconds` | `float` | `5.0` | — |  |

## `cluster_monitor`

AD-479g: Cluster health monitor.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `peer_unreachable_seconds` | `float` | `60.0` | — |  |

## `self_mod`

Self-modification configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `require_user_approval` | `bool` | `True` | — |  |
| `probationary_alpha` | `float` | `1.0` | — |  |
| `probationary_beta` | `float` | `3.0` | — |  |
| `max_designed_agents` | `int` | `5` | — |  |
| `sandbox_timeout_seconds` | `float` | `60.0` | — |  |
| `allowed_imports` | `list[str]` | `['asyncio', 'pathlib', 'json', 'os', 're', 'datetime', 'typing', 'dataclasses', 'collections', 'math', 'hashlib', 'urllib.parse', 'base64', 'csv', 'io', 'tempfile']` | — |  |
| `forbidden_patterns` | `list[str]` | `['subprocess', 'shutil\\.rmtree', 'os\\.remove', 'os\\.unlink', 'eval\\s*\\(', 'exec\\s*\\(', '__import__', 'open\\s*\\(.*[\'\\"][waxWAX]', 'socket\\b', 'ctypes\\b', 'os\\.system', 'os\\.popen', 'os\\.exec', 'os\\.kill', '\\.write_text\\s*\\(', '\\.write_bytes\\s*\\(', '\\.unlink\\s*\\(', '__builtins__', 'compile\\s*\\(']` | — |  |
| `research_enabled` | `bool` | `False` | — |  |
| `research_domain_whitelist` | `list[str]` | `['docs.python.org', 'pypi.org', 'developer.mozilla.org', 'learn.microsoft.com']` | — |  |
| `research_max_pages` | `int` | `3` | — |  |
| `research_max_content_per_page` | `int` | `2000` | — |  |

## `device`

AD-843b: probationary Beta trust prior for paired devices (brain->limb tier).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `probationary_alpha` | `float` | `1.0` | > 0.0 |  |
| `probationary_beta` | `float` | `3.0` | > 0.0 |  |

## `os_activity`

AD-1054: consent gate for the desktop OS-activity sensor.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | Consent gate for the OS-activity sensor. Default OFF (no capture without consent). |
| `poll_interval_seconds` | `int` | `5` | ≥ 1, ≤ 60 | Heartbeat cadence (seconds) the desktop watcher reads to poll the active window. |

## `grounding`

AD-1119: consent/enable gate for the referent-grounding gate (guard G1).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `referent_gate_enabled` | `bool` | `False` | — | AD-1119: consent/enable gate for the referent-grounding gate. Default OFF (byte-identical when off). |
| `ground_before_collaborate_enabled` | `bool` | `False` | — | AD-1120: when True (and referent_gate_enabled is also True), inject the AD-1119 honest-absence cue for an unresolved CENTRAL room referent into each dispatched crew agent's context. Default OFF (injection path byte-identical when off; has no effect unless referent_gate_enabled is on). |
| `confab_probe_enabled` | `bool` | `False` | — | AD-1121: when True (and referent_gate_enabled is also True), run a context-free self-consistency divergence probe on an UNRESOLVED central room referent; on a divergence verdict, record a CASCADE_CONFAB observation and notify the Captain. Best-effort + non-blocking. Default OFF (byte-identical when off; no effect unless referent_gate_enabled is on). |

## `dependency`

AD-838c: Dynamic dependency installation for the task path.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `dynamic_install_enabled` | `bool` | `False` | — |  |
| `dynamic_install_policy` | `Literal['whitelist', 'prompt_unlisted']` | `'prompt_unlisted'` | — |  |
| `dynamic_install_deny` | `list[str]` | `[]` | — |  |
| `auto_approve_imports` | `list[str]` | `['asyncio', 'base64', 'calendar', 'collections', 'contextlib', 'copy', 'csv', 'dataclasses', 'datetime', 'decimal', 'difflib', 'enum', 'fnmatch', 'fractions', 'functools', 'glob', 'hashlib', 'html', 'io', 'itertools', 'json', 'logging', 'math', 'os', 'pathlib', 'pprint', 'random', 're', 'secrets', 'shutil', 'statistics', 'string', 'struct', 'sys', 'tempfile', 'textwrap', 'time', 'typing', 'urllib', 'uuid', 'xml']` | — | AD-1222: packages that install with no Captain prompt. Everything else files an install request (AD-1220). Stdlib-only by default: installing a third-party package is an authority grant and should be asked for, not inherited from the self-mod import allowlist. |

## `execution`

AD-993/994: governed ephemeral code execution (tiered isolation).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `default_tier` | `int` | `1` | — |  |
| `scratch_dir` | `str` | `'data/execution'` | — |  |
| `persistent_workspaces` | `bool` | `True` | — |  |
| `workspace_root` | `str` | `'data/execution/workspaces'` | — |  |
| `fetch_broker_enabled` | `bool` | `False` | — |  |
| `fetch_broker_max_body_bytes` | `int` | `8388608` | — |  |
| `workspace_write_enabled` | `bool` | `False` | — |  |
| `timeout_seconds` | `float` | `30.0` | — |  |
| `max_output_bytes` | `int` | `65536` | — |  |
| `max_memory_mb` | `int` | `512` | — |  |
| `stage_thread_artifacts` | `bool` | `False` | — |  |
| `max_staged_artifacts` | `int` | `20` | — |  |
| `allow_package_install` | `bool` | `False` | — |  |
| `pip_index_url` | `str` | `'https://pypi.org/simple'` | — |  |
| `install_timeout_seconds` | `float` | `180.0` | — |  |

## `hooks`

AD-1004: lifecycle-hook bus (deterministic interception at agent-loop     points — the VS Code / Claude / Copilot hook model).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |

## `packs`

AD-1003c: Capability Packs — installed-pack inventory directory.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `packs_dir` | `str` | `'data/packs'` | — |  |

## `skills_marketplace`

AD-813: remote skill/pack marketplace BROWSE (read-only, default-OFF).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `registry_url` | `str` | `''` | — |  |
| `timeout_seconds` | `float` | `10.0` | > 0, ≤ 60 |  |
| `max_bytes` | `int` | `2000000` | > 0 |  |
| `max_results` | `int` | `100` | ≥ 1, ≤ 1000 |  |
| `default_page_size` | `int` | `20` | ≥ 1, ≤ 100 |  |

## `workstations`

AD-1022: HXI workstation-type surface (Experience layer).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |

## `qa`

SystemQAAgent configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `smoke_test_count` | `int` | `5` | — |  |
| `timeout_per_test_seconds` | `float` | `10.0` | — |  |
| `total_timeout_seconds` | `float` | `30.0` | — |  |
| `pass_threshold` | `float` | `0.6` | — |  |
| `trust_reward_weight` | `float` | `1.0` | — |  |
| `trust_penalty_weight` | `float` | `2.0` | — |  |
| `flag_on_fail` | `bool` | `True` | — |  |
| `auto_remove_on_total_fail` | `bool` | `False` | — |  |

## `knowledge`

Persistent knowledge store configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `repo_path` | `str` | `''` | — |  |
| `auto_commit` | `bool` | `True` | — |  |
| `commit_debounce_seconds` | `float` | `5.0` | — |  |
| `max_episodes` | `int` | `1000` | — |  |
| `max_workflows` | `int` | `200` | — |  |
| `restore_on_boot` | `bool` | `True` | — |  |

## `records`

Ship's Records — the durable, classified, cross-session knowledge commons (Nooplex Σ). Distinct from an agent's sovereign episodic shard (Nooplex A), which lives behind a different filter.

Ship's Records configuration (AD-434).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `repo_path` | `str` | `''` | — |  |
| `auto_commit` | `bool` | `True` | — |  |
| `commit_debounce_seconds` | `float` | `5.0` | — |  |
| `max_episodes_per_hour` | `int` | `20` | — |  |
| `notebook_dedup_enabled` | `bool` | `True` | — |  |
| `notebook_similarity_threshold` | `float` | `0.8` | — |  |
| `notebook_staleness_hours` | `float` | `72.0` | — |  |
| `notebook_max_scan_entries` | `int` | `20` | — |  |
| `notebook_repetition_enabled` | `bool` | `True` | — |  |
| `notebook_repetition_window_hours` | `float` | `48.0` | — |  |
| `notebook_repetition_threshold_count` | `int` | `3` | — |  |
| `notebook_repetition_novelty_threshold` | `float` | `0.2` | — |  |
| `notebook_repetition_suppression_count` | `int` | `5` | — |  |
| `notebook_metrics_enabled` | `bool` | `True` | — |  |
| `realtime_convergence_enabled` | `bool` | `True` | — |  |
| `realtime_convergence_threshold` | `float` | `0.5` | — |  |
| `realtime_divergence_threshold` | `float` | `0.3` | — |  |
| `realtime_convergence_staleness_hours` | `float` | `72.0` | — |  |
| `realtime_max_scan_per_agent` | `int` | `5` | — |  |
| `realtime_min_convergence_agents` | `int` | `2` | — |  |
| `realtime_min_convergence_departments` | `int` | `2` | — |  |
| `convergence_independence_threshold` | `float` | `0.3` | — |  |
| `notebook_quality_enabled` | `bool` | `True` | — |  |
| `notebook_quality_low_threshold` | `float` | `0.3` | — |  |
| `notebook_quality_warn_threshold` | `float` | `0.5` | — |  |
| `notebook_staleness_alert_rate` | `float` | `0.7` | — |  |
| `semantic_index_enabled` | `bool` | `False` | — |  |

## `archive`

Ship's Archive configuration (AD-524).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `db_path` | `str` | `''` | — |  |

## `telemetry`

Ship's Telemetry configuration (AD-461).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `report_interval_seconds` | `float` | `60.0` | — |  |
| `max_samples_per_bucket` | `int` | `1000` | — |  |

## `post_budget_telemetry`

BF-238: Post-budget exhaustion telemetry configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `exhaustion_alert_threshold` | `float` | `0.5` | — |  |
| `min_samples_for_alert` | `int` | `10` | — |  |
| `recent_suppressions_max` | `int` | `100` | — |  |

## `confidence`

AD-444: Knowledge confidence scoring configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_confidence` | `float` | `0.5` | — |  |
| `confirm_delta` | `float` | `0.15` | — |  |
| `contradict_delta` | `float` | `0.25` | — |  |
| `auto_supersede_threshold` | `float` | `0.1` | — |  |
| `auto_apply_threshold` | `float` | `0.8` | — |  |
| `suppress_threshold` | `float` | `0.5` | — |  |

## `lint`

AD-563: Knowledge linting configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_coverage_per_department` | `int` | `5` | — |  |
| `inconsistency_keywords` | `dict[str, str]` | `{'increased': 'decreased', 'improved': 'degraded', 'rising': 'falling', 'positive': 'negative', 'success': 'failure'}` | — |  |

## `quality_trigger`

AD-564: Quality-triggered forced consolidation configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_quality_threshold` | `float` | `0.4` | — |  |
| `max_stale_rate` | `float` | `0.3` | — |  |
| `max_repetition_rate` | `float` | `0.2` | — |  |
| `cooldown_seconds` | `float` | `1800.0` | — |  |
| `max_forced_per_day` | `int` | `5` | — |  |

## `quality_router`

AD-565: Quality-informed routing configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_weight` | `float` | `0.5` | — |  |
| `max_weight` | `float` | `1.5` | — |  |
| `concern_threshold` | `float` | `0.3` | — |  |

## `onboarding`

AD-442: Onboarding ceremony configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `activation_trust_threshold` | `float` | `0.65` | — |  |
| `naming_ceremony` | `bool` | `True` | — |  |

## `holodeck_birth_chamber`

AD-486: Holodeck Birth Chamber — graduated cognitive onboarding.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `bypass_for_existing_agents` | `bool` | `True` | — |  |
| `department_order` | `list[str]` | `['security', 'operations', 'engineering', 'science', 'medical']` | — |  |
| `calibration_min_episodes` | `int` | `5` | ≥ 1 |  |
| `affective_baseline_check_enabled` | `bool` | `True` | — |  |
| `auto_advance_enabled` | `bool` | `True` | — |  |
| `auto_advance_poll_interval_seconds` | `float` | `2.0` | ≥ 0.1, ≤ 30.0 |  |
| `max_self_discovery_probe_attempts` | `int` | `3` | ≥ 1 |  |

## `holodeck_scenarios`

AD-539b: Holodeck scenario generation from skill gaps.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `auto_register_with_harness` | `bool` | `True` | — |  |
| `default_threshold` | `float` | `0.6` | ≥ 0.0, ≤ 1.0 |  |
| `default_tier` | `int` | `2` | ≥ 1, ≤ 3 |  |
| `category_fallback` | `str` | `'construction'` | — |  |
| `persist_to_sqlite` | `bool` | `False` | — |  |
| `data_subdir` | `str` | `'holodeck_scenarios'` | — |  |

## `team_simulations`

AD-510: Holodeck team simulations — group discovery & collaboration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `auto_register_with_harness` | `bool` | `True` | — |  |
| `default_threshold` | `float` | `0.6` | ≥ 0.0, ≤ 1.0 |  |
| `default_tier` | `int` | `2` | ≥ 1, ≤ 3 |  |
| `enforce_required_departments` | `bool` | `True` | — |  |
| `persist_to_sqlite` | `bool` | `False` | — |  |
| `data_subdir` | `str` | `'team_simulations'` | — |  |

## `skill_requests`

AD-906: Crew skill-acquisition request queue.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `data_subdir` | `str` | `'skill_requests'` | — |  |

## `naming`

Ship & crew naming conventions (AD-499).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `captain_ship_override` | `str` | `''` | — |  |
| `extra_banned_words` | `list[str]` | `[]` | — |  |

## `runtime_overrides`

Runtime override layer configuration (AD-468).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `store_filename` | `str` | `'runtime_overrides.json'` | — |  |

## `utility_agents`

Utility agent suite configuration (AD-252).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `swe_specialists`

AD-476 v1 — opt-in pool registration for the five SWE specialists.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `pool_size_per_specialty` | `int` | `1` | — |  |
| `model_tier_overrides` | `dict[str, str]` | `{'backend': 'deep', 'frontend': 'standard', 'test': 'fast', 'infrastructure': 'standard', 'data': 'deep'}` | — |  |

## `native_swe_harness`

AD-549: Configuration for the native SWE agentic harness.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | Master gate. When False, builds route to existing native/visiting paths. |
| `eligibility_modify_only` | `bool` | `True` | — | Phase α default. Only modify-only builds (all targets exist) eligible. |
| `max_iterations` | `int` | `25` | ≥ 1, ≤ 200 |  |
| `max_fix_iterations` | `int` | `5` | ≥ 1, ≤ 20 |  |
| `token_budget` | `int | None` | `None` | ≥ 1024 |  |
| `compaction_threshold_pct` | `float` | `0.8` | ≥ 0.1, ≤ 0.95 |  |
| `blocked_paths` | `list[str]` | `['src/probos/security/', '.env', 'config/sealed_modules.yaml']` | — | AD-548: Pre-hook denies tool calls touching these path substrings. |

## `agentic_loop`

Conversation mechanics for the agentic loop. `tool_result_max_chars` is the one to look at first: it ships at `0`, meaning **unbounded**, and `max_iterations` bounds turns rather than bytes — so a single large tool result can exhaust the context window.

AD-1146: configuration shared by every ``AgenticLoop``.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `structured_tool_messages` | `bool` | `False` | — | AD-1146: emit the provider's real multi-turn message array (assistant.tool_calls + role:'tool' results keyed by tool_call_id) instead of flattening the transcript into one prompt string. Default-OFF per convention #14 — the flattened AD-545 path stays byte-identical until the operator opts in. |
| `tool_result_max_chars` | `int` | `0` | ≥ 0 | AD-1148: maximum characters of a single tool result allowed into the loop's message history. 0 = unbounded (default-OFF), which keeps message content byte-identical. Applies to both the legacy flattened path and the AD-1146 structured path, and to error results. The durable tool trace is unaffected — bounding is a working-context concern only. |
| `tool_result_head_chars` | `int` | `4000` | ≥ 0 | AD-1148: characters kept from the START of a bounded tool result. Mirrors TOOL_RESULT_HEAD_CHARS in swe_harness/agentic_loop.py. Head and tail are both preserved because many tools print their header first and their summary line last. Shrunk proportionally when tool_result_max_chars cannot hold head + tail + the elision marker. Only consulted once tool_result_max_chars is non-zero. |
| `tool_result_tail_chars` | `int` | `2000` | ≥ 0 | AD-1148: characters kept from the END of a bounded tool result. Mirrors TOOL_RESULT_TAIL_CHARS in swe_harness/agentic_loop.py. Only consulted once tool_result_max_chars is non-zero. |
| `parallel_tool_calls_enabled` | `bool` | `False` | — | AD-1147: execute the read-only tool calls from a single LLM response concurrently instead of one at a time. Default-OFF per convention #14 — the AD-545 sequential loop stays byte-identical until the operator opts in. Only tool ids on the PARALLEL_SAFE_TOOL_IDS allowlist in swe_harness/agentic_loop.py ever run concurrently; mutating tools and unrecognised tool ids stay sequential. That allowlist is deliberately NOT configurable — it is a safety property, not a tuning knob. |
| `max_parallel_tool_calls` | `int` | `3` | ≥ 1, ≤ 16 | AD-1147: ceiling on concurrently in-flight tool calls within one LLM response. Mirrors PARALLEL_TOOL_CALLS_DEFAULT / PARALLEL_TOOL_CALLS_MAX in swe_harness/agentic_loop.py and the AgenticDispatchConfig.max_parallel_subtasks default — fan-out is a Safety Budget concern, so it is bounded rather than unlimited. Only consulted once parallel_tool_calls_enabled is True. |
| `tool_trace_output_max_chars` | `int` | `8192` | ≥ 0 | AD-1151: maximum characters of a single tool OUTPUT persisted into the durable tool trace. 0 = do not persist outputs at all, which yields a blob byte-identical to the pre-AD-1151 trace. Mirrors TOOL_TRACE_OUTPUT_MAX_CHARS in swe_harness/agentic_loop.py. The durable head/tail split is derived from THIS cap (2:1, the AD-1148 ratio), not from tool_result_head_chars / tool_result_tail_chars, so raising this value really does retain more. resolve_tool_trace_bounds clamps the effective value UP to tool_result_max_chars when a non-zero context cap exceeds it, so the trace is never bounded tighter than the transcript the model already saw. The clamp is skipped when this field is 0, which stays an explicit opt-out rather than being silently re-enabled. HONEST SCOPE: this closes the gap only against a BOUNDED context. tool_result_max_chars ships at 0 (unbounded), and no finite durable cap can retain more than an unbounded transcript — so on the shipped defaults the trace still records LESS than the model saw. What it does guarantee is that the output survives the conversation at all, which is what did not happen before. DEFAULT-ON: an explicit, documented carve-out from convention #14 (default-OFF on transitional flags), granted on the same grounds as warm_boot.enabled — an audit trail that is off by default does not audit. The carve-out is NOT precedent for a non-guarantee feature: the cost is bounded by tool_trace_max_bytes and the array shape plus every legacy key are preserved either way, so nothing breaks when it is on. |
| `tool_trace_max_bytes` | `int` | `262144` | ≥ 0 | AD-1151: ceiling on the whole encoded tool-trace blob, in bytes (256 KiB). 0 = no total cap. Mirrors TOOL_TRACE_MAX_BYTES in swe_harness/agentic_loop.py. Deliberately conservative against the 5 GiB attachments.max_store_bytes default: AttachmentStore.write can raise AttachmentStoreFullError, which honest-degrades the WHOLE trace to None, call records included — so a smaller blob protects the request records this AD must not regress. When the cap binds, later outputs are elided whole and marked; call records are never dropped. |

## `ward_room`

Ward Room communication fabric configuration (AD-407).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `max_agent_rounds` | `int` | `5` | — |  |
| `agent_cooldown_seconds` | `float` | `45` | — |  |
| `max_thread_posts` | `int` | `50` | — |  |
| `default_discuss_responder_cap` | `int` | `3` | — |  |
| `retention_days` | `int` | `7` | — |  |
| `retention_days_endorsed` | `int` | `30` | — |  |
| `retention_days_captain` | `int` | `0` | — |  |
| `archive_enabled` | `bool` | `True` | — |  |
| `prune_interval_seconds` | `float` | `86400.0` | — |  |
| `dm_exchange_limit` | `int` | `15` | — |  |
| `dm_similarity_threshold` | `float` | `0.6` | — |  |
| `router_concurrency_limit` | `int` | `10` | — |  |
| `event_coalesce_ms` | `int` | `200` | — |  |
| `dm_response_budget` | `int` | `6` | — |  |
| `dm_response_window_seconds` | `float` | `600.0` | — |  |
| `dm_pair_exchange_budget` | `int` | `8` | — |  |

## `group_chat`

AD-915: ad-hoc group-chat turn-taking facilitator.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `max_speakers_per_turn` | `int` | `0` | — |  |
| `convergence_enabled` | `bool` | `True` | — |  |
| `convergence_similarity_threshold` | `float` | `0.6` | — |  |
| `convergence_min_messages` | `int` | `4` | — |  |
| `convergence_min_agents` | `int` | `2` | — |  |
| `weight_mention` | `float` | `0.4` | — |  |
| `weight_recency` | `float` | `0.25` | — |  |
| `weight_department` | `float` | `0.25` | — |  |
| `weight_trust` | `float` | `0.1` | — |  |
| `weight_exploration` | `float` | `0.0` | — |  |
| `conversation_trust_enabled` | `bool` | `False` | — |  |
| `conversation_trust_positive_weight` | `float` | `0.05` | — |  |
| `conversation_trust_negative_weight` | `float` | `0.15` | — |  |
| `conversation_trust_max_outcomes` | `int` | `4` | — |  |
| `conversation_trust_correction_observe_enabled` | `bool` | `False` | — |  |
| `agent_create_cooldown_seconds` | `float` | `60.0` | — |  |
| `agent_create_max_per_window` | `int` | `5` | — |  |
| `agent_create_window_seconds` | `float` | `3600.0` | — |  |
| `auto_task_room_enabled` | `bool` | `False` | — |  |
| `agent_reactivity_enabled` | `bool` | `False` | — |  |
| `max_agent_rounds` | `int` | `2` | — |  |
| `agent_next_speaker_selection_enabled` | `bool` | `False` | — |  |
| `max_address_extensions` | `int` | `1` | — |  |
| `agent_initiated_kickoff_enabled` | `bool` | `False` | — |  |
| `escalation_suggestion_enabled` | `bool` | `False` | — |  |
| `escalation_min_crew` | `int` | `3` | — |  |
| `escalation_min_posts` | `int` | `6` | — |  |
| `broadcast_terminator_enabled` | `bool` | `False` | — |  |
| `turn_mode_policy_enabled` | `bool` | `False` | — |  |
| `broadcast_weight_mention` | `float` | `0.2` | — |  |
| `broadcast_weight_recency` | `float` | `0.15` | — |  |
| `broadcast_weight_department` | `float` | `0.5` | — |  |
| `broadcast_weight_trust` | `float` | `0.1` | — |  |
| `scale_aware_facilitation_enabled` | `bool` | `False` | — |  |
| `facilitation_gate_threshold` | `int` | `5` | ≥ 2 |  |
| `force_facilitation_min` | `int` | `0` | ≥ 0 |  |

## `visiting_officers`

AD-701: Visiting officer registry tunables.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `session_ttl_seconds` | `float` | `3600.0` | > 0.0 |  |
| `sweep_interval_seconds` | `float` | `60.0` | > 0.0 |  |
| `default_capabilities` | `list[str]` | `['ward_room.post', 'ward_room.read']` | — |  |

## `workflow_cron`

AD-707: Workflow cron-trigger scheduler configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `db_path` | `str` | `''` | — |  |
| `tick_interval_seconds` | `float` | `1.0` | > 0.0 |  |
| `initial_triggers` | `list[dict[str, str]]` | `[]` | — |  |

## `query_planner`

Memvid pattern 1: relational query routing for the recall pipeline.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `fall_through_on_empty` | `bool` | `True` | — |  |

## `assignments`

Dynamic assignment groups configuration (AD-408).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |

## `bridge_alerts`

Bridge Alerts — proactive Captain & crew notifications (AD-410).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `cooldown_seconds` | `float` | `300` | — |  |
| `trust_drop_threshold` | `float` | `0.15` | — |  |
| `trust_drop_alert_threshold` | `float` | `0.25` | — |  |
| `resolve_clean_period` | `float` | `3600.0` | — |  |
| `default_dismiss_duration` | `float` | `14400.0` | — |  |

## `firewall`

AD-529: Communication Contagion Firewall configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `scan_trust_threshold` | `float` | `0.65` | — |  |
| `low_trust_threshold` | `float` | `0.45` | — |  |
| `hex_id_min_length` | `int` | `6` | — |  |
| `hex_id_threshold` | `int` | `2` | — |  |
| `fabricated_metrics_threshold` | `int` | `3` | — |  |
| `flag_window_seconds` | `float` | `3600.0` | — |  |
| `quarantine_threshold` | `int` | `3` | — |  |

## `security`

Security Team configuration (AD-455).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_payload_bytes` | `int` | `65536` | ≥ 1024 |  |
| `rate_window_seconds` | `float` | `60.0` | ≥ 1.0 |  |
| `rate_max_requests` | `int` | `60` | ≥ 1 |  |
| `max_threat_severity` | `float` | `0.8` | ≥ 0.0, ≤ 1.0 |  |
| `burst_window_seconds` | `float` | `60.0` | ≥ 1.0 |  |
| `burst_threshold` | `int` | `20` | ≥ 2 |  |
| `campaign_interval_seconds` | `float` | `3600.0` | ≥ 60.0 |  |
| `profile` | `Literal['strict', 'relaxed']` | `'strict'` | — |  |
| `permission_mode` | `Literal['manual', 'autopilot']` | `'manual'` | — |  |
| `policy_engine_class` | `str` | `'NullPolicyEngine'` | — |  |

## `permissions`

AD-711: declarative permission lists (enforcement deferred to AD-711-1).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `allow` | `list[str]` | `[]` | — |  |
| `deny` | `list[str]` | `[]` | — |  |

## `auth`

AD-722b-1: minimal crew-scope authentication.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `crew_scope_token` | `str` | `''` | — | Shared bearer token for crew-scope auth on telemetry surfaces. Empty string disables auth. Set via config/system.yaml to opt in. |

## `emergent_detector`

BF-124: Emergent detector calibration parameters.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `cluster_edge_threshold` | `float` | `0.3` | — |  |
| `cluster_min_size` | `int` | `3` | — |  |
| `cluster_min_avg_weight` | `float` | `0.25` | — |  |
| `cluster_cooldown_seconds` | `float` | `1800.0` | — |  |
| `cluster_activity_window` | `float` | `900.0` | — |  |
| `dream_min_history` | `int` | `5` | — |  |
| `dream_anomaly_min_strengthened` | `int` | `10` | — |  |
| `dream_anomaly_min_pruned` | `int` | `5` | — |  |
| `dream_anomaly_min_trust_adj` | `int` | `10` | — |  |
| `adaptive_window_size` | `int` | `30` | — |  |
| `adaptive_z_threshold` | `float` | `2.5` | — |  |
| `adaptive_debounce_count` | `int` | `2` | — |  |
| `adaptive_min_history` | `int` | `8` | — |  |

## `emergence_collector`

AD-454: EvidenceCollector — research opt-in, default disabled.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `confidence_threshold` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 |  |
| `dedup_window_seconds` | `float` | `600.0` | ≥ 0.0 |  |
| `output_dir` | `str` | `'data/research/emergence-evidence'` | — |  |
| `llm_tier` | `str` | `'fast'` | — |  |
| `trial_id` | `str` | `'default'` | — |  |
| `thread_context_limit` | `int` | `5` | ≥ 0, ≤ 50 |  |
| `max_reasoning_chars` | `int` | `2000` | ≥ 100, ≤ 20000 |  |

## `novelty_gate`

AD-493: Semantic novelty gate — suppress rehashed observations.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `similarity_threshold` | `float` | `0.82` | — |  |
| `max_fingerprints_per_agent` | `int` | `50` | — |  |
| `decay_hours` | `float` | `24.0` | — |  |
| `min_text_length` | `int` | `80` | — |  |

## `earned_agency`

Earned Agency — trust-tiered behavioral gating (AD-357).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `initiative_trust_thresholds` | `dict[str, float]` | `{'responsive': 0.3, 'contributory': 0.5, 'proactive': 0.7}` | — |  |

## `duty_schedule`

Captain-configured work-hours/quiet-hours policy for proactive scans.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `scan_throttle_sec` | `dict[str, int]` | `{'inbox': 300, 'calendar': 600, 'teams': 900}` | — |  |
| `daily_briefing_time` | `str` | `'08:00'` | — |  |
| `briefing_reminder_throttle_sec` | `int` | `3600` | — |  |

## `work_hours`

Time window policy definition used for proactive scheduling.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `start_time` | `str` | `'08:00'` | — |  |
| `end_time` | `str` | `'18:00'` | — |  |
| `days` | `list[int]` | `[0, 1, 2, 3, 4]` | — |  |

## `quiet_hours`

Time window policy definition used for proactive scheduling.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `start_time` | `str` | `'08:00'` | — |  |
| `end_time` | `str` | `'18:00'` | — |  |
| `days` | `list[int]` | `[0, 1, 2, 3, 4]` | — |  |

## `proactive_cognitive`

Proactive Cognitive Loop — periodic idle-think (Phase 28b).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `interval_seconds` | `float` | `120.0` | — |  |
| `cooldown_seconds` | `float` | `300.0` | — |  |
| `trust_reward_weight` | `float` | `0.1` | — |  |
| `trust_no_response_weight` | `float` | `0.0` | — |  |
| `trust_duty_bonus` | `float` | `0.1` | — |  |
| `stagger_enabled` | `bool` | `True` | — |  |
| `min_stagger_seconds` | `float` | `5.0` | — |  |
| `yeoman_digest_window_seconds` | `float` | `60.0` | — |  |

## `proactive_scan`

AD-763: scoping config for proactive scans (folders, calendars, filters).

## `inbox`

AD-763: per-operator scoping of the inbox proactive scan.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `folders` | `list[str]` | `['Inbox']` | — | Graph mail folder IDs (or 'Inbox' alias) to include in scans. |
| `lookback_hours` | `int` | `24` | ≥ 1, ≤ 336 | Window (hours) to query backward from now. |
| `importance_filter` | `Literal['any', 'high']` | `'any'` | — | 'any' includes all importance levels; 'high' restricts to high-importance only. |
| `unread_only` | `bool` | `False` | — | If True, only unread messages are surfaced. |
| `sender_allowlist` | `list[str]` | `[]` | — | Email addresses or domains (e.g. '@acme.com'). Empty = no allow filter. |
| `sender_denylist` | `list[str]` | `[]` | — | Email addresses or domains. Senders matching are dropped post-fetch. |

## `calendar`

AD-763: per-operator scoping of the calendar proactive scan.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `calendar_ids` | `list[str]` | `['primary']` | — | Graph calendar IDs ('primary' alias resolves to default calendar). |
| `lookahead_hours` | `int` | `24` | ≥ 1, ≤ 720 | Window (hours) to query forward from now. |
| `include_declined` | `bool` | `False` | — | If True, events the operator has declined are still surfaced. |

## `persistent_tasks`

Persistent Task Engine — SQLite-backed scheduled tasks (Phase 25a).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `tick_interval_seconds` | `float` | `5.0` | — |  |
| `max_concurrent_executions` | `int` | `1` | — |  |
| `dag_auto_resume` | `bool` | `False` | — |  |

## `channels`

Channel adapter configurations.

## `discord`

Discord bot adapter configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `token` | `str` | `''` | — |  |
| `allowed_channel_ids` | `list[int]` | `[]` | — |  |
| `allowed_user_ids` | `list[int]` | `[]` | — |  |
| `command_prefix` | `str` | `'!'` | — |  |
| `mention_required` | `bool` | `False` | — |  |
| `scout_channel_id` | `int` | `0` | — |  |

## `slack`

Slack adapter configuration (AD-472 + AD-804).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `bot_token` | `str` | `''` | — |  |
| `signing_secret` | `str` | `''` | — |  |
| `allowed_channel_ids` | `list[str]` | `[]` | — |  |
| `allowed_user_ids` | `list[str]` | `[]` | — |  |
| `default_thread_ts` | `bool` | `True` | — |  |
| `channels` | `list[str]` | `[]` | — |  |
| `poll_interval_s` | `float` | `8.0` | — |  |
| `poll_inbound` | `bool` | `True` | — |  |
| `api_base` | `str` | `'https://slack.com/api'` | — |  |

## `webhook`

Webhook adapter configuration (AD-472).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `shared_secret` | `str` | `''` | — |  |
| `allowed_channels` | `list[str]` | `[]` | — |  |

## `m365`

AD-749: Microsoft 365 integration configuration.          OSS (personal): single-user OAuth device-code flow with local token caching.     Commercial: multi-tenant SSO + enterprise policy extensions (not in OSS).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `client_id` | `str | None` | `None` | — |  |
| `authority` | `str` | `'https://login.microsoftonline.com/common'` | — |  |
| `scopes` | `list[str]` | `['https://graph.microsoft.com/.default']` | — |  |
| `cache_dir` | `str` | `'~/.probos/m365_cache'` | — |  |

## `office_skills`

AD-755: Local office-document skills and template registry config.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `template_dir` | `str` | `'~/.probos/templates'` | — |  |
| `output_dir` | `str` | `'~/.probos/output'` | — |  |

## `medical`

Medical team pool configuration (AD-290).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `vitals_interval_seconds` | `float` | `5.0` | — |  |
| `vitals_window_size` | `int` | `12` | — |  |
| `pool_health_min` | `float` | `0.5` | — |  |
| `trust_floor` | `float` | `0.3` | — |  |
| `health_floor` | `float` | `0.6` | — |  |
| `max_trust_outliers` | `int` | `3` | — |  |
| `scheduled_diagnosis_interval` | `float` | `300.0` | — |  |

## `counselor`

Counselor cognitive wellness configuration (AD-503).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `profile_retention_days` | `int` | `90` | — |  |
| `trust_delta_threshold` | `float` | `0.15` | — |  |
| `sweep_max_agents` | `int` | `50` | — |  |
| `alert_on_red` | `bool` | `True` | — |  |
| `alert_on_yellow` | `bool` | `False` | — |  |

## `circuit_breaker`

Cognitive circuit breaker thresholds (AD-506a).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `velocity_threshold` | `int` | `8` | — |  |
| `velocity_window_seconds` | `float` | `300.0` | — |  |
| `similarity_threshold` | `float` | `0.6` | — |  |
| `similarity_min_events` | `int` | `4` | — |  |
| `base_cooldown_seconds` | `float` | `900.0` | — |  |
| `max_cooldown_seconds` | `float` | `3600.0` | — |  |
| `amber_similarity_ratio` | `float` | `0.25` | — |  |
| `amber_velocity_ratio` | `float` | `0.6` | — |  |
| `amber_decay_seconds` | `float` | `900.0` | — |  |
| `red_decay_seconds` | `float` | `1800.0` | — |  |
| `critical_decay_seconds` | `float` | `3600.0` | — |  |
| `critical_trip_window_seconds` | `float` | `3600.0` | — |  |
| `critical_trip_count` | `int` | `3` | — |  |

## `trait_adaptive`

Trait-adaptive circuit breaker configuration (AD-494).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `concurrency`

AD-672: Per-agent concurrency management.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_max_concurrent` | `int` | `4` | — |  |
| `queue_max_size` | `int` | `10` | — |  |
| `capacity_warning_ratio` | `float` | `0.75` | — |  |
| `role_overrides` | `dict[str, int]` | `{'bridge': 3, 'operations': 6, 'engineering': 5, 'science': 4, 'medical': 3, 'security': 3}` | — |  |

## `trust_dampening`

Trust cascade dampening configuration (AD-558).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `dampening_window_seconds` | `float` | `300.0` | — |  |
| `dampening_geometric_factors` | `tuple[float, ...]` | `(1.0, 0.75, 0.5, 0.25)` | — |  |
| `dampening_floor` | `float` | `0.25` | — |  |
| `hard_trust_floor` | `float` | `0.05` | — |  |
| `cascade_agent_threshold` | `int` | `3` | — |  |
| `cascade_department_threshold` | `int` | `2` | — |  |
| `cascade_delta_threshold` | `float` | `0.15` | — |  |
| `cascade_window_seconds` | `float` | `300.0` | — |  |
| `cascade_global_dampening` | `float` | `0.5` | — |  |
| `cascade_cooldown_seconds` | `float` | `600.0` | — |  |
| `cold_start_observation_threshold` | `float` | `20.0` | — |  |
| `cold_start_dampening_floor` | `float` | `0.5` | — |  |

## `emergence_metrics`

Configuration for emergence metrics computation (AD-557).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `pid_bins` | `int` | `2` | — |  |
| `pid_permutation_shuffles` | `int` | `50` | — |  |
| `pid_significance_threshold` | `float` | `0.05` | — |  |
| `min_thread_contributors` | `int` | `2` | — |  |
| `min_thread_posts` | `int` | `3` | — |  |
| `thread_lookback_hours` | `float` | `24.0` | — |  |
| `groupthink_redundancy_threshold` | `float` | `0.8` | — |  |
| `fragmentation_synergy_threshold` | `float` | `0.1` | — |  |
| `tom_baseline_window` | `int` | `20` | — |  |
| `tom_trend_min_samples` | `int` | `10` | — |  |
| `hebbian_synergy_min_interactions` | `int` | `5` | — |  |

## `emergent_leadership`

Emergent leadership detection configuration (AD-439).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_weight` | `float` | `0.1` | — |  |
| `min_ratio` | `float` | `1.5` | — |  |

## `orders`

Chain-of-command order configuration (AD-440).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_active_per_post` | `int` | `8` | ≥ 1, ≤ 64 |  |
| `default_ttl_seconds` | `float` | `3600.0` | ≥ 60.0, ≤ 86400.0 |  |

## `validation_framework`

Validation framework configuration (AD-451).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `metadata_threshold` | `float` | `0.85` | ≥ 0.0, ≤ 1.0 |  |
| `min_confidence_delta` | `float` | `0.2` | ≥ 0.0, ≤ 1.0 |  |

## `pre_flight`

Pre-flight validation configuration (AD-458 / AD-458b).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `llm_tier_check_enabled` | `bool` | `True` | — |  |
| `required_llm_tier` | `str` | `'deep'` | — |  |
| `token_budget_check_enabled` | `bool` | `True` | — |  |
| `token_budget_blocking` | `bool` | `False` | — |  |

## `engineering`

Engineering crew configuration (AD-457).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `performance_interval_seconds` | `float` | `10.0` | ≥ 1.0 |  |
| `maintenance_interval_seconds` | `float` | `300.0` | ≥ 60.0 |  |
| `damage_control_cooldown_seconds` | `float` | `60.0` | ≥ 1.0 |  |

## `degradation`

Saucer separation / graceful degradation (AD-459 / AD-459b).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `auto_pause_enabled` | `bool` | `False` | — |  |

## `infodynamic`

Infodynamic telemetry configuration (AD-491).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `event_window_seconds` | `float` | `3600.0` | ≥ 60.0 |  |
| `trust_buckets` | `int` | `10` | ≥ 2, ≤ 100 |  |

## `infrastructure`

Engineering infrastructure configuration (AD-466).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `backup_enabled` | `bool` | `True` | — |  |
| `backup_subdir` | `str` | `'backups'` | — |  |

## `security_infra`

Security infrastructure configuration (AD-456 + AD-456b).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `secrets_persistence_enabled` | `bool` | `True` | — |  |
| `secrets_store_filename` | `str` | `'secrets.json'` | — |  |
| `egress_enabled` | `bool` | `True` | — |  |
| `egress_deny_by_default` | `bool` | `True` | — |  |
| `audit_enabled` | `bool` | `True` | — |  |
| `sandbox_enabled` | `bool` | `True` | — |  |
| `sandbox_default_wall_timeout_seconds` | `float` | `30.0` | — |  |
| `sandbox_default_memory_peak_mb` | `float` | `256.0` | — |  |
| `egress_active_enforcement` | `bool` | `False` | — |  |
| `credential_tier_enforcement` | `bool` | `False` | — |  |
| `audit_persistence_enabled` | `bool` | `False` | — |  |
| `audit_persistence_filename` | `str` | `'audit_log.db'` | — |  |
| `audit_retention_days` | `int` | `90` | — |  |

## `ground_truth`

Ground-truth task verification configuration (AD-528, AD-528b, AD-528c).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `threshold` | `float` | `0.75` | ≥ 0.0, ≤ 1.0 |  |
| `event_window_seconds` | `float` | `600.0` | ≥ 10.0 |  |
| `write_episode` | `bool` | `True` | — |  |
| `active_rejection_enabled` | `bool` | `False` | — |  |
| `quarantine_metadata_key` | `str` | `'ground_truth_quarantine'` | — |  |
| `trust_feedback_enabled` | `bool` | `False` | — |  |
| `trust_feedback_success_weight` | `float` | `1.0` | ≥ 0.0 |  |
| `trust_feedback_failure_weight` | `float` | `0.5` | ≥ 0.0 |  |

## `operations`

Operations crew configuration (AD-467).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `resource_interval_seconds` | `float` | `30.0` | ≥ 1.0 |  |
| `resource_emit_interval_seconds` | `float` | `60.0` | ≥ 10.0 |  |
| `scheduler_interval_seconds` | `float` | `60.0` | ≥ 10.0 |  |
| `coordinator_interval_seconds` | `float` | `60.0` | ≥ 10.0 |  |

## `model_routing`

Model routing configuration (AD-463).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `cost_ceiling_per_million_output_tokens` | `float | None` | `None` | — |  |

## `ready_room`

Captain's Ready Room configuration (AD-475).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `idea_store_filename` | `str` | `'ready_room/ideas.json'` | — |  |
| `wardroom_channel_id` | `str` | `'ready_room'` | — |  |

## `dept_profiles`

AD-656: dict of department-name -> DepartmentCognitiveProfile.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `profiles` | `dict[str, probos.config.DepartmentCognitiveProfile]` | `{}` | — |  |

## `eps`

EPS - Compute/Token Distribution (AD-469).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `window_seconds` | `float` | `60.0` | ≥ 10.0 |  |
| `over_budget_threshold` | `float` | `1.25` | ≥ 1.0, ≤ 10.0 |  |
| `departments` | `list[probos.config.EPSDepartmentConfig]` | `[EPSDepartmentConfig(name='engineering', percent=0.3, priority=3), EPSDepartmentConfig(name='science', percent=0.2, priority=4), EPSDepartmentConfig(name='medical', percent=0.15, priority=2), EPSDepartmentConfig(name='security', percent=0.15, priority=2), EPSDepartmentConfig(name='operations', percent=0.1, priority=4), EPSDepartmentConfig(name='other', percent=0.1, priority=6)]` | — |  |

## `mcp`

MCP Bridge configuration (AD-449; AD-1014 stdio).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `request_timeout_seconds` | `float` | `30.0` | ≥ 1.0 |  |
| `servers` | `list[probos.config.MCPServerConfig]` | `[]` | — |  |
| `stdio_enabled` | `bool` | `False` | — |  |
| `command_allowlist` | `list[str]` | `['uvx', 'npx', 'python', 'node', 'docker']` | — |  |
| `management_enabled` | `bool` | `False` | — |  |
| `agent_tools_enabled` | `bool` | `False` | — |  |
| `agent_tool_idle_ttl_seconds` | `float` | `86400.0` | ≥ 1.0 |  |
| `agent_tool_reaper_interval_seconds` | `float` | `3600.0` | ≥ 1.0 |  |

## `mcp_app_host`

AD-597 — MCP App Host configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `serve_internal_games` | `bool` | `True` | — |  |
| `discover_external_apps` | `bool` | `False` | — |  |
| `internal_default_csp` | `str` | `"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"` | — |  |
| `external_default_csp` | `str` | `"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'"` | — |  |
| `bundles_dir` | `str` | `''` | — |  |

## `browser_tool`

AD-706: BrowserTool (Computer Use via Playwright).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `headless` | `bool` | `True` | — |  |
| `default_timeout_ms` | `int` | `30000` | — |  |
| `session_max_duration_seconds` | `int` | `1800` | — |  |
| `session_reaper_interval_seconds` | `int` | `60` | — |  |
| `domain_allowlist` | `list[str] | None` | `None` | — |  |
| `domain_denylist` | `list[str]` | `[]` | — |  |
| `screenshot_max_width` | `int` | `1024` | — |  |
| `screenshot_max_height` | `int` | `768` | — |  |
| `require_confirmation_for_tier_3` | `bool` | `True` | — |  |
| `confirmation_timeout_seconds` | `int` | `300` | — |  |
| `default_min_interval_seconds` | `float` | `1.0` | — |  |
| `per_action_timeout_ms` | `dict[str, int]` | `{}` | — |  |
| `tier_3_domain_patterns` | `list[str]` | `['*bank*', '*paypal*', '*stripe*', '*chase*', '*coinbase*', '*checkout*']` | — |  |
| `llm_classifier_enabled` | `bool` | `False` | — | AD-706d: LLM-driven tier classifier for Browser Tool actions. Augments the rule-based classifier; default OFF. |
| `llm_classifier_tier` | `str` | `'fast'` | — | AD-706d: LLM tier for classification calls. Fast is cheapest and adequate for tier classification. |
| `llm_classifier_max_per_hour` | `int` | `60` | ≥ 0 | AD-706d: per-runtime hourly cap on LLM classifier calls. 0 disables. Reuses the AD-722a-1 VisionLLMRateLimit primitive under scope 'browser_action_classifier'. |
| `llm_classifier_cache_ttl_seconds` | `int` | `300` | ≥ 0 | AD-706d: in-memory cache TTL for identical (action, url-prefix, element-text, page-title) tuples. 0 disables caching. |
| `compute_use_max_consecutive_autonomous_actions` | `int` | `5` | ≥ 0, ≤ 20 | AD-706c-2: per-session cap on consecutive ``compute_use_click`` actions without a Captain ACK. Resets on any tier-3 ACK signal. 0 disables compute_use entirely. |
| `compute_use_max_per_session` | `int` | `50` | ≥ 0, ≤ 500 | AD-706c-2: per-session hard cap on total ``compute_use_click`` calls. Independent of the consecutive-autonomous cap. 0 disables. |
| `streaming_enabled` | `bool` | `False` | — | AD-706a: enable MJPEG-over-HTTP Captain-watch streaming. Default-OFF (Wave 10 convention #14). |
| `streaming_fps` | `int` | `4` | ≥ 1, ≤ 15 | AD-706a: frames-per-second for MJPEG streaming. Higher fps quickly overwhelms localhost. |
| `streaming_jpeg_quality` | `int` | `60` | ≥ 20, ≤ 95 | AD-706a: JPEG quality (Playwright page.screenshot quality param). |
| `streaming_max_concurrent_viewers` | `int` | `4` | ≥ 1, ≤ 16 | AD-706a: per-runtime cap on concurrent Captain-watch viewer slots. |
| `recording_enabled` | `bool` | `False` | — | AD-706b: enable Playwright record_video_dir on each BrowserSession. Default-OFF. |
| `recording_dir` | `str` | `'data/browser-sessions'` | — | AD-706b: directory tree where session subdirs (and .webm files) are written. |
| `recording_retention_days` | `int` | `7` | ≥ 1, ≤ 365 | AD-706b: delete recordings older than this many days. |
| `recording_reaper_interval_seconds` | `int` | `3600` | ≥ 60, ≤ 86400 | AD-706b: sleep interval between recording-reaper sweeps. |
| `recording_max_size_mb_per_session` | `int` | `500` | ≥ 10, ≤ 5000 | AD-706b: per-session size cap (MB); oldest webm files deleted when exceeded. |
| `bridge_enabled` | `bool` | `False` | — | AD-1052b: enable BRIDGE mode (connect_over_cdp to an external user-launched Chrome). Higher-risk than headless; default OFF. |
| `bridge_allowed_hosts` | `list[str]` | `['127.0.0.1', 'localhost', '[::1]']` | — | AD-1052b: SSRF allowlist — the CDP endpoint host must match one of these (case-insensitive exact match). Refuses arbitrary remote CDP endpoints (exfil/SSRF guard). Localhost-only by default. |
| `input_forwarding_enabled` | `bool` | `False` | — | AD-1052c: enable forwarding human pointer/keyboard input from the HXI watch canvas to the live browser page. Higher-risk (the human drives the shared/real browser); default OFF. |
| `viewport_width` | `int` | `1280` | ≥ 1, ≤ 16384 | AD-1052c: viewport width (CSS px) fallback for normalized-coord mapping when page.viewport_size is None. |
| `viewport_height` | `int` | `720` | ≥ 1, ≤ 16384 | AD-1052c: viewport height (CSS px) fallback for normalized-coord mapping when page.viewport_size is None. |
| `action_dispatch_enabled` | `bool` | `False` | — | AD-745: master switch for parsing [ACTION: ...] markers in DM replies and dispatching them to BrowserTool. Default OFF. |
| `action_dispatch_max_consecutive_autonomous` | `int` | `5` | ≥ 0, ≤ 20 | AD-745: consecutive tier-1/2 dispatched actions before forcing tier-3 Captain confirm. Reuses AD-706c-2 Guard #10 trust-budget pattern across all action verbs (not just compute_use_click). |
| `action_dispatch_max_per_dm_turn` | `int` | `1` | ≥ 1, ≤ 10 | AD-745 v1: single action per DM reply. >1 reserved for AD-745-6 multi-step plans (forward marker). |
| `action_dispatch_ack_timeout_seconds` | `int` | `60` | ≥ 5, ≤ 600 | AD-745: tier-2 ACK timeout. Honest-degrade to TIMED_OUT after this many seconds without Captain ack. Tier-3 confirms NEVER time out (Captain decision required). |
| `destructive_url_patterns` | `list[str]` | `['*/checkout*', '*/payment*', '*/billing*', '*/auth/*', '*/login*', '*/oauth*', '*/admin/*', '*/settings/account*', '*/delete*', '*/destroy*']` | — | AD-745: fnmatch patterns. URLs matching any pattern force ALL action verbs to tier-3 (Captain ACK every call). |

## `credential_vault`

AD-706f: Browser Tool credential vault.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-706f: enable encrypted credential vault. Default OFF. |
| `backend` | `str` | `'file'` | — | AD-706f/AD-1016: credential backend kind. 'file' (default) = encrypted JSON vault (Fernet KEK from auth.crew_scope_token); 'keychain' = OS keychain (DPAPI / macOS Keychain / libsecret) with a non-secret metadata sidecar. |
| `file_path` | `str` | `'data/credential_vault.json'` | — | AD-706f: JSON sidecar path for the EncryptedFileCredentialVault. |
| `keyring_index_path` | `str` | `'data/credential_keyring_index.json'` | — | AD-1016: non-secret metadata sidecar path for the keychain backend (holds scope/timestamps only — never a secret value). |
| `keyring_service_name` | `str` | `'probos.credentials'` | — | AD-1016: OS-keychain service name for the keychain backend (CredentialEncryptor namespace). |
| `max_credentials` | `int` | `100` | ≥ 1, ≤ 10000 | AD-706f: per-vault hard cap on stored credentials. |
| `require_https_for_fill` | `bool` | `True` | — | AD-706f: when True, fill_credential blocks page.fill on http:// URLs. Operators override only for explicit dev/local scenarios. |

## `avatars`

AD-721: 3D crew avatars (VRM popout).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `avatars_dir` | `str` | `'data/avatars'` | — |  |
| `max_vrm_size_bytes` | `int` | `26214400` | — |  |
| `fallback_to_parametric_on_error` | `bool` | `True` | — |  |
| `blender_path` | `str` | `''` | — |  |
| `blender_render_timeout_s` | `int` | `180` | — |  |
| `dsl_drafts_dir` | `str` | `'data/avatars/.drafts'` | — |  |
| `renderer_enabled` | `bool` | `False` | — |  |
| `procedural_base_mesh_fallback` | `bool` | `True` | — |  |
| `max_proposal_iterations` | `int` | `3` | — |  |
| `proposal_history_path` | `str | None` | `None` | — | AD-721d-4: filesystem path for the per-agent DSL proposal history JSON sidecar. When None, defaults to ``<runtime.data_dir>/proposal_history.json``. |
| `vision_proposal_history_path` | `str | None` | `None` | — | AD-720d-2.1: filesystem path for the vision-capability proposal-history JSON sidecar. |
| `vision_intent_divergence_enabled` | `bool` | `False` | — | AD-722a-1: enable vision-LLM intent-vs-render divergence detection. Default-OFF until AD-721i backend renderer ref lookup is stable. |
| `vision_intent_divergence_max_per_hour_per_agent` | `int` | `3` | — | AD-722a-1: per-agent hourly call cap for vision-LLM intent divergence (aligns with AD-728 cost ceiling). |
| `self_render_verify_enabled` | `bool` | `False` | — | AD-722e-2: enable vision-LLM digital-vs-render coherence verification. Default-OFF until AD-721i backend renderer ref lookup is stable. |
| `self_render_verify_max_per_hour_per_agent` | `int` | `3` | — | AD-722e-2: per-agent hourly call cap for vision-LLM self-render verification (aligns with AD-728 cost ceiling). |
| `render_verification_enabled` | `bool` | `False` | — | AD-728: vision-LLM render-coherence mirror. Default OFF until AD-721i backend renderer is stable. |
| `render_verification_max_per_hour_per_agent` | `int` | `3` | ≥ 0 | AD-728: per-agent hourly cap for render-verification vision calls. 0 disables. Shares the AD-722a-1 VisionLLMRateLimit primitive under scope 'render_verification'. |
| `render_verification_followup_enabled` | `bool` | `False` | — | AD-728: when True, an AD-722a-1 intent-divergence observation triggers a render-coherence mirror call with trigger='divergence_followup'. Default OFF; flip after AD-728 RENDER_DIVERGENCE_OBSERVED telemetry is stable. |
| `render_self_check_enabled` | `bool` | `False` | — | AD-728c: flip agent_initiated_stub trigger from hard-reject to a gated, rate-limited self-check. Default OFF; flip after AD-728 telemetry confirms vision-tier cost is bounded. |
| `render_self_check_max_per_hour_per_agent` | `int` | `3` | ≥ 0 | AD-728c: per-agent hourly cap for agent-initiated render self-checks. Applies when the agent is NOT in an active conversation. 0 disables. Uses the AD-722a-1 VisionLLMRateLimit primitive under scope 'render_self_check_hour'. |
| `render_self_check_max_per_active_conversation` | `int` | `2` | ≥ 0 | AD-728c: per-agent budget within a single active conversation window. Pattern: 'before reply + 1 mid-conversation'. Applies INSTEAD OF the hourly budget while the agent is in an active conversation. 0 disables self-check during active conversations. |
| `render_self_check_active_window_seconds` | `int` | `600` | ≥ 0 | AD-728c: seconds since the agent's last reply emission to consider it 'in an active conversation' for self-check budget selection. Default 600s = 10 minutes. Uses CognitiveAgent.last_reply_emitted_at (AD-722). |
| `affect_drift_default_window` | `int` | `8` | ≥ 2, ≤ 128 | AD-740: default window size (most recent N divergence entries) for affect-vs-intent drift trend summary. Operators may pass an explicit ``window`` to ``get_affect_drift`` to override. |
| `affect_drift_threshold` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 | AD-740: match-score threshold below which an entry counts as a 'divergent' turn in the drift summary. Default 0.7 mirrors the conservative end of the AD-722a divergence band. |
| `image_gen_enabled` | `bool` | `False` | — | AD-730-3: master switch for agent image generation via [GEN_IMAGE ...] bracket marker. Default OFF (transitional). Requires CognitiveConfig.llm_base_url_image_gen to be set. |
| `image_gen_max_prompt_chars` | `int` | `512` | ≥ 8, ≤ 4000 | AD-730-3: hard cap on the [GEN_IMAGE ...] prompt length. Markers exceeding this are silently stripped and a single WARNING is logged. |
| `image_gen_wellness_review_required` | `bool` | `True` | — | AD-730-3: when True, the FIRST image_gen invocation per agent per process triggers a Counselor wellness review log entry (AD-727 governance pattern). Subsequent invocations by the same agent skip the review until process restart. |
| `image_gen_max_image_bytes` | `int` | `4194304` | ≥ 65536, ≤ 26214400 | AD-730-3: per-image size cap on bytes written to AttachmentStore. Defense in depth alongside the upstream API's own limits. |
| `image_gen_mime` | `str` | `'image/png'` | — | AD-730-3: declared MIME for stored images. PNG is OpenAI's default. Operator may set to image/jpeg if their endpoint returns JPEG. |
| `peer_perception_enabled` | `bool` | `False` | — | AD-729: peer avatar perception capability. Default OFF until AD-729a Standing Orders ship and AD-729b certification grades at least one officer. |
| `peer_observation_decay_seconds` | `int` | `604800` | ≥ 3600 | AD-729: impression decay window in seconds. Observations older than this are filtered from composite impressions. |
| `peer_observation_max_per_pair_per_thread` | `int` | `1` | ≥ 0 | AD-729: mechanical floor — max observations per (observer, observed) pair per WR thread. 0 disables capability entirely. |
| `cross_agent_divergence_observation_enabled` | `bool` | `False` | — | AD-722a-6: peer perception of intent-vs-presentation. Default OFF; requires peer_perception_enabled True AND AD-729a Standing Orders shipped before being flipped. |
| `canvas_render_vrm_avatars` | `bool` | `False` | — | AD-721f: render registered VRMs in the Cognitive Canvas at canvas scale for agents within the LOD distance threshold. Default OFF -- operators with low-end GPUs keep the orb-only path. |
| `canvas_max_concurrent_vrms` | `int` | `12` | ≥ 0, ≤ 64 | AD-721f: max VRMs rendered simultaneously in the canvas. Agents beyond this count fall back to orb instances. |
| `canvas_vrm_lod_distance` | `float` | `15.0` | > 0.0 | AD-721f: camera-distance threshold (world units) under which agents render as VRMs. Beyond this distance, the orb path is used. |
| `animations_dir` | `str` | `'data/avatars/animations'` | — | AD-721e: directory of operator-installed CC0/MIT animation clips. Gitignored; operator-fetched via scripts/animations-fetch.ps1. |
| `animations_enabled` | `bool` | `False` | — | AD-721e: enable AnimationMixer playback in CrewVRM. Default OFF -- operators without animations installed keep the procedural idle fallback. |
| `pacing_enabled` | `bool` | `False` | — | AD-743: enable [FOLLOW_UP delay reason] marker parsing and the ConversationPacingScheduler runtime service. Default OFF transitional flag (convention #14) — existing turn-taking DM behavior is bit-for-bit preserved when disabled. |
| `pacing_max_followups_per_active_conversation` | `int` | `2` | ≥ 0, ≤ 10 | AD-743: per-conversation cap on synthesized follow-ups before the active window resets. |
| `pacing_max_followups_per_hour_per_agent` | `int` | `6` | ≥ 0, ≤ 60 | AD-743: rolling 1h ceiling on follow-ups per agent across all conversations (safety cap). |
| `pacing_active_window_seconds` | `int` | `600` | ≥ 60, ≤ 3600 | AD-743: silence threshold beyond which a conversation is considered inactive and the per-conversation budget resets. |
| `pacing_min_delay_seconds` | `int` | `1` | ≥ 1, ≤ 60 | AD-743: minimum allowed delay for a [FOLLOW_UP] marker. Markers below this floor are stripped and discarded. |
| `pacing_max_delay_seconds` | `int` | `300` | ≥ 1, ≤ 900 | AD-743: maximum allowed delay for a [FOLLOW_UP] marker. Markers above this ceiling are stripped and discarded. |

## `baseline_vrms`

AD-721g: per-rank baseline VRM filenames.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `ensign` | `str` | `''` | — |  |
| `lieutenant` | `str` | `''` | — |  |
| `commander` | `str` | `''` | — |  |
| `senior` | `str` | `''` | — |  |

## `avatar_telemetry`

AD-722: agent-observable avatar telemetry channel.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `inject_into_agent_context` | `bool` | `False` | — |  |
| `mouth_active_window_seconds` | `float` | `3.0` | — |  |
| `polling_interval_ms` | `int` | `2000` | — |  |
| `max_connections_per_agent` | `int` | `4` | — |  |
| `divergence_detection` | `bool` | `False` | — |  |
| `divergence_negative_threshold` | `float` | `0.3` | — |  |
| `divergence_positive_threshold` | `float` | `0.5` | — |  |
| `divergence_negative_weight` | `float` | `0.4` | — |  |
| `divergence_positive_weight` | `float` | `0.1` | — |  |
| `divergence_history_size` | `int` | `100` | — |  |
| `divergence_aggregate_window` | `int` | `50` | — |  |
| `auto_correct_enabled` | `bool` | `False` | — |  |
| `auto_correct_threshold` | `float` | `0.6` | — |  |
| `max_corrections_per_utterance` | `int` | `1` | — |  |
| `correction_noise_factor` | `float` | `1.15` | — |  |
| `correction_length_factor` | `float` | `0.92` | — |  |
| `history_enabled` | `bool` | `True` | — |  |
| `history_retention_days` | `int` | `30` | — |  |
| `history_dir` | `str` | `'data/avatar_telemetry'` | — |  |
| `records_auto_write_enabled` | `bool` | `False` | — |  |
| `records_throttle_seconds` | `int` | `3600` | — |  |
| `records_significant_events` | `list[str]` | `['emotion_divergence_high', 'working_state_transition_to_blocked', 'sustained_silence']` | — |  |
| `sustained_silence_seconds` | `int` | `1800` | — |  |
| `ws_diff_enabled` | `bool` | `True` | — |  |
| `ws_diff_threshold` | `float` | `0.05` | — |  |
| `ws_full_snapshot_every_n` | `int` | `10` | — |  |
| `fleet_stream_enabled` | `bool` | `True` | — |  |

## `sampling_rates`

AD-722f: per-agent avatar-telemetry sampling rates (3 tiers).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `high_ms` | `int` | `250` | — |  |
| `normal_ms` | `int` | `2000` | — |  |
| `low_ms` | `int` | `10000` | — |  |

## `dm_sanity_gate`

Configuration for the DM one-shot sanity gate.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `length_floor` | `int` | `5` | — |  |
| `repetition_prefix_chars` | `int` | `100` | — |  |
| `repetition_similarity_threshold` | `float` | `0.85` | — |  |
| `retry_on_rejection` | `bool` | `True` | — |  |
| `retry_warnings` | `list[str]` | `['length_floor', 'orphaned_tag']` | — |  |

## `dm_targeted_lookup`

AD-725: pre-LLM targeted sub-intent dispatch on the DM one-shot path.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `classifier_tier` | `str` | `'regex'` | — |  |
| `timeout_ms` | `int` | `500` | — |  |
| `enable_oracle` | `bool` | `True` | — |  |
| `enable_episodic` | `bool` | `True` | — |  |
| `enable_codebase` | `bool` | `False` | — |  |
| `enable_knowledge` | `bool` | `True` | — |  |
| `identity_enabled` | `bool` | `True` | — |  |
| `max_lookup_chars` | `int` | `1500` | — |  |

## `dm_deliberate`

AD-934 (Option C): flag-gated [THINK]/[DELIBERATE] deep-tier re-roll.     Default OFF — opt-in because the re-roll adds a full deep-tier LLM pass     (latency + cost) per marker-bearing reply.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `tier` | `str` | `'deep'` | — |  |
| `max_tokens` | `int` | `800` | — |  |

## `dm_agentic`

AD-1065: flag-gated conversational agentic turn. When enabled, a 1:1     ``direct_message`` reply runs the AgenticLoop (tool-calling) instead of a     single LLM pass, so an agent can read / write / execute on the Captain's     behalf mid-conversation (Claude Cowork / Codex / Copilot parity). A no-tool     turn is a single pass (the model just answers), so the flag only adds latency     when the agent actually calls a tool. Default OFF (opt-in: adds tool-calling     + per-call latency); 1:1 only (group / ward-room / proactive / vision turns     keep the single-pass path).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `max_iterations` | `int` | `5` | ≥ 1, ≤ 25 |  |
| `tier` | `str` | `'standard'` | — |  |
| `continue_or_ask_enabled` | `bool` | `False` | — | AD-1164: when a conversational turn exhausts max_iterations, continue it or ask the Captain, instead of stopping silently. BF-697 stopped the partial work being DISCARDED; this stops it being reported as though the turn had finished. With the gate on, a turn that hits the step limit either (a) re-invokes with a fresh max_iterations allowance when a standing rule from AD-1154's ActionApprovalStore covers this agent, bounded by continue_or_ask_max_passes, or (b) files a kind='continue' request into the AD-853 approval queue and returns the partial work with an explicit statement that it stopped mid-task. Default-OFF per convention #14 — with the gate off the turn behaves exactly as it does today. Only max_iterations is ever continued: token_budget is a spend ceiling the operator set, error is usually provider-window exhaustion that a longer prompt makes worse, and complete means the model chose to stop. Every failure path (absent store, raising cache read, failed re-invocation) degrades to today's behaviour, so arming this can cost you an unnecessary question but never a turn. |
| `continue_or_ask_max_passes` | `int` | `2` | ≥ 1, ≤ 5 | AD-1164: the hard cap on how many times ONE conversational turn's agentic loop is run, COUNTING THE FIRST. 1 means no re-invocation, identical to today; the cap is a bound, never an enable — continue_or_ask_enabled is what turns the feature on. Mirrors agentic_dispatch.crew_loop_until_done_max_iterations, which is the same bound on the crew fan-out. WORST CASE: each pass gets a fresh max_iterations (default 5, ceiling 25) turns and one turn can carry up to agentic_loop.max_parallel_tool_calls (ceiling 16) concurrent tool calls, so at this ceiling of 5 that is 5 x 25 x 16 = 2000 tool invocations for a single chat turn. A pass only happens while a live standing rule permits it, so reaching that ceiling requires the Captain to have issued one. |
| `promote_to_task_after_seconds` | `float` | `0.0` | ≥ 0.0, ≤ 600.0 | AD-1165: seconds a conversational agentic turn may run before it stops being a reply and becomes a background task. A Captain DM is dispatched with a 60s intent TTL, so a turn that does real work (driving a browser, producing a document) is cancelled mid-flight and the Captain is told the agent did not respond — for a turn in which it was working correctly. Past this budget the run is NOT cancelled or restarted: the same in-flight loop keeps going, a work item is opened for it, the turn returns an acknowledgement inside the TTL, and the result is posted into the same thread when it lands. Set it BELOW the 60s chat TTL with room for one more loop iteration — 35 is a reasonable starting value. 0 disables promotion, which is the default and is byte-identical to AD-1164: the turn is awaited inline and a long one still trips the TTL. Promotion needs a chat thread and a work-item store; without either it degrades to that same inline wait rather than promising a report nothing would deliver. |
| `hold_degraded_turns` | `bool` | `False` | — | AD-1230: hold a Captain DM that the LLM was too degraded to answer, and reply in the same thread once the model recovers. OFF reproduces BF-714 exactly — the Captain is told the tier is cooling, how long it has left, and to send the message again. ON, the turn is held and the Captain is told an answer is coming, which is a promise the runtime then has to keep: a thread holding a turn accepts no further turns until that one is answered, held turns are replayed oldest-first one at a time, and every abandonment path (TTL, retries exhausted, shutdown) posts into the thread rather than dropping silently. Only turns whose degrade the runtime could actually diagnose are held — an unreadable health status is not evidence a retry would help. The queue is in memory by design: the outage it covers is measured in seconds (BF-674 clocked 48.8s), so a durable store would outlive its own TTL. |
| `hold_degraded_turn_ttl_seconds` | `float` | `900.0` | ≥ 30.0, ≤ 7200.0 | AD-1230: how long a held turn waits for the model before it is abandoned with a note in the thread. Past this the answer is stale enough that resending is better than delivering it — an answer to a question the Captain asked an hour ago, arriving under everything said since, costs more attention than it returns. |
| `hold_degraded_turn_max_threads` | `int` | `16` | ≥ 1, ≤ 256 | AD-1230: how many distinct threads may hold a turn at once. One turn is held per thread and that thread accepts no further turns until it is answered, so this bounds the ship, not the conversation. At the ceiling a further thread is told to resend rather than being promised an answer that would queue behind fifteen others. |
| `compaction_enabled` | `bool` | `False` | — | AD-1167: compact the working context of a long conversational turn. The agentic loop re-flattens its entire message history into one prompt every iteration, so without compaction each added step re-pays for every step before it. Measured on a live instance: raising max_iterations from 10 to 20 took one turn from 218,957 to 474,736 tokens — more than double for twice the steps — and produced a WORSE answer, because the early tool result that had located the target was buried under twenty rounds of re-flattened history. Compaction summarises older messages through the fast tier and preserves the most recent ones. The durable tool trace is unaffected: it is persisted after the loop finishes, so transparency is retained. Off by default; when off the loop is constructed exactly as before. Turn this on before raising max_iterations, not after. |
| `compaction_threshold_tokens` | `int` | `60000` | ≥ 0 | AD-1167: estimated working-context size, in tokens, at which compaction runs. Only consulted when compaction_enabled is true; 0 disables compaction even then. The default leaves generous room below a 200k context window while still engaging well before the runaway growth measured above. |

## `agentic_tools`

Tools offered inside the agentic loop, including the Σ commons read/write verbs. The publish path has **no consensus gate** — the rate and size bounds are the control.

AD-1072: conversational-loop discovery + delegation tools (default-OFF).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `tool_search_enabled` | `bool` | `False` | — |  |
| `delegation_enabled` | `bool` | `False` | — |  |
| `delegation_max_depth` | `int` | `1` | ≥ 0, ≤ 3 |  |
| `delegation_max_iterations` | `int` | `5` | ≥ 1, ≤ 25 |  |
| `delegation_tier` | `str` | `'standard'` | — |  |
| `oracle_query_enabled` | `bool` | `False` | — |  |
| `publish_finding_enabled` | `bool` | `False` | — |  |
| `publish_finding_max_per_hour` | `int` | `12` | ≥ 1, ≤ 100 |  |
| `publish_finding_max_content_chars` | `int` | `4000` | ≥ 200, ≤ 20000 |  |
| `publish_finding_max_per_hour_ship` | `int` | `40` | ≥ 1, ≤ 500 |  |
| `browser_enabled` | `bool` | `False` | — | AD-1153: offer the registered BrowserTool to the agentic loop. v1 is READ-ONLY — the loop admits only goto, state, extract_text, back, forward and wait, which are exactly the actions that stay below the tier-3 confirmation gate; click/type/scroll wait on AD-1154. Also requires browser_tool.enabled plus an importable Playwright. Egress consequence: browser_tool.domain_allowlist defaults to None, which permits every host absent from domain_denylist — set an allowlist to bound where an agent may navigate. |
| `disposition_enabled` | `bool` | `False` | — | AD-1180: compose the shared agentic disposition (probos.cognitive.agentic_disposition.AGENTIC_DISPOSITION) into the system prompt inside WorkItemAgenticExecutor.run, so it reaches every path that hands an agent a tool array. AD-1177 authored that text and it reached exactly ONE of the five callers -- the Captain's 1:1 DM turn -- because the other four (the AD-856 task path, crew children, the AD-860 convergence re-run and AD-1072 delegation) pass the agent's STATIC instructions attribute straight through while receiving the same eleven-group tool array. Default-OFF: with this False the system prompt reaching the loop is byte-identical to AD-1177 on every path. Turning it ON is a REAL behaviour change for crew children, verifier convergence and delegated sub-agents by design -- it adds roughly 1,500 characters of disposition to each of those runs and tells them to be resourceful, to treat run_python as the general-purpose instrument, and to act inside their orders. Interaction to know: crew_token_budget (AD-1142) is a HARD STOP that fails a child and blocks its dependents; it defaults to None, so on shipped defaults there is no ceiling for these characters to push a child over. |
| `crew_sigma_context_enabled` | `bool` | `False` | — |  |
| `crew_sigma_max_chars` | `int` | `2000` | ≥ 200, ≤ 8000 |  |
| `crew_sigma_max_entries` | `int` | `4` | ≥ 1, ≤ 12 |  |
| `crew_sigma_min_score` | `float` | `0.35` | ≥ 0.0, ≤ 1.0 |  |

## `repair`

Dispatching a reported fault to a harness of the Captain's choosing.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-1172: propose a repair when a fault is reported. Off by default. When on, a fault that reaches propose_after_occurrences raises an approval asking the Captain whether to dispatch it and to which harness. Approval is required before anything is spent: an Architect run costs deep-tier tokens, and a tool failing in a loop must not be able to spend them on its own. |
| `targets` | `list[str]` | `['architect']` | — | AD-1172: harnesses this instance can dispatch a repair brief to, in the order they are offered. 'architect' is the internal crew (ArchitectAgent then BuilderAgent). Any other name is an external harness — GitHub Copilot, Claude Code, a person — reached by rendering the brief for the Captain to carry across. External targets need no code: the brief IS the interface, which is what keeps them first-class rather than a degraded path. |
| `propose_after_occurrences` | `int` | `2` | ≥ 1 | AD-1172: how many times a fault must recur before a repair is proposed. Matches the AD-1168/1170/1171 threshold: once is a transient, twice is the tool. |

## `approval_inbox`

AD-1154: park an unattended consequential action instead of performing it.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-1154: park a tier-3 unattended tool action as a durable capability request (kind='action') instead of letting the tier-3 gate return its success-shaped intervention_required no-op. The agent is told in an ERROR-shaped result that the step did not run, and the run continues. Approval does NOT replay the parked action — the browser session TTL (1800s) is far shorter than human decision latency, so replaying a page-relative selector against a changed page would be a different act. Off by default; off means the dispatch path is byte-identical to AD-1153. |
| `standing_rules_enabled` | `bool` | `False` | — | AD-1154: additionally permit the Captain to convert an approval into a standing, scoped, mandatorily-expiring rule that answers the same ask on the next run. Separate from 'enabled' so an operator can take the audit trail without the durable privilege grant. Rules match (agent_id, tool_id, action, scope_key) exactly — there is no wildcard, and scope_key='' matches only an ask whose scope is also ''. No HXI affordance ships with this: grant_standing is API-only on POST /api/capability-requests/{id}/decide, and the capability-request panel has no Approve-with-standing control until a follow-up adds one. |
| `standing_rule_max_ttl_hours` | `int` | `168` | ≥ 1, ≤ 720 | AD-1154: hard ceiling on a standing rule's lifetime. A requested TTL above this is clamped, not rejected. expires_at is NOT NULL in the action_approvals schema, so no standing rule can be issued without an expiry. |
| `standing_rule_default_ttl_hours` | `int` | `24` | ≥ 1, ≤ 720 | AD-1154: TTL applied when the Captain approves with grant_standing but names no duration. Deliberately far below standing_rule_max_ttl_hours so the low-effort path is the short-lived one. Should be <= the max; clamped at issue time rather than validated, so an out-of-order pair cannot 422 an unrelated config write. |
| `max_pending_per_agent` | `int` | `20` | ≥ 1, ≤ 200 | AD-1154: per-agent cap on undecided action asks. At the cap the wrapper REFUSES without filing and logs at WARNING with the agent id and count — a neglected inbox becomes an honest refusal within this many asks per agent rather than an unbounded queue that looks like progress. |
| `pending_ask_ttl_hours` | `int` | `72` | ≥ 1, ≤ 720 | AD-1154: age at which an undecided ask is treated as stale. Stale asks are excluded from the max_pending_per_agent count but are NEITHER auto-approved NOR auto-denied — they keep status='pending' and keep appearing in the pending list, because auto-approving on timeout would make walking away the approval mechanism. |
| `work_permits_enabled` | `bool` | `False` | — | AD-1159: issue single-holder, expiring work permits over a workstation within a crew session, so at most one agent holds (session_id, workstation_id) at a time and its hazard ceiling is explicit rather than implied. A permit's issuing authority must differ from its holder — the officer who authorizes never performs — and every permit carries a mandatory expiry (expires_at is NOT NULL in the work_permits schema). Off by default; off means the dispatch path is byte-identical to AD-1158. Nothing consumes the store in AD-1159: it lands with tests and no callers so its first exercise is not in production. AD-1160 wires it. |
| `work_permit_default_ttl_seconds` | `float` | `3600.0` | > 0.0, ≤ 86400.0 | AD-1159: lifetime applied to a work permit whose issuer names no duration. One hour, deliberately short: a permit is authority to act on a live workstation, and the cost of an expiry that is too short is a reissue, while the cost of one that is too long is an authority nobody remembers granting. Expiry is lazy — a lapsed permit answers as absent on the next read rather than being reaped — so a stale row is inert, not active. |
| `work_permit_max_tier_ceiling` | `int` | `2` | ≥ 1, ≤ 3 | AD-1159: highest classify_action hazard tier a work permit may authorize by default. 2 covers observation plus ordinary click/type/goto; tier 3 (eval_js, upload_file, fill_credential, checkout and payment paths) is excluded so reaching it needs an explicit Captain-issued permit rather than an inherited default. Bounded 1-3 because that is the whole tier ladder classify_action returns; a ceiling outside it is unrepresentable rather than merely discouraged. |

## `dm_mesh_synthesis`

BF-629: after a requires_reflect inline mesh read (web_search / read_page)     on the conversational path, make ONE LLM pass so the originating agent     REASONS over the result in its own voice (search -> reason -> answer), like an     agentic tool-use loop, instead of pasting raw links/page dumps verbatim.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `tier` | `str` | `'standard'` | — |  |
| `max_tokens` | `int` | `700` | — |  |

## `attachments`

AD-720: chat attachments configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `serve_remote_enabled` | `bool` | `False` | — |  |
| `auto_resolve_remote_enabled` | `bool` | `False` | — |  |
| `attachments_dir` | `str` | `'data/attachments'` | — |  |
| `max_attachment_bytes` | `int` | `10485760` | — |  |
| `allowed_mime_types` | `list[str]` | `['image/png', 'image/jpeg', 'image/webp', 'image/gif', 'application/pdf', 'text/plain', 'text/markdown', 'application/json', 'text/csv', 'audio/webm', 'audio/wav', 'audio/mpeg', 'audio/mp4', 'audio/ogg']` | — |  |
| `vision_tier` | `str` | `'vision'` | — |  |
| `text_extraction_max_bytes` | `int` | `1048576` | — |  |
| `pdf_extraction_enabled` | `bool` | `False` | — |  |
| `multi_image_warn_threshold` | `int` | `5` | — |  |
| `images_per_dm_hard_cap` | `int` | `8` | — |  |
| `image_max_dimension` | `int` | `1024` | — |  |
| `daily_image_budget_per_captain` | `int` | `50` | — |  |
| `image_budget_path` | `str | None` | `None` | — | AD-730-2-1: filesystem path for the per-Captain image-budget JSON sidecar. When None, defaults to ``<runtime.config.data_dir>/image_budget.json``. |
| `vision_tier_overrides` | `dict[str, str]` | `{}` | — |  |
| `max_store_bytes` | `int` | `5368709120` | ≥ 0 | AD-733-1: total bytes ceiling for attachments_dir. Reaper evicts oldest perception_frame entries first, then oldest chat_attachment entries, until under cap. 0 = disabled. |

## `cloud_pickers`

AD-720c: cloud file picker config (OAuth-bound). Default OFF.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-720c master switch. |
| `max_file_size_bytes` | `int` | `50000000` | ≥ 1 |  |
| `state_ttl_seconds` | `int` | `300` | ≥ 30 | AD-720c: CSRF state-token TTL (seconds). |

## `google_drive`

AD-720c: per-provider OAuth client credentials. Operator-supplied (BYOC).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-720c: enable this provider. |
| `client_id` | `str` | `''` | — | Operator-supplied OAuth client ID. |
| `client_secret` | `str` | `''` | — | Operator-supplied OAuth client secret. |
| `redirect_uri` | `str` | `'http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback'` | — | AD-720c: OAuth redirect URI; must match the registration at the provider. {provider} is substituted with the provider id. |

## `onedrive`

AD-720c: per-provider OAuth client credentials. Operator-supplied (BYOC).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-720c: enable this provider. |
| `client_id` | `str` | `''` | — | Operator-supplied OAuth client ID. |
| `client_secret` | `str` | `''` | — | Operator-supplied OAuth client secret. |
| `redirect_uri` | `str` | `'http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback'` | — | AD-720c: OAuth redirect URI; must match the registration at the provider. {provider} is substituted with the provider id. |

## `dropbox`

AD-720c: per-provider OAuth client credentials. Operator-supplied (BYOC).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-720c: enable this provider. |
| `client_id` | `str` | `''` | — | Operator-supplied OAuth client ID. |
| `client_secret` | `str` | `''` | — | Operator-supplied OAuth client secret. |
| `redirect_uri` | `str` | `'http://127.0.0.1:8081/api/cloud-pickers/{provider}/callback'` | — | AD-720c: OAuth redirect URI; must match the registration at the provider. {provider} is substituted with the provider id. |

## `lipsync`

AD-721b-1 — Server-side lip-sync backend selection.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `backend` | `Literal['heuristic', 'rhubarb']` | `'heuristic'` | — |  |
| `binary_path` | `str` | `'tools/rhubarb/rhubarb'` | — |  |
| `timeout_seconds` | `float` | `30.0` | — |  |
| `ffmpeg_binary_path` | `str` | `'tools/ffmpeg/ffmpeg'` | — |  |

## `tts`

AD-738 — Server-side TTS backend selection.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `backend` | `Literal['browser', 'piper']` | `'browser'` | — |  |
| `binary_path` | `str` | `'tools/piper/piper'` | — |  |
| `voice_model` | `str` | `'en_US-amy-medium'` | — |  |
| `voices_dir` | `str` | `'tools/piper/voices'` | — |  |
| `timeout_seconds` | `float` | `10.0` | — |  |
| `noise_scale` | `float` | `0.85` | — |  |
| `length_scale` | `float` | `1.0` | — |  |
| `noise_w` | `float` | `1.0` | — |  |
| `sentence_silence` | `float` | `0.35` | — |  |
| `sentence_pipelining_enabled` | `bool` | `False` | — |  |

## `spatial_explorer`

AD-520: Spatial Knowledge Explorer (Phase 1 Knowledge Graph View + Phase 2 Spatial Ship Layout).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `max_graph_edges` | `int` | `500` | ≥ 0, ≤ 5000 |  |
| `max_graph_nodes` | `int` | `200` | ≥ 0, ≤ 2000 |  |
| `spatial_layout_path` | `str` | `''` | — |  |

## `knowledge_browser`

AD-562: Ship's Records Knowledge Browser (Phases 1-4 OSS).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `max_graph_nodes` | `int` | `500` | ≥ 0, ≤ 2000 |  |
| `max_graph_edges` | `int` | `1000` | ≥ 0, ≤ 5000 |  |
| `jaccard_threshold` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 |  |
| `max_suggestions_per_entry` | `int` | `5` | ≥ 0, ≤ 50 |  |
| `index_refresh_seconds` | `int` | `300` | ≥ 10, ≤ 3600 |  |

## `extensions`

AD-481: Extension subsystem master config.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `enforce_sealed_core` | `bool` | `False` | — |  |
| `default_profile` | `str` | `'minimal'` | — |  |
| `extensions_dir` | `str` | `'src/probos/extensions'` | — |  |

## `observability_bridge`

AD-641a: Observability Bridge configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `publish_interval_seconds` | `float` | `60.0` | — |  |
| `system_channel` | `str` | `'system_observability'` | — |  |

## `threshold_alerts`

AD-695: Threshold-driven bridge alerts.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `pool_saturation_floor` | `float` | `0.9` | ≥ 0.0, ≤ 1.0 |  |
| `degradation_min_severity` | `str` | `'degraded'` | — |  |
| `attention_queue_depth` | `int` | `20` | ≥ 0 |  |
| `dedup_window_seconds` | `float` | `300.0` | ≥ 1.0 |  |

## `ward_room_hebbian`

AD-641b: Ward Room Hebbian Router configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `learning_rate` | `float` | `0.1` | — |  |
| `decay_factor` | `float` | `0.99` | — |  |

## `perception`

AD-733: visual sensor input from operator-side capture devices.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `explicit_share_enabled` | `bool` | `True` | — | AD-744: master switch for Captain-initiated 'Share to agent' shortcuts. Default-ON because getDisplayMedia requires a fresh browser-prompt consent on every invocation; toggle off for kiosk mode. |
| `camera_max_fps_server` | `int` | `4` | ≥ 1, ≤ 10 | Server-side hard cap on frame ingestion rate per session. |
| `screen_max_fps_server` | `int` | `2` | ≥ 1, ≤ 4 | AD-733-2: server-side hard cap on screen-frame ingestion rate per session. Independent of camera cap. |
| `frame_max_size_bytes` | `int` | `524288` | ≥ 4096, ≤ 5242880 | Reject frame uploads larger than this. Default 512 KB. |
| `frame_retention_seconds` | `int` | `300` | ≥ 30, ≤ 86400 | AD-733-1: TTL for perception-origin attachments. Default 5 min -- covers VisionConsumer WM window + AD-733c-1 force-describe cache. |
| `reaper_interval_seconds` | `int` | `60` | ≥ 10, ≤ 3600 | AD-733-1: how often the AttachmentReaper sweeps. Default 60s -- produces at most one full directory scan per minute. |
| `vision_consumer_enabled` | `bool` | `True` | — | Run the VisionConsumer that calls the vision LLM on supervisor-flagged frames. |
| `vision_min_interval_seconds` | `float` | `3.0` | ≥ 1.0, ≤ 120.0 | Minimum seconds between vision LLM calls per session. Cost-discipline floor. |
| `vision_novelty_threshold` | `float` | `0.08` | ≥ 0.0, ≤ 1.0 | Perceptual aHash diff threshold above which a frame is flagged as novel. Lower = more sensitive to small scene changes. BF-307: 0.08 default after empirical evidence that 0.15 was too high for static-camera setups. |
| `vision_baseline_max_age_seconds` | `float` | `30.0` | ≥ 0.0, ≤ 600.0 | BF-309: after this many seconds with no admit, the supervisor re-baselines on the next frame. Prevents static-scene anchoring where a steady pose makes every later frame look low-novelty against a stale baseline. 0 = disable. |
| `vision_supervisor_strategy` | `str` | `'ahash'` | — | AD-742d: frame-admission strategy. 'ahash' (default, perceptual-hash diff), 'motion' (per-pixel diff), 'scene_change' (HSV histogram delta), 'never' (drop all frames; describe only on force / DM), 'always' (admit all; debug/test only). Restart required to swap. |
| `working_memory_capacity` | `int` | `8` | ≥ 1, ≤ 64 | Per-agent vision working memory ring buffer size. |
| `wm_persistence_enabled` | `bool` | `True` | — | AD-742f: persist VisionWorkingMemory rings to data/perception_wm.db so Captain's per-agent visual history survives restart. Set False to operate in-memory only (legacy behavior). |
| `vision_tier` | `str` | `'vision'` | — | LLM tier name for narrative / proactive-observer vision calls (AD-733b scene-introduction + high-novelty triggers). Falls back to standard/deep behavior if vision_fast is unset. |
| `vision_fast_tier` | `str` | `'vision_fast'` | — | AD-742a (Wave 174): LLM tier for per-frame supervisor-flagged describe calls. Falls back to vision_tier when unconfigured (which itself honest-degrades). |
| `dm_force_describe_enabled` | `bool` | `True` | — | On every DM, synchronously describe the latest captured frame before composing the reply (4s timeout floor). |
| `prompt_freshness_seconds` | `float` | `120.0` | ≥ 0.0, ≤ 86400.0 | A vision observation older than this many seconds is treated as no-current-data (camera off) for prompt injection. 0 = disable the freshness guard (legacy behavior). |
| `engaged_idle_seconds` | `float` | `300.0` | ≥ 30.0, ≤ 3600.0 | ENGAGED -> AMBIENT after this many seconds of no DM activity. Default 5 min. |
| `ambient_idle_seconds` | `float` | `1800.0` | ≥ 60.0, ≤ 86400.0 | AMBIENT -> DORMANT after this many seconds in AMBIENT with no engagement signal. Default 30 min. |
| `idle_watchdog_tick_seconds` | `float` | `30.0` | ≥ 5.0, ≤ 300.0 | How often the controller's idle watchdog polls. Default 30s. |
| `captain_avatar_ref` | `str` | `''` | — | DEPRECATED (AD-742b): SHA-256 of a reference photo of the Captain in AttachmentStore. Use face-embedding enrollment instead. |
| `identity_match_threshold` | `float` | `0.6` | ≥ 0.0, ≤ 2.0 | Cosine distance threshold for face-embedding identity match. Smaller = stricter. facenet-pytorch VGGFace2-pretrained default: 0.6. Operator-tunable. |
| `identity_resolver_enabled` | `bool` | `True` | — | AD-742b: use face-embedding identity resolution. False = fall back to AD-733b LLM-prompt path (deprecated, expensive). |
| `proactive_observer_enabled` | `bool` | `True` | — | Allow the agent to proactively surface novel visual scenes in a DM. |
| `proactive_max_emissions` | `int` | `3` | ≥ 0, ≤ 20 | Maximum proactive vision DMs per session. |
| `proactive_dwell_seconds` | `float` | `30.0` | ≥ 5.0, ≤ 600.0 | Minimum seconds between consecutive proactive vision DMs. |
| `proactive_novelty_threshold` | `float` | `0.5` | ≥ 0.0, ≤ 1.0 | Minimum novelty score for a high-novelty proactive trigger (separate from supervisor admission threshold). |
| `engaged_budget_enforcement` | `bool` | `True` | — | AD-733c-6: when True, exceeding the per-session or per-day vision call cap in ENGAGED mode auto-drops to AMBIENT. False = counters-only behavior (AD-742e baseline). |
| `engaged_call_cap_per_session` | `int` | `200` | ≥ 10, ≤ 10000 | AD-733c-6: vision LLM calls per session in ENGAGED mode before auto-drop to AMBIENT. Captain default 200; tune via Settings or BF-308 hot-reload. |
| `engaged_call_cap_per_day` | `int` | `2000` | ≥ 50, ≤ 100000 | AD-733c-6: vision LLM calls per UTC day before auto-drop to AMBIENT. Captain default 2000. |
| `vad_engagement_enabled` | `bool` | `False` | — | AD-733c-7: enable Silero VAD as a secondary engagement trigger. Default OFF — endpoint exists but the browser never calls it. When enabled, browser POSTs speech-detected events to /api/perception/voice-activity which routes through the per-agent PerceptionEngagementRegistry (AD-733c-5). |
| `vad_min_speech_duration_ms` | `int` | `400` | ≥ 100, ≤ 2000 | AD-733c-7: browser-side debounce floor before firing the voice-activity endpoint. Prevents single-syllable false positives. |
| `source_fusion_enabled` | `bool` | `True` | — | AD-746 Layer 1: when ON, ambient camera + screen frames are buffered within ``fusion_window_ms`` and forwarded as a single fused vision_observation. Reduces AD-733c-6 budget burn + AD-541b anchor noise when both sources stream. Hot-reload. |
| `fusion_window_ms` | `int` | `800` | ≥ 100, ≤ 5000 | AD-746 Layer 1: debounce window for cross-source fusion. Pipecat default. Hot-reload. |

## `camera`

AD-733: client-side camera streaming controls.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `default_fps` | `int` | `1` | ≥ 1, ≤ 4 | Client-side capture cadence. Vision tier inference budget caps this; 1 fps is the safe default. |
| `frame_jpeg_quality` | `float` | `0.6` | ≥ 0.2, ≤ 0.95 |  |
| `frame_max_dimension` | `int` | `512` | ≥ 128, ≤ 1024 | Longest-edge downsample target for capture. |

## `screen`

AD-733-2: client-side screen-share streaming controls.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `default_fps` | `int` | `1` | ≥ 1, ≤ 4 | Client-side screen-capture cadence. Vision tier inference budget caps this; 1 fps is the safe default. |

## `wake_word`

AD-705c (Wave 179) — custom wake-word training pipeline config.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `wake_word_trainer_enabled` | `bool` | `False` | — |  |
| `custom_model_filename` | `str` | `'captain.onnx'` | — |  |
| `retain_training_samples` | `bool` | `False` | — |  |
| `training_samples_max_count` | `int` | `200` | — |  |
| `training_audio_max_bytes` | `int` | `1048576` | — |  |

## `engineering_sensors`

AD-641f: Engineering Chief Observability configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `report_interval_seconds` | `float` | `60.0` | — |  |
| `auto_start_periodic_report` | `bool` | `False` | — |  |

## `learned_shortcuts`

AD-641e: LearnedShortcut Registry configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `register_workflow_cache` | `bool` | `True` | — |  |

## `thread_priority`

AD-641c: Ward Room Thread Priority configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `weight_captain` | `float` | `0.3` | — |  |
| `weight_unresolved` | `float` | `0.2` | — |  |
| `weight_cross_department` | `float` | `0.15` | — |  |
| `weight_recency` | `float` | `0.2` | — |  |
| `weight_endorsement` | `float` | `0.15` | — |  |
| `captain_callsign` | `str` | `'Captain'` | — |  |

## `deliberation`

AD-641d: Crew Deliberation Protocol configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `captain_callsign` | `str` | `'Captain'` | — |  |

## `behavioral_metrics`

AD-569: Observation-Grounded Crew Intelligence Metrics.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `thread_lookback_hours` | `float` | `72.0` | — |  |
| `min_thread_contributors` | `int` | `2` | — |  |
| `min_thread_posts` | `int` | `3` | — |  |
| `frame_diversity_min_departments` | `int` | `2` | — |  |
| `synthesis_novelty_threshold` | `float` | `0.35` | — |  |
| `synthesis_min_thread_posts` | `int` | `4` | — |  |
| `trigger_correlation_window_hours` | `float` | `24.0` | — |  |
| `trigger_topic_similarity_threshold` | `float` | `0.6` | — |  |
| `convergence_similarity_threshold` | `float` | `0.75` | — |  |
| `convergence_min_agreeing` | `int` | `2` | — |  |
| `anchor_independence_min_episodes` | `int` | `3` | — |  |
| `max_snapshots` | `int` | `100` | — |  |

## `event_log`

Event log retention configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `retention_days` | `int` | `7` | — |  |
| `max_rows` | `int` | `100000` | — |  |
| `prune_interval_seconds` | `float` | `3600.0` | — |  |

## `cognitive_journal`

Cognitive Journal — append-only LLM reasoning trace store (AD-431).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `retention_days` | `int` | `14` | — |  |
| `max_rows` | `int` | `500000` | — |  |
| `prune_interval_seconds` | `float` | `3600.0` | — |  |

## `knowledge_edges`

Knowledge Edge Store — typed-triple graph (AD-687).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `db_path` | `str` | `'data/knowledge_edges.sqlite'` | — |  |
| `max_traverse_hops` | `int` | `3` | — |  |

## `knowledge_edge_classification`

AD-692: Classification enforcement on knowledge graph edges.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_classification` | `str` | `'private'` | — |  |

## `edge_backfill`

AD-689: One-shot backfill of ``knowledge_edges`` from existing data.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `run_on_warm_boot` | `bool` | `True` | — |  |
| `hebbian_threshold` | `float` | `0.5` | — |  |
| `force` | `bool` | `False` | — |  |
| `decisions_paths` | `list[str]` | `['DECISIONS.md', 'decisions-era-1-genesis.md', 'decisions-era-2-emergence.md', 'decisions-era-3-product.md', 'decisions-era-4-evolution.md']` | — |  |

## `communications`

Communications settings (AD-485).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `dm_min_rank` | `str` | `'ensign'` | — |  |
| `recreation_min_rank` | `str` | `'ensign'` | — |  |
| `group_chat_min_rank` | `str` | `'commander'` | — |  |
| `artifact_min_rank` | `str` | `'lieutenant'` | — |  |
| `artifact_max_per_turn` | `int` | `3` | — |  |
| `artifact_max_bytes` | `int` | `262144` | — |  |
| `a2ui_enabled` | `bool` | `False` | — | AD-811a: enable the [A2UI] choice widget on the 1:1 DM path (default OFF -> byte-identical). |
| `a2ui_min_rank` | `str` | `'lieutenant'` | — | AD-811a: min rank to emit an [A2UI] choice widget: ensign\|lieutenant\|commander\|senior |
| `a2ui_max_options` | `int` | `10` | ≥ 2, ≤ 20 | AD-811a: anti-flood cap on choice options honored per [A2UI] block (schema hard-caps at 20). |
| `room_todos_enabled` | `bool` | `False` | — | AD-1081: enable [TODOS]/[TODO_DONE]/[TODO_CONFIRM]/[TODO_REJECT] room-task tags (default OFF). |
| `room_todos_min_rank` | `str` | `'commander'` | — | AD-1081: min rank to seed the plan + confirm/reject Todos (the senior/facilitator): ensign\|lieutenant\|commander\|senior |
| `room_todos_seed_min_rank` | `str` | `'ensign'` | — | AD-1082: min rank to SEED the plan ([TODOS]) — open to any crew so the asked agent can plan; confirm/reject stay at room_todos_min_rank. |
| `office_backend` | `str` | `'python-docx'` | — | BF-646: Office doc backend: python-docx (default) \| libreoffice (headless soffice, higher fidelity, degrades if absent). |
| `libreoffice_path` | `str` | `''` | — | BF-646: explicit soffice/soffice.exe path; empty = auto-detect on PATH. |
| `status_min_rank` | `str` | `'lieutenant'` | — |  |
| `status_max_per_turn` | `int` | `3` | — |  |
| `status_max_bytes` | `int` | `4096` | — |  |
| `presence_working_window_seconds` | `float` | `90.0` | — |  |
| `proactive_conversation_enabled` | `bool` | `True` | — |  |
| `conversational_memory_enabled` | `bool` | `True` | — |  |
| `room_awareness_enabled` | `bool` | `True` | — |  |
| `recall_interpretation_enabled` | `bool` | `False` | — |  |
| `dream_interpretation_enabled` | `bool` | `False` | — |  |

## `workforce`

Workforce Scheduling Engine configuration (AD-496).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `tick_interval_seconds` | `float` | `10.0` | — |  |
| `default_capacity` | `int` | `1` | — |  |
| `custom_work_types` | `list[dict]` | `[]` | — |  |
| `custom_templates` | `list[dict]` | `[]` | — |  |
| `template_config_path` | `str` | `'config/work_templates.yaml'` | — |  |

## `temporal`

AD-502: Temporal awareness configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `include_birth_time` | `bool` | `True` | — |  |
| `include_system_uptime` | `bool` | `True` | — |  |
| `include_last_action` | `bool` | `True` | — |  |
| `include_post_count` | `bool` | `True` | — |  |
| `captain_timezone` | `str` | `''` | — |  |
| `include_episode_timestamps` | `bool` | `True` | — |  |

## `qualification`

Configuration for the Crew Qualification Battery (AD-566).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `baseline_auto_capture` | `bool` | `True` | — |  |
| `significance_threshold` | `float` | `0.15` | — |  |
| `test_timeout_seconds` | `float` | `60.0` | — |  |
| `enforcement_enabled` | `bool` | `False` | — |  |
| `enforcement_log_only` | `bool` | `True` | — |  |
| `drift_check_enabled` | `bool` | `True` | — |  |
| `drift_check_interval_seconds` | `float` | `604800.0` | — |  |
| `drift_warning_sigma` | `float` | `2.0` | — |  |
| `drift_critical_sigma` | `float` | `3.0` | — |  |
| `drift_min_samples` | `int` | `3` | — |  |
| `drift_history_window` | `int` | `20` | — |  |
| `drift_cooldown_seconds` | `float` | `3600.0` | — |  |
| `drift_check_tiers` | `list[int]` | `[1, 2, 3]` | — |  |
| `peer_observation_module_path` | `str` | `'config/manuals/peer_observation_conduct.yaml'` | — | AD-729b: training module YAML path. Loaded at Boot Camp graduation gate when peer_observation_certification_required is True. |
| `peer_observation_certification_required` | `bool` | `False` | — | AD-729b: when True, Boot Camp / Qualification gates block advancement unless the peer-observation conduct module is passed. Default False — flips to True after AD-729a Standing Orders ship. |

## `communication_benchmarks`

AD-642: Communication Quality Benchmarks configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `frequency_hours` | `float` | `12.0` | — |  |
| `probes` | `list[str]` | `['thread_relevance', 'memory_grounding', 'memory_absence', 'expertise', 'silence_appropriateness', 'dm_action']` | — |  |

## `orientation`

AD-567g: Cognitive re-localization configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `orientation_window_seconds` | `float` | `600.0` | — |  |
| `cold_start_full_orientation` | `bool` | `True` | — |  |
| `warm_boot_orientation` | `bool` | `True` | — |  |
| `proactive_supplement` | `bool` | `True` | — |  |
| `populate_watch_section` | `bool` | `True` | — |  |
| `populate_ward_room_department` | `bool` | `True` | — |  |
| `populate_event_log_window` | `bool` | `True` | — |  |

## `social_verification`

AD-567f: Social Verification Protocol configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `corroboration_threshold` | `float` | `0.4` | — |  |
| `corroboration_max_agents` | `int` | `5` | — |  |
| `corroboration_min_confidence` | `float` | `0.3` | — |  |
| `cascade_enabled` | `bool` | `True` | — |  |
| `cascade_independence_threshold` | `float` | `0.3` | — |  |
| `cascade_cooldown_seconds` | `float` | `300.0` | — |  |
| `anomaly_window_discount` | `float` | `0.5` | — |  |
| `provenance_version_independence_weight` | `float` | `0.7` | — |  |
| `provenance_validation_enabled` | `bool` | `True` | — |  |
| `expose_episode_content` | `bool` | `False` | — |  |

## `anomaly_window`

Anomaly window detection configuration (AD-673).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_window_duration_seconds` | `float` | `1800.0` | — |  |
| `lookback_seconds` | `float` | `60.0` | — |  |

## `working_memory`

AD-573: Unified agent working memory configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `token_budget` | `int` | `3000` | — |  |
| `max_recent_actions` | `int` | `10` | — |  |
| `max_recent_observations` | `int` | `5` | — |  |
| `max_recent_conversations` | `int` | `5` | — |  |
| `max_events` | `int` | `10` | — |  |
| `proactive_budget` | `int` | `1500` | — |  |
| `stale_threshold_hours` | `float` | `24.0` | — |  |
| `conclusion_ttl_seconds` | `float` | `1800.0` | — |  |
| `max_conclusions` | `int` | `20` | — |  |
| `duty_budget` | `int` | `600` | — |  |
| `social_budget` | `int` | `800` | — |  |
| `ship_budget` | `int` | `800` | — |  |
| `engagement_budget` | `int` | `800` | — |  |

## `predictive_branching`

AD-633 v1: Predictive Cognitive Branching.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `cache_ttl_seconds` | `float` | `60.0` | ≥ 1.0 |  |
| `cache_max_entries` | `int` | `128` | ≥ 1 |  |
| `speculation_tokens_per_window` | `int` | `2000` | ≥ 0 |  |
| `speculation_window_seconds` | `float` | `300.0` | ≥ 1.0 |  |
| `flush_rate_feedback_threshold` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 |  |
| `flush_rate_window_seconds` | `float` | `3600.0` | ≥ 1.0 |  |
| `accuracy_ring_size` | `int` | `100` | ≥ 10 |  |
| `cheap_tier_min_confidence` | `float` | `0.3` | ≥ 0.0, ≤ 1.0 |  |
| `standard_tier_min_confidence` | `float` | `0.7` | ≥ 0.0, ≤ 1.0 |  |
| `anticipatory_tier_min_confidence` | `float` | `0.85` | ≥ 0.0, ≤ 1.0 |  |

## `self_improvement`

AD-482 v1: Self-improvement pipeline (proposal -> approval -> QA -> evolution -> versioning).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `qa_pool_size` | `int` | `3` | ≥ 1, ≤ 8 |  |
| `iteration_cap` | `int` | `5` | ≥ 1, ≤ 20 |  |
| `evolution_half_life_seconds` | `float` | `2592000.0` | ≥ 1.0 |  |
| `evolution_collection_name` | `str` | `'self_improvement_lessons'` | — |  |
| `persistence_root_dir` | `str` | `'src/probos/agents/designed'` | — |  |

## `memory_budget`

AD-573: Memory budget accounting across recall tiers.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `total_budget_tokens` | `int` | `4650` | — |  |
| `l0_budget` | `int` | `150` | — |  |
| `l1_budget` | `int` | `3000` | — |  |
| `l2_budget` | `int` | `1000` | — |  |
| `l3_budget` | `int` | `500` | — |  |

## `metabolism`

AD-670: Working memory metabolism — active lifecycle management.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `decay_half_life_seconds` | `float` | `3600.0` | — |  |
| `forget_threshold` | `float` | `0.05` | — |  |
| `min_entries_per_buffer` | `int` | `2` | — |  |
| `audit_enabled` | `bool` | `True` | — |  |
| `cycle_interval_seconds` | `float` | `300.0` | — |  |
| `triage_fullness_threshold` | `float` | `0.8` | — |  |
| `triage_base_score` | `float` | `0.3` | — |  |

## `pinned_knowledge`

AD-579a: Pinned knowledge buffer configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_tokens` | `int` | `150` | — |  |
| `max_pins` | `int` | `10` | — |  |
| `default_ttl_seconds` | `float` | `86400.0` | — |  |

## `temporal_validity`

AD-579b: Temporal validity windows for episodic memory.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_validity_hours` | `float` | `0.0` | — |  |

## `task_context`

Task-contextual standing orders configuration (AD-586).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `orders_dir` | `str` | `'config/task_orders'` | — |  |
| `max_tokens` | `int` | `500` | — |  |

## `question_adaptive`

AD-602: Question-adaptive retrieval strategy configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `strategy_overrides` | `dict[str, dict]` | `{}` | — |  |

## `storage_gate`

AD-610: Utility-based storage gating - write-time validation.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `duplicate_threshold` | `float` | `0.95` | — |  |
| `utility_floor` | `float` | `0.2` | — |  |
| `recent_window` | `int` | `50` | — |  |
| `contradiction_check_enabled` | `bool` | `True` | — |  |

## `salience`

AD-668: Salience filter for working memory promotion.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `weights` | `dict[str, float]` | `{'relevance': 0.3, 'recency': 0.25, 'novelty': 0.15, 'urgency': 0.2, 'social': 0.1}` | — |  |
| `threshold` | `float` | `0.3` | — |  |
| `background_max_entries` | `int` | `50` | — |  |

## `sensorium`

AD-666/AD-1122: Agent Sensorium tracking configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `warning_chars` | `int` | `10000` | — |  |
| `warning_cooldown_seconds` | `float` | `21600.0` | — |  |
| `warning_rearm_ratio` | `float` | `0.9` | — |  |
| `warning_escalation_ratio` | `float` | `1.25` | — |  |
| `top_contributors` | `int` | `5` | — |  |

## `source_tracing`

AD-583g: Ward Room echo detection and source tracing.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `echo_min_chain_length` | `int` | `3` | — |  |
| `echo_similarity_threshold` | `float` | `0.4` | — |  |
| `echo_analysis_enabled` | `bool` | `True` | — |  |

## `observable_state`

AD-583f: Observable state verification.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `verification_enabled` | `bool` | `True` | — |  |
| `max_claims_per_thread` | `int` | `10` | — |  |

## `llm_rate`

AD-617: LLM call rate governance configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `rpm_fast` | `int` | `120` | — |  |
| `rpm_standard` | `int` | `120` | — |  |
| `rpm_deep` | `int` | `30` | — |  |
| `max_wait_seconds` | `float` | `30.0` | — |  |
| `cache_max_entries` | `int` | `500` | — |  |
| `per_agent_hourly_token_cap` | `int` | `0` | — |  |
| `max_concurrent_calls` | `int` | `6` | — |  |
| `interactive_reserved_slots` | `int` | `2` | — |  |
| `max_inflight_per_endpoint` | `int` | `8` | — |  |
| `endpoint_failure_cooldown_seconds` | `float` | `15.0` | ≥ 0.0, ≤ 300.0 |  |

## `sub_task`

AD-632a: Sub-task protocol configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `chain_timeout_ms` | `int` | `30000` | — |  |
| `step_timeout_ms` | `int` | `15000` | — |  |
| `max_chain_steps` | `int` | `6` | — |  |
| `fallback_on_timeout` | `str` | `'single_call'` | — |  |
| `max_concurrent_chains` | `int` | `4` | — |  |
| `nats_publish_enabled` | `bool` | `False` | — |  |
| `nats_payload_max_bytes` | `int` | `16384` | — |  |

## `boot_camp`

AD-638: Cold-start boot camp configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_episodes` | `int` | `5` | — |  |
| `min_ward_room_posts` | `int` | `3` | — |  |
| `min_dm_conversations` | `int` | `1` | — |  |
| `min_trust_score` | `float` | `0.55` | — |  |
| `min_time_minutes` | `int` | `60` | — |  |
| `timeout_minutes` | `int` | `120` | — |  |
| `nudge_cooldown_seconds` | `int` | `600` | — |  |

## `ship_state_snapshot`

AD-683: Ship State Snapshot for Cold-Start Onboarding.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `tiered_trust`

AD-640: Role-based trust initialization tiers.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `bridge_alpha` | `float` | `4.5` | — |  |
| `bridge_beta` | `float` | `1.0` | — |  |
| `chief_alpha` | `float` | `3.0` | — |  |
| `chief_beta` | `float` | `1.0` | — |  |
| `bridge_pools` | `list[str]` | `['counselor', 'yeoman']` | — |  |
| `bridge_callsigns` | `list[str]` | `['Meridian', 'Yeo']` | — |  |
| `chief_callsigns` | `list[str]` | `['Bones', 'LaForge', 'Number One', 'Worf', "O'Brien"]` | — |  |

## `chain_tuning`

AD-639: Trust-adaptive chain personality tuning.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `low_trust_ceiling` | `float` | `0.6` | — |  |
| `high_trust_floor` | `float` | `0.75` | — |  |

## `chain_optimizer`

AD-659 v1 + AD-659b: Cognitive Chain Self-Optimization service.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `analysis_window` | `int` | `100` | — |  |
| `latency_p95_ms_floor` | `float` | `10000.0` | — |  |
| `success_rate_floor` | `float` | `0.7` | — |  |
| `error_rate_ceiling` | `float` | `0.3` | — |  |
| `min_samples_per_group` | `int` | `20` | — |  |
| `apply_enabled` | `bool` | `False` | — |  |
| `analysis_interval_seconds` | `int` | `0` | — |  |

## `chain_optimizer_counselor`

AD-659c v1: OptimizationCounselor watchdog for AD-659b applied proposals.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `baseline_window_seconds` | `float` | `1800.0` | — |  |
| `observation_window_seconds` | `float` | `1800.0` | — |  |
| `success_rate_drop_floor` | `float` | `0.1` | — |  |
| `min_samples_per_window` | `int` | `20` | — |  |
| `auto_revert_enabled` | `bool` | `False` | — |  |

## `causal_reasoning`

AD-660 v1 + AD-660b: Agent Causal Reasoning Framework.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_tokens` | `int` | `700` | — |  |
| `tier` | `str` | `'standard'` | — |  |
| `max_invocations_per_hour` | `int` | `5` | — |  |

## `diagnostic_context`

AD-661 v1 + AD-661b/c: Diagnostic Context Service — pull-based bundle assembly.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_budget_tokens` | `int` | `8000` | — |  |
| `chain_trace_ratio` | `float` | `0.3` | — |  |
| `procedure_ratio` | `float` | `0.25` | — |  |
| `episode_ratio` | `float` | `0.25` | — |  |
| `records_ratio` | `float` | `0.2` | — |  |
| `chars_per_token` | `int` | `4` | — |  |
| `redistribute_remainder` | `bool` | `True` | — |  |

## `nl_graph_query`

AD-691 v1: NL-to-Graph Query Service.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_max_hops` | `int` | `2` | — |  |
| `default_limit` | `int` | `10` | — |  |
| `llm_tier` | `str` | `'standard'` | — |  |
| `extraction_max_tokens` | `int` | `600` | — |  |
| `synthesis_max_tokens` | `int` | `800` | — |  |

## `clinical_telemetry`

AD-635 / AD-635b / AD-635c: Clearance-gated clinical query facade (Medical / Counselor).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `audit_max_entries` | `int` | `1000` | — |  |
| `audit_persistence_enabled` | `bool` | `False` | — |  |
| `audit_db_path` | `str` | `'data/clinical_audit.db'` | — |  |
| `circuit_breaker_history_persistence_enabled` | `bool` | `False` | — |  |
| `circuit_breaker_history_db_path` | `str` | `'data/circuit_breaker_history.db'` | — |  |

## `consultation_workspaces`

AD-594a v1: Session-scoped consultation workspace registry.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `root_path` | `str` | `'consultations'` | — |  |
| `input_processor` | `str` | `'passthrough'` | — |  |

## `consultation_delivery`

AD-594d v1: Consultation delivery pipeline.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `local_file_enabled` | `bool` | `True` | — |  |
| `github_enabled` | `bool` | `True` | — |  |
| `local_file_allowed_roots` | `list[str]` | `[]` | — |  |
| `github_token_env` | `str` | `'GITHUB_TOKEN'` | — |  |
| `default_requires_approval` | `bool` | `False` | — |  |

## `consultation_dispatch`

AD-594c v1: Parallel execution dispatch.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_work_type` | `str` | `'duty'` | — |  |
| `default_tags` | `list[str]` | `['consultation']` | — |  |
| `blocker_threshold_seconds` | `float` | `600.0` | — |  |
| `progress_subscription_enabled` | `bool` | `True` | — |  |
| `decomposer` | `Literal['markdown', 'llm']` | `'markdown'` | — |  |
| `max_subtasks` | `int` | `12` | — |  |
| `decomposer_tier` | `str` | `'standard'` | — |  |

## `capability_triage`

AD-854: Acquire-vs-build triage grant fast-path gating.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `grant_fast_path_enabled` | `bool` | `False` | — |  |
| `grant_trust_floor` | `float` | `0.8` | — |  |

## `agentic_dispatch`

AD-856: Gate the AgenticLoop execution path for dispatched work items.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `max_parallel_subtasks` | `int` | `3` | ≥ 1, ≤ 64 |  |
| `max_convergence_rounds` | `int` | `2` | — |  |
| `orchestrator_enabled` | `bool` | `False` | — |  |
| `max_active_crew_sessions` | `int` | `2` | ≥ 1, ≤ 32 |  |
| `crew_resume_scan_limit` | `int` | `100` | ≥ 1, ≤ 1000 |  |
| `crew_ingress_scan_limit` | `int` | `100` | ≥ 1, ≤ 1000 |  |
| `crew_ingress_semantic_call_limit` | `int` | `32` | ≥ 1, ≤ 128 |  |
| `crew_ingress_semantic_threshold` | `float` | `0.9` | ≥ 0.0, ≤ 1.0 |  |
| `crew_provisioning_repair_limit` | `int` | `100` | ≥ 1, ≤ 1000 |  |
| `crew_recovery_max_retries` | `int` | `3` | ≥ 0, ≤ 10 |  |
| `crew_recovery_initial_backoff_seconds` | `float` | `5.0` | ≥ 0.0, ≤ 3600.0 |  |
| `crew_recovery_max_backoff_seconds` | `float` | `300.0` | ≥ 0.0, ≤ 86400.0 |  |
| `crew_compaction_enabled` | `bool` | `False` | — | AD-1142: compact a crew child's working context when it crosses crew_compaction_threshold_tokens, instead of letting it grow until the provider rejects the request. Default-OFF per convention #14 — with the gate off no compactor is threaded to the child's AgenticLoop at all and the run is byte-identical to pre-AD-1142. Compaction is BEST-EFFORT: a single AD-1147 tool-call group is preserved whole, so one turn's fan-out can exceed any threshold, in which case the loop warns and continues rather than retrying. Compaction is a context-window mechanism, NOT a transparency one: it drops assistant reasoning text, the flattened prompt and the summary itself, and NONE of those are recorded in any durable store. Only tool OUTPUTS survive, bounded, via the AD-1151 tool trace. |
| `crew_compaction_threshold_tokens` | `int` | `60000` | ≥ 1000, ≤ 1000000 | AD-1142: the crew child's working-context ceiling, in estimated tokens. Measures OCCUPANCY of the message list (content plus the serialised tool_calls array), not cumulative spend — see crew_token_budget for the spend ceiling. Crossing it shrinks the history and continues. 60000 is a STARTING VALUE, NOT A DERIVED ONE: the SWE harness compacts at 0.8 x 100000, and crew children run up to max_parallel_subtasks concurrently (default 3), so 60000 is 180000 of simultaneous provider load at the default fan-out. It is the first knob to tune if children still fail with stopped_reason='error'. AD-1147 interaction: one turn appends up to agentic_loop.max_parallel_tool_calls results, so with agentic_loop.tool_result_max_chars at 0 (unbounded, the shipped default) a SINGLE turn can cross any threshold and compaction cannot converge. With a non-zero tool_result_max_chars the per-turn ceiling is max_parallel_tool_calls x tool_result_max_chars characters, which must stay comfortably under crew_compaction_threshold_tokens x 4 for compaction to converge; at the AD-1147 ceiling of 16 that is 16 x the cap. There is deliberately no validator relating them — the relation is stated here and asserted in tests. Only consulted when crew_compaction_enabled is True. |
| `crew_token_budget` | `int | None` | `None` | ≥ 1024 | AD-1142: cumulative-spend ceiling for one crew child, in tokens. None (the default) means no budget, which is today's behaviour. This is a HARD STOP, not a shrink: crossing it returns stopped_reason='token_budget', which crew_executor maps to status='failed', so the child's DEPENDENTS STAY BLOCKED and no partial output is persisted as done. That consequence is why it defaults to None. It is INDEPENDENT of crew_compaction_enabled — a Safety Budget ceiling is useful with or without compaction, and gating it on the compaction flag would mean enabling compaction silently introduced a new failure mode. The two knobs are different mechanisms: crew_compaction_threshold_tokens is a working-context ceiling (cross it, shrink and continue); this is a spend ceiling (cross it, stop and fail). AD-1155 interaction: when crew_loop_until_done_enabled is True this budget is SHARED across the outer iterations and carried forward as a remainder, never reset per iteration, so iterations 2+ run with LESS room than the first one. It is a ceiling, not an allowance. |
| `crew_loop_until_done_enabled` | `bool` | `False` | — | AD-1155: re-invoke a crew child that stopped without finishing, with a fresh independently governed run each time, bounded by crew_loop_until_done_max_iterations. Default-OFF per convention #14 — with the gate off the child runs exactly once and the call is byte-identical to pre-AD-1155. This does NOT replace SubtaskVerifier.converge_for_session, which is a separate LIVE outer loop driven by an LLM judge on the finalizer path; the two compose, and the four-way worst case in crew_loop_until_done_max_iterations assumes they do. Only a stopped_reason the executor classifies as re-invokable is ever re-run, which today is max_iterations ALONE: token_budget is a spend ceiling the operator set, error is usually provider-window exhaustion that a longer prompt makes worse, and complete means the model chose to stop. |
| `crew_loop_until_done_max_iterations` | `int` | `2` | ≥ 1, ≤ 5 | AD-1155: the hard outer cap on how many times ONE crew child is run. 1 means no re-invocation, identical to today; the cap is a bound, never an enable — crew_loop_until_done_enabled is what turns the feature on. WORST CASE, STATED PLAINLY: per outer iteration a child gets AGENTIC_MAX_ITERATIONS (25) turns, and one turn can carry up to agentic_loop.max_parallel_tool_calls (ceiling 16) concurrent tool calls, so at this ceiling of 5 that is 5 x 25 x 16 = 2000 tool invocations FOR ONE CHILD — before max_parallel_subtasks (default 3, ceiling 64) multiplies it across siblings and before converge_for_session adds up to 8 correction rounds on the finalizer path. That is the four-way product: convergence x outer x inner x parallel. There is deliberately no validator relating these fields — the relation is stated here and asserted in tests, because a cross-field validator would turn an unrelated POST /config into a 422. |
| `crew_loop_until_done_predicate` | `str` | `'stopped_reason'` | — | AD-1155: which completion predicate decides whether to re-invoke. An enum string, never an operator-supplied callable, which would be an arbitrary-code seam on the crew hot path. 'stopped_reason' (the default) continues only when the run was cut off by the turn counter — the one unambiguous signal. 'completion_marker' continues while crew_loop_until_done_completion_marker is absent from the trailing output; its weakness is that nothing teaches the agent to emit the marker on the FIRST pass, so a single-iteration run can never satisfy it. 'open_todos' continues while the PARENT work item has a checklist step in pending / in_progress / rejected; it is OPT-IN and INAPPLICABLE to the crew path as shipped — the crew fan-out never writes WorkItem.steps (steps move through the DM reply pipeline's [TODO_*] tags, which a crew child never enters), so a child with no checklist STOPS rather than being re-invoked forever. 'submitted' steps are excluded from 'actionable' because closing one needs rank >= communications.room_todos_min_rank, which the modal crew agent does not hold. An unknown value degrades to 'stopped_reason'. |
| `crew_loop_until_done_completion_marker` | `str` | `'TASK COMPLETE'` | — | AD-1155: the exact line the 'completion_marker' predicate looks for in the trailing 200 characters of a child's output. Only consulted when crew_loop_until_done_predicate is 'completion_marker', in which case the continuation block tells the agent to emit it. An empty or malformed value degrades to the default rather than to '', because an empty marker is contained in every string and would silently disable the predicate the operator just armed. |

## `hybrid_dispatch`

AD-581 v1: Hybrid dispatch routing policy (581a + 581d).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `confidence_threshold` | `float` | `0.4` | — |  |
| `confidence_margin` | `float` | `0.05` | — |  |
| `min_hebbian_weight` | `float` | `0.05` | — |  |
| `success_rate_window` | `int` | `50` | — |  |
| `min_samples_for_routing` | `int` | `3` | — |  |
| `dispatchable_tags` | `list[str]` | `['consultation']` | — |  |

## `work_board_reconciler`

AD-876: periodic + warm-boot work-board reconciliation (Quartermaster).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `interval_seconds` | `int` | `300` | ≥ 30, ≤ 3600 |  |
| `warm_boot` | `bool` | `True` | — |  |
| `scan_limit` | `int` | `200` | ≥ 1, ≤ 2000 |  |
| `max_reconcile_attempts` | `int` | `3` | ≥ 1, ≤ 20 |  |
| `reconcile_backoff_seconds` | `int` | `600` | ≥ 0, ≤ 86400 |  |
| `min_item_age_seconds` | `int` | `30` | ≥ 0, ≤ 600 |  |
| `reactive_reclaim` | `bool` | `False` | — |  |
| `stall_timeout_seconds` | `int` | `0` | ≥ 0, ≤ 86400 |  |

## `process_chain_registry`

AD-647b v1: Registry of named process chains (`ProcessChainDefinition`).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `knowledge_loading`

AD-585: Tiered knowledge loading configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `ambient_token_budget` | `int` | `200` | — |  |
| `contextual_token_budget` | `int` | `400` | — |  |
| `on_demand_token_budget` | `int` | `600` | — |  |
| `ambient_max_age_seconds` | `float` | `300.0` | — |  |
| `contextual_max_age_seconds` | `float` | `60.0` | — |  |
| `on_demand_max_age_seconds` | `float` | `0.0` | — |  |
| `intent_knowledge_map` | `dict[str, list[str]]` | `{'security_alert': ['trust', 'agents'], 'proactive_think': ['episodes', 'proactive'], 'ward_room_notification': ['episodes', 'agents'], 'direct_message': ['episodes', 'agents']}` | — |  |

## `step_instruction`

AD-651: Step-specific standing order decomposition.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — |  |
| `step_categories` | `dict[str, list[str]]` | `{'query': [], 'analyze': ['observation_guidelines', 'situation_assessment', 'when_to_act_vs_observe', 'memory_anchoring', 'source_attribution', 'self_monitoring'], 'compose': ['communication_style', 'personality_expression', 'audience_awareness', 'ward_room_actions', 'knowledge_capture', 'duty_reporting'], 'evaluate': ['self_monitoring', 'scope_discipline', 'communication_style'], 'reflect': ['self_monitoring', 'scope_discipline', 'knowledge_capture']}` | — |  |
| `universal_categories` | `list[str]` | `['identity', 'chain_of_command', 'core_directives', 'encoding_safety']` | — |  |
| `log_token_savings` | `bool` | `True` | — |  |

## `agent_tiers`

Agent tier classification for trust separation (AD-571).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `crew_types` | `list[str]` | `['architect', 'builder', 'code_reviewer', 'counselor', 'diagnostician', 'surgeon', 'pharmacist', 'pathologist', 'red_team', 'system_qa', 'scout', 'data_analyst', 'systems_analyst', 'research_specialist']` | — |  |
| `core_types` | `list[str]` | `['event_log', 'vitals_monitor', 'introspect']` | — |  |

## `operational_status`

Operational status tracker configuration (AD-571b).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `sample_window_size` | `int` | `50` | — |  |
| `available_success_rate` | `float` | `0.85` | — |  |
| `degraded_p95_latency_ms` | `float` | `5000.0` | — |  |
| `offline_consecutive_errors` | `int` | `5` | — |  |

## `risk_tiers`

Action Risk Tier configuration (AD-676).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `elevated_min_trust` | `float` | `0.0` | — |  |
| `critical_min_trust` | `float` | `0.7` | — |  |

## `procedural_bridge`

Episodic-procedural bridge configuration (AD-572).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_cross_cycle_episodes` | `int` | `5` | — |  |
| `novelty_threshold` | `float` | `0.3` | — |  |

## `nats`

NATS event bus configuration (AD-637).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | Enable NATS event bus. Overridden by PROBOS_NATS_ENABLED env var. |
| `url` | `str` | `'nats://localhost:4222'` | — |  |
| `connect_timeout_seconds` | `float` | `5.0` | — |  |
| `max_reconnect_attempts` | `int` | `60` | — |  |
| `reconnect_time_wait_seconds` | `float` | `2.0` | — |  |
| `drain_timeout_seconds` | `float` | `5.0` | — |  |
| `jetstream_enabled` | `bool` | `True` | — |  |
| `jetstream_domain` | `str | None` | `None` | — |  |
| `subject_prefix` | `str` | `'probos.local'` | — |  |
| `js_publish_timeout` | `float` | `5.0` | — |  |

## `bill`

Configuration for the Bill System runtime (AD-618b).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `max_concurrent_instances` | `int` | `10` | — |  |
| `default_step_timeout_seconds` | `float` | `300.0` | — |  |
| `allow_partial_assignment` | `bool` | `False` | — |  |

## `consultation`

AD-594: Crew Consultation Protocol configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `timeout_seconds` | `float` | `30.0` | — |  |
| `max_consultations_per_agent_per_hour` | `int` | `20` | — |  |
| `max_pending_requests` | `int` | `10` | — |  |
| `expert_selection_max_candidates` | `int` | `5` | — |  |
| `weight_capability_match` | `float` | `0.5` | — |  |
| `weight_trust` | `float` | `0.3` | — |  |
| `weight_billet_relevance` | `float` | `0.2` | — |  |

## `expertise`

AD-600: Transactive Memory expertise directory configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_topics_per_agent` | `int` | `50` | — |  |
| `min_confidence` | `float` | `0.1` | — |  |
| `decay_rate` | `float` | `0.95` | — |  |
| `top_k_experts` | `int` | `3` | — |  |

## `creative_expression`

Configuration for AD-525 v1 (Skills Inventory + Records Output).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `default_classification` | `Literal['ship', 'department', 'private']` | `'ship'` | — |  |

## `classification_gate`

Configuration for AD-530 v1 disclosure gate.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `autonomy_boundaries`

AD-511 v1: Agent Autonomy Boundaries (registry + observational detector).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `crew_development`

AD-507 v1: Crew Development Framework (Core Knowledge Curriculum Registry).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `boot_camp_phase`

AD-509 v1: Boot Camp Phase Tracker (in-memory observational).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `discovery_learning`

AD-512 v1: Discovery-Based Capability Building substrate (observational).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `confidence_prior_alpha` | `float` | `1.0` | ≥ 0.01 |  |
| `confidence_prior_beta` | `float` | `1.0` | ≥ 0.01 |  |
| `zpd_lower_bound` | `float` | `0.4` | ≥ 0.0, ≤ 1.0 |  |
| `zpd_upper_bound` | `float` | `0.75` | ≥ 0.0, ≤ 1.0 |  |

## `scoped_cognition`

AD-508 v1: Duty Scope helper (read-only observational).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |

## `workspace_ontology`

AD-478 v1: Workspace Ontology read-only register (frequency-bounded).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_terms` | `int` | `1000` | — |  |

## `gap_pipeline_extensions`

AD-539c + AD-539d v1 config (observational gap pipeline extensions).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `remediation_tracker_enabled` | `bool` | `True` | — |  |
| `fleet_aggregator_enabled` | `bool` | `True` | — |  |
| `remediation_max_history` | `int` | `100` | — |  |
| `active_remediation_enabled` | `bool` | `False` | — |  |

## `spreading_activation`

AD-604: Spreading activation / multi-hop retrieval configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `max_hops` | `int` | `2` | — |  |
| `k_per_hop` | `int` | `5` | — |  |
| `hop_decay_factor` | `float` | `0.6` | — |  |
| `min_anchor_fields` | `int` | `2` | — |  |

## `thought_store`

AD-606: Think-in-Memory thought storage configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_importance` | `int` | `5` | — |  |
| `max_thoughts_per_cycle` | `int` | `3` | — |  |

## `retroactive`

AD-608: Retroactive memory evolution - store-time metadata propagation.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `neighbor_k` | `int` | `5` | — |  |
| `similarity_threshold` | `float` | `0.7` | — |  |
| `max_relations_per_episode` | `int` | `10` | — |  |
| `propagate_watch_section` | `bool` | `True` | — |  |
| `propagate_department` | `bool` | `True` | — |  |

## `distillation`

AD-609: Multi-faceted distillation configuration.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `min_failure_cluster_size` | `int` | `3` | — |  |
| `comparative_enabled` | `bool` | `True` | — |  |

## `reconsolidation`

AD-574: Episodic decay reconsolidation scheduling.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `base_intervals_hours` | `list[float]` | `[1.0, 6.0, 24.0, 72.0, 168.0, 720.0]` | — |  |
| `importance_scale_factor` | `float` | `0.1` | — |  |
| `max_scheduled` | `int` | `500` | — |  |

## `naval_organization`

Naval Organization Protocols (AD-477) — v1 ships Captain's Log + Plan of the Day.

## `captains_log`

Captain's Log daily-narrative configuration (AD-477).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `output_dir` | `pathlib.Path` | `'data/captains_log'` | — |  |
| `end_of_day_hour` | `int` | `23` | — |  |
| `top_episodes_count` | `int` | `5` | — |  |
| `importance_threshold` | `int` | `5` | — |  |

## `plan_of_day`

Plan of the Day morning-summary configuration (AD-477).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `output_dir` | `pathlib.Path` | `'data/plan_of_day'` | — |  |
| `start_of_day_hour` | `int` | `8` | — |  |
| `include_alert_conditions` | `bool` | `True` | — |  |

## `self_distillation`

Configuration for AD-487 self-distillation v1 (Map step only).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `rate_limit_hours` | `int` | `24` | — |  |
| `llm_timeout_seconds` | `float` | `30.0` | — |  |
| `max_sub_topics` | `int` | `5` | — |  |
| `db_path` | `pathlib.Path` | `'data/agent_probes.db'` | — |  |

## `spc`

AD-522 v1: Statistical Process Control (calibration profile + WE rules).

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `True` | — |  |
| `sample_window` | `int` | `100` | — |  |

## `desktop`

AD-751: Desktop UX Surface — tray, hotkey, notifications, autostart.

| Field | Type | Default | Bounds | Description |
|---|---|---|---|---|
| `enabled` | `bool` | `False` | — | AD-751: master switch for desktop surface. Default OFF (Wave 10 convention #14). |
| `tray_autostart` | `bool` | `True` | — | Auto-start tray icon on boot when desktop enabled. |
| `hotkey` | `str` | `'ctrl+shift+space'` | — | Global hotkey to activate mini-mode (pynput syntax). |
| `notification_timeout_sec` | `int` | `5` | ≥ 1, ≤ 60 | Toast notification display duration (seconds). |
| `quiet_hours_start` | `str` | `'19:00'` | — | Start of quiet hours (HH:MM format, local time). |
| `quiet_hours_end` | `str` | `'08:00'` | — | End of quiet hours (HH:MM format, local time). |
| `lock_file` | `str` | `'~/.probos/yeo.lock'` | — | Single-instance lock file path. |
| `autostart_enabled` | `bool` | `False` | — | Register for OS autostart on boot. |
