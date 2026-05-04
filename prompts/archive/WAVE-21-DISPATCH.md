# Wave 21 — AD-522 v1 Statistical Process Control (Calibration + Western Electric Rules)

**Date:** 2026-05-03
**Mode:** Architect first (review), then Builder (build).
**Closes GH issue:** #97.

---

Standard wave shape. Stages: draft → precheck → review_1 → revision → review_2 → gate_1 → build → verify_build → gate_2 → push → gate_3 → close → retrospective → done.

v1 ships 2 of 5 capabilities (calibration profile + 4 of 8 Western Electric rules). AD-522b/c/d/e deferred.

Per Wave 5 convention #14 aggressive pre-deferral. EmergentDetector integration deferred to AD-522c. Holodeck calibration deferred to AD-522e.

Test target: ~21 tests. Public attribute `runtime.spc_calibration_store` (no underscore). 1 new EventType (`SPC_RULE_VIOLATED`).
