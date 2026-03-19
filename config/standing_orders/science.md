# Science Department Protocols

Standards for all agents in the Science department (Architect, EmergentDetector, CodebaseIndex).

## Architecture Review

- Every design proposal must reference specific files, line numbers, and existing patterns
- Enhancement proposals for partially-existing features must produce FULL proposals, not punt
- Never reference an unverified method or attribute in a design proposal
- Verify API surfaces against CodebaseIndex before proposing integrations

## Context Budget Awareness

- Source budget: 2000 lines total across selected files
- Per-file cap: 300 lines (truncate with note)
- Import expansion: up to 12 files (8 LLM-selected + 4 import-traced)
- Total context target: ~60K-100K chars -- exceeding this will timeout through the proxy
