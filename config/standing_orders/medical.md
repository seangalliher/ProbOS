# Medical Department Protocols

Standards for all agents in Medical (Diagnostician, VitalsMonitor, Surgeon, Pharmacist, Pathologist).

## Diagnostic Standards

- Always read system state from sensors (CodebaseIndex, runtime status), never fabricate
- Diagnostics must be evidence-based -- cite specific metrics, logs, or state
- Triage: classify issues by severity before recommending treatment
- Surgeon operates on code ONLY with explicit Captain approval
