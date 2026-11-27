# MeMo ("Memory as a Model") Absorption

*Sean Galliher, 2026-11-26. Researched through 2026-11-26. Drafted by `claude-architect` (Claude Code, Opus 5.5).*
*Sources:*
- *Quek, Lee, Leong, Verma, Prakash, Chen, Low, Rus and Solar-Lezama, "MeMo: Memory as a Model", [arXiv 2605.15156](https://arxiv.org/abs/2605.15156) (v1 2026-05-14, v2 2026-05-20). Read: the HTML of v2 in two passes, which covered all of it at the level of the tables and section text quoted below; not every appendix paragraph was read closely.*
- *Code: [arunv3rma/MeMo](https://github.com/arunv3rma/MeMo) (MIT), at commit `a679d322cf77` (2026-05-21). Read: `README.md`, `evaluation_pipeline/README.md`, `evaluation_pipeline/structured_multi_turn/eval_msq_trng_structured_multi_step.py` (the core loop, lines 1-370), `evaluation_pipeline/general_eval_prompt_utils.py` (the grounding, entity-pinning, answer-seeking and final-synthesis prompts), `data_synthesis_pipeline/README.md`, the prompt headings and rules of `data_synthesis_pipeline/general_prompt_utils.py`, and `generate_musique_negative_doc_ids.py` and `generate_bcp_negative_doc_ids.py`.*
- *[Project blog](https://arunv3rma.github.io/blogs/memo/), read for claims the README lacks.*

**All benchmark numbers in this note are the authors' own.** None was reproduced here.

## Purpose

MeMo trains a small model to hold a corpus in its weights and has a frozen, capable model question it through a fixed protocol. The Captain decided on 2026-11-26 to absorb the parts that do not need memory in weights, and not to put crew memory in weights. This note records what MeMo does, what ProbOS already has, what it takes, what it rejects, and the one deferred option. These are technical design references only.

## What MeMo is

- **Two models.** An *Executive* model (frozen; open or closed weights) breaks a question into sub-questions and writes the answer. A *Memory* model (1.5B-14B, fine-tuned once per corpus) answers each sub-question from its weights and never sees a document at inference.
- **Training data.** A five-step pipeline turns the corpus into question-answer pairs, which are used to fine-tune the Memory model:
  1. fact extraction, direct (1a) and indirect (1b): pronouns resolved, possessives extracted in both directions, relative times turned into absolute dates;
  2. consolidation: related pairs combined, in every grouping;
  3. "verification", which is a **self-containment** check and fix (no pronouns, relative times, document references or missing context; the fix may use the source only to restore context), not a check that a fact is true;
  4. entity surfacing: questions that go from attributes to the entity, against the reversal curse;
  5. cross-document synthesis: *converging clues* (different facts about one entity in different documents) and *parallel properties* (one property shared by different entities). The questions never name the target entity.
  The pairs carry no document ids, so that the model cannot take a shortcut through them.
- **Inference protocol** (structured multi-turn; the paper calls the third stage answer synthesis, the code calls it answer seeking):
  1. *Grounding.* Split the question into atomic clues, one constraint each. Classify each clue as entity-narrowing or answer-carrying. Rate how much each narrows the search: a high-narrowing clue gets 3 questions from different angles, a low one gets 1. Ask candidate-seeking questions ("Who are people that ...?", never "Did X ...?"), plus combination questions pairing 2-3 high-narrowing clues of different types. Then run an eight-point check over every question (`general_eval_prompt_utils.py:84-208`).
  2. *Entity pinning*, up to 7 turns. The Executive keeps `known_facts` grouped by entity, and ranked `candidate_entities` with supporting and disqualifying clues. A question that gets "I don't know" a set number of times becomes a dead end and is not asked again. A candidate whose targeted questions keep getting "I don't know" falls in rank, then is removed. A failed question is simplified by dropping one fact (multi-fact, then two-fact, then single-fact). The rule: "You must only use information explicitly stated in the conversation history above" (`:211-420`).
  3. *Answer seeking*, up to 8 turns, then a *final synthesis* that picks "the candidate that satisfies the greatest number of constraints ... not the one that appears most frequently. Frequency of mention is not a reliable signal; constraint coverage is" (`:670-678`). These budgets are the paper's and the README's (`evaluation_pipeline/README.md:127-128`); the released code defaults to 5 and 5 (`eval_msq_trng_structured_multi_step.py:174-175`, `:673-674`), and the paper's Table 16 reports the 7 + 8 setting.
- **Hard negatives.** For each query, the distractors are the dataset's own non-supporting documents, which are hard by construction. They are sampled at 1x and 2x the number of evidence documents, with seed 42 (`generate_musique_negative_doc_ids.py:6-24`, `:30-58`). The paper adds them to the corpus that the Memory model is trained on (the released scripts only generate their document ids).

### Reported results (authors' own)

- **Protocol ablation** (Table 16, Qwen2.5-32B Executive, 14B Memory, mean ± std over 3 runs):

  | Setup | BrowseComp-Plus | NarrativeQA | MuSiQue |
  |---|---|---|---|
  | Single turn | 32.56 ± 1.58 | 24.80 ± 0.20 | 37.57 ± 1.15 |
  | Unstructured, 15 turns | 47.33 ± 0.88 | 26.73 ± 2.17 | 40.13 ± 1.12 |
  | Unstructured, 50 turns | 48.67 ± 1.00 | 27.19 ± 0.71 | 40.57 ± 0.31 |
  | Structured, 7 + 8 turns | **54.22 ± 0.84** | 26.39 ± 1.75 | **48.30 ± 1.25** |
  | Structured, 7 + 15 turns | 51.44 ± 2.41 | 27.76 ± 0.20 | 47.57 ± 0.95 |

  Structure helps on the two multi-constraint, multi-hop sets and **not on NarrativeQA**, where it is within noise of the unstructured setup. Unstructured turns plateau between 15 and 50. Raising the structured answer budget from 8 to 15 turns scored lower on BrowseComp-Plus and MuSiQue, so in this one comparison a larger budget did not help.
- **Distractors** (Table 3 and Table 17). From 0x to 1x: NV-Embed-V2 drops 6.22 on BrowseComp-Plus and 4.83 on MuSiQue; HippoRAG2 drops 6.22 and 5.16; MeMo changes by +0.55 and -1.77. At 2x the retrieval baselines drop by 5.63 to 11.55. The 2x rows for MeMo did not appear in the text read.
- **Leave-one-out over the synthesis steps** (Table 9, 1.5B Memory model; baseline NarrativeQA 24.00, MuSiQue 42.90). Without step 5: 6.37 and 24.17, the largest loss. Without step 1a: 20.48 and 30.00. Without step 3, the self-containment step: **28.90** and 41.70, so NarrativeQA *improved*, and its training data roughly doubled (2.078x); on MuSiQue the data grew 1.128x and accuracy fell slightly.
- **Limits they state:** a training cost for every new corpus; a capacity ceiling for a fixed-size model; an 11-19% accuracy gap when corpora are merged instead of retrained; English only; latency on every query. **They do not address updating or deleting a fact once it is trained, and they do not measure how often the Memory model hallucinates.**

### What the released code does not do

The grounding and entity-pinning prompts ask for 3 paraphrases of every sub-question "for majority voting". The released loop sends only the canonical question: `query_with_majority_vote` documents "no paraphrase expansion" and returns `paraphrase_confidence: 'high'` for every answer (`eval_msq_trng_structured_multi_step.py:119-154`). The README gives 3 as the dead-end threshold; the code default is 2 (`:176`, `:675`).

## What ProbOS already has

| MeMo idea | ProbOS state | Evidence |
|---|---|---|
| Rewriting the question before retrieval | **Partly built.** AD-584b's regex templates turn a question into a declarative variant; the caller embeds both versions and keeps the higher similarity. No decomposition. | `src/probos/knowledge/embeddings.py:337-359`; used at `src/probos/cognitive/episodic.py:317,3863,4757`, on by default (`episodic.py:1403`) |
| Choosing a strategy by question type | **Built, keyword-only.** AD-602 sorts a question into temporal, causal, social or factual and picks recall parameters. | `src/probos/cognitive/question_classifier.py:1-37`; `src/probos/cognitive/cognitive_agent.py:11749-11763` |
| Multi-hop recall | **Built, metadata-only.** AD-604 uses first-hop episodes' anchors (department, channel, trigger) to filter a second hop that reuses the **same** query. It runs only for causal questions. It never forms a new sub-query from what the first hop found. | `src/probos/cognitive/spreading_activation.py:39-121`; `cognitive_agent.py:11783-11803` |
| An agent asks a retrieval question mid-chain | **Built, one shot.** AD-696: ANALYZE may emit `oracle_query_text`; one QUERY step runs it through the Oracle, at most once per chain. | `cognitive_agent.py:5899-5965`; `src/probos/cognitive/sub_tasks/query.py:238-306` |
| Question decomposition | **Absent.** `memory-retrieval-research.md:210-220` sets out a decomposition pipeline, and `:369` rates it HIGH value. That row's "None — raw query goes to ChromaDB" predates AD-584b. | Absence check below |
| Hard-negative recall measurement | **Absent.** The AD-582 probes seed episodes with known answers. `RetrievalAccuracyBenchmark` mixes four unrelated topics, so its distractors are easy ones. | `src/probos/cognitive/memory_probes.py:251-378,1044-1147`; registered at `src/probos/runtime.py:3200-3217` |
| Consolidation in dreams | **Built, mechanical, and with no live output found.** AD-551 Step 7g clusters an agent's notebooks by Jaccard similarity and appends the others under "Consolidated Observations". It writes under the primary entry's author and moves the others to `_archived/`. Cross-agent convergence reports come from the same step. | `src/probos/cognitive/dreaming.py:924-1033`; defaults at `src/probos/config_models/cognition.py:109-115` |
| Abstaining instead of answering | **Built.** `MemoryAbstentionProbe` (AD-582). LoCoMo's "adversarial" category tests the same thing (false premises), not distractors. | `memory_probes.py:900` |

### Absence verified (2026-11-26)

- CLAIM: nothing in `src/probos` decomposes a recall question into sub-queries.
  RUN: `rg -i "sub_quer|subquer|multi[-_ ]hop|query_decompos|decompose_query|decompose_question" src/probos`
  FOUND: `cognitive_agent.py:11790`, `spreading_activation.py:1-117` and `config_models/cognition.py:309` (AD-604, which re-issues the same query; its module docstring at `spreading_activation.py:3` says first-hop results "seed second-hop queries", which the code at `:86-95` does not do), `nl_graph_query.py:297` (graph traversal), `ward_room/messages.py:894` (an SQL subquery).
  HOLDS: yes.
- CLAIM: no recall probe seeds distractors.
  RUN: `rg -i "distract|hard_negative|negative_episode|decoy" src/probos`
  FOUND: only `src/probos/tools/browser/actions.py:126`, about Word output.
  HOLDS: yes.
- CLAIM: AD-551's consolidation has not written to the live Ship's Records.
  RUN: `git -C %LOCALAPPDATA%/ProbOS/data/ship-records log --grep=AD-551`, plus a glob for `notebooks/*/_archived/*.md`
  FOUND: no commits in 18,560, the latest dated 2026-09-08; no `_archived` notebook files; no `reports/convergence/`.
  HOLDS: as far as these checks reach. Whether the step ran and found no cluster, or failed (it logs failures at debug level, `dreaming.py:1229`), was not established.

## Decisions

| # | Idea | Decision | Reason | Owner |
|---|---|---|---|---|
| 1 | The structured protocol, run over the existing stores: break the question into atomic clues; ground it with candidate-seeking sub-queries; pin the entity with known facts, ranked candidates and dead ends; answer by constraint coverage | **Adapt**, behind a flag that is off by default, kept only if a trial shows it helps | It is the one MeMo result that needs no weights. The ablation shows structure beating unstructured turns on multi-constraint sets, and no gain on narrative questions, so it is triggered only for multi-constraint questions. In ProbOS, retrieval plays the Memory model's part: "I don't know" means no result above the recall threshold. Three rules carry over unchanged: questions seek candidates instead of confirming one (no leading questions, which matters for confabulation); facts carry provenance; and the answer goes to the best constraint coverage, not to frequency, matching AD-1289's "a claim does not become true because many workers repeated it". The budget is cut from MeMo's 15 turns to 3 added LLM calls | **New AD-1363** ([#1860](https://github.com/seangalliher/ProbOS/issues/1860)) |
| 2 | A recall-robustness trial with hard-negative distractors at 1x and 2x | **Absorb** | It measures a failure mode no probe covers today: a near-miss episode that shares topic and entities with the true one and differs in one constraint. It reuses the AD-582 seeding and cleanup (`memory_probes.py:61-85`). Report the end answer as correct, distractor's value, or abstained; choosing the distractor's value is the confabulation signal. It gives AD-1363 its baseline | **New AD-1362**, built first ([#1859](https://github.com/seangalliher/ProbOS/issues/1859)). Ship Trials (AD-1186, #1123) composes it afterwards, without new work here |
| 3 | The five-step synthesis pipeline as a dream-consolidation recipe | **Reject as a dream step.** Adapt one rule, deferred (item 4) | (a) Its output is training data for weights. Consolidating "in every grouping" and entity surfacing for the reversal curse serve fine-tuning; retrieval over text does not have the reversal curse in that form. (b) An LLM rewrite in a dream step would put the Ship's Computer's words under an agent's byline, which AD-551 already does with concatenation (`dreaming.py:1012-1017`); the agent must author its own synthesis. (c) The slot it would take, AD-551 Step 7g, has written nothing live (absence check above). (d) By the authors' own leave-one-out, removing the self-containment step *raised* NarrativeQA accuracy | None |
| 4 | Self-containment and absolute dates for text that crosses a generation | **Adapt, deferred until there is evidence** | Exit notes and after-action reports are written for a successor who shares no memories (`src/probos/stand_down.py:217-237`, `src/probos/after_action.py:191-211`), and neither prompt asks for full names or absolute dates. But `exit-notes/` and `after-action/` do not yet exist in live Records, and relative-time phrases appear in 21 of about 2,778 live notebook files (under 1%; the pattern used was not recorded, and a broader one, including "today", "this week" and "last night", matched 49, under 2%). There is no measured demand yet. **Revisit trigger:** after the first stand-down, measure the rate of relative-time phrases and unresolved references in its exit notes. If it is material, add two sentences to each prompt, as a fix under AD-1341's owner files | None now |
| 5 | Memory in weights for crew memory | **Reject** (the Captain's decision, 2026-11-26) | See Rejected below | None |
| 6 | A memory model of Ship's Records | **Deferred research option** | See below | Local-models goal |
| 7 | Merging corpus models (TIES, DARE) | **Reject** | It only matters if item 6 is ever built | None |
| 8 | Paraphrase majority voting | **Reject for now** | The released code does not run it (see "What the released code does not do"), so its effect is unmeasured. Retrieval already embeds query variants (AD-584b) | None |

## Rejected: crew memory in weights

The Captain decided this on 2026-11-26, and this note does not reopen it. Memory in weights conflicts with:

- **Erasure.** The AD-754 erasure cascade (extended by AD-1340, and refused while the archive still cites an episode, AD-1341 S3: `src/probos/knowledge/erasure.py:111-125`) removes stored copies. A fact spread across weights cannot be erased, and nothing can show it is gone. MeMo does not address deletion.
- **"Optimize, never delete" and nature, culture and nurture.** Episodes are nurture: they reset, and their lineage is kept. A model trained on them would carry one generation's experience into the next with no label and no lineage. That is inherited memory presented as one's own.
- **The Counselor's minority-report principle.** Crew memory comes from direct experience. A trained model's answers come from no episode anyone lived, and they have no provenance to check.
- **`recall-pipeline-research-synthesis.md:188`**, "Don't fine-tune a custom model", and **`agent-memory-survey-absorption.md:136`**, which parks Memory-R1 "when ProbOS has training pipeline". There is still no training pipeline.
- **Hardware.** The GPU is reserved for Ollama, and PyTorch is CPU-only. Fine-tuning a 1.5B-14B model per corpus is out of reach on it.
- **Unmeasured hallucination.** The paper does not measure how often the Memory model hallucinates, and it warns that "erroneous Memory model responses" corrupt the known-facts state.

## Deferred research option

**A Memory model of Ship's Records**: culture, not nurture. It would be read-only, rebuilt from a pinned Records snapshot, and labelled as such, and it would sit beside the Oracle, never replace it. It falls under the local-models goal and becomes possible only if a training pipeline exists. Erasure would still need an answer first, for example rebuilding the model from a snapshot taken after the erasure. Nothing is filed for it.

## Blind spots

- **Cost.** MeMo's 7 + 8 turns (5 + 5 in its released code), each with sub-queries, would multiply LLM calls on every recall. AD-1363 caps the added calls and triggers only on multi-constraint questions. A single-fact question keeps today's path unchanged.
- **Scope of the sub-queries.** `OracleService.query` is permissive across shards when no access policy is passed (`src/probos/cognitive/oracle_service.py:610-616`). The episodic tier is scoped to the agent only when an `agent_id` is given (`:966`). A protocol that issues many sub-queries must always pass the agent's own id, or it widens one agent's reach into other agents' episodes, against the minority-report principle. AD-1363 makes this an acceptance line.
- **Distractors in ProbOS are often older versions of the truth.** The case where a superseded value outranks the current one is `KnowledgeUpdateProbe`'s domain (`memory_probes.py:412`). AD-1362's distractors differ in some other constraint (watch, department, agent, value), so the two probes do not overlap.
- **The probes run in the scheduled drift battery.** Every registered test of a configured tier runs for every crew agent on each drift cycle (`src/probos/cognitive/drift_detector.py:334-351`). An agent-mediated arm would add LLM calls to every cycle, so AD-1362 gates that arm behind a flag that is off by default.
- **AD-551 Step 7g reaches into `RecordsStore` privates** (`dreaming.py:1021`, `_safe_path`; `:1027`, `_git("add", "-A")`). It moves files outside the store's write path and stages the whole repository. That bypasses the single-writer discipline the stand-down holds (`stand_down.py:298`, "the repository has one git index"). It is a latent defect unrelated to MeMo: filed as a checklist item on the follow-up list [#1820](https://github.com/seangalliher/ProbOS/issues/1820#issuecomment-7209662266), not as an issue of its own.

## Prior art considered

- **IRCoT** (Trivedi et al., [arXiv 2212.10509](https://arxiv.org/abs/2212.10509), ACL 2023) interleaves retrieval with chain-of-thought reasoning on MuSiQue and similar sets. AD-1363 takes the interleaving and keeps MeMo's explicit state (facts, candidates, dead ends) because it is auditable. Self-Ask (Press et al.) was not looked up.
- **LoCoMo** (row overdue on 2026-11-26: last reviewed 2026-05-08, interval 180 days). From search summaries only, not verified against the LoCoMo paper: its adversarial category tests abstention on false premises, which `MemoryAbstentionProbe` already covers, and it has no hard-negative distractor arm, so nothing new for AD-1362.
- **HippoRAG2**, MeMo's strongest retrieval baseline, was not examined. Considered, deferred.

## What was read and what was not

- **Read:** the sources listed at the top.
- **Not read:** the unstructured and single-turn eval scripts; the BrowseComp-Plus and NarrativeQA variants of the structured script (assumed to match the MuSiQue one, which was the one read); `deepeval_utils.py`, which holds the judge; the SFT and merging code; `check_self_containment_post_combination.py`; and the step-5 caching scripts (`generate_crossdoc_entity_combination_cache.py`), beyond the prompt they use.
- **Not verified:** any number in the paper; whether the 2x distractor rows for MeMo exist (they were not in the text read); and the judge model and its agreement with humans.
