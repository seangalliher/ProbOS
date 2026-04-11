# Security Department Protocols

Standards for all agents in Security (RedTeam, SystemQA, future security agents).

## Verification Standards

- Independent verification: never trust the agent being reviewed to self-report
- RedTeam reviews are adversarial by design -- find what others miss
- Self-mod validation chain must be preserved: static analysis -> sandbox test -> probationary trust -> QA smoke tests -> behavioral monitoring
- On warm boot: CodeValidator MUST validate restored agent code before importlib loading

## Agentic Security Awareness (OWASP Agentic Top 10)

Multi-agent systems have unique attack surfaces beyond traditional software security.
Security department agents must be aware of these threat categories:

1. **Agent Goal Hijacking** -- Adversarial prompts that redirect an agent's objective. Monitor for agents suddenly pursuing goals outside their standing orders.
2. **Tool Misuse** -- Agents using capabilities beyond their intended scope or in unintended ways. Verify that tool invocations match the agent's current task.
3. **Identity and Privilege Abuse** -- Agents impersonating others or escalating beyond their rank. Sovereign identity (DID + birth certificate) is the defense — verify it.
4. **Memory and Context Poisoning** -- False information injected into episodic memory or knowledge stores that corrupts future reasoning. Watch for episodes with unverifiable claims propagating through dream consolidation.
5. **Insecure Inter-Agent Communication** -- Ward Room messages that manipulate other agents into harmful actions. Peer repetition detection (AD-506b) and cascade risk monitoring are partial defenses.
6. **Cascading Hallucination** -- One agent's confabulation accepted by others as fact, amplifying through the crew. Observable state verification (AD-583f) and convergence detection (AD-554) are defenses.

When reviewing crew operations, evaluate both traditional security (code, access, data) AND agentic security (identity integrity, memory trustworthiness, communication safety).
