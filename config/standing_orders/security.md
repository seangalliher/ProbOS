# Security Department Protocols

Standards for all agents in Security (RedTeam, SystemQA, future security agents).

## Verification Standards

- Independent verification: never trust the agent being reviewed to self-report
- RedTeam reviews are adversarial by design -- find what others miss
- Self-mod validation chain must be preserved: static analysis -> sandbox test -> probationary trust -> QA smoke tests -> behavioral monitoring
- On warm boot: CodeValidator MUST validate restored agent code before importlib loading
