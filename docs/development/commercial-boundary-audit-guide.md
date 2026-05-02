# Commercial Boundary Audit Guide

**Purpose:** prevent commercial details (pricing, revenue model, customer counts, go-to-market) from leaking into the public OSS repo.

This is a **process guide**, not the audit itself. The audit data lives in the private `probos-commercial` repo at `commercial-boundary-audit.md`. This file documents the audit's structure and the boundary rule so OSS contributors know what's expected.

## Boundary Rule (canonical)

See `.github/copilot-instructions.md` § "Repository Boundary — OSS vs Commercial". The hard rule:

> Any `*(Commercial)*` AD entry in the public roadmap describes the **extension point only** — what the feature is, what it connects to, what OSS infrastructure it builds on. Pricing, revenue model, customer counts, professional-services positioning, and go-to-market language all belong in the private `commercial-roadmap.md`.

## What Triggers an Audit

Run a commercial-boundary audit before any of the following is committed to `main`:

1. New AD entries in `docs/development/roadmap.md` tagged `*(Commercial)*` or `*(planned, Commercial)*`.
2. Bulk roadmap drafting events (the wave 1-4 sweep that drafted 20 ADs at once was an audit-triggering event).
3. Post-merge spot checks every time a `*(Commercial)*` AD is updated.

## Audit Pattern (per commercial-tagged AD)

For each `*(Commercial)*` AD entry in the public roadmap, the private audit document records:

| Column | Meaning |
|---|---|
| AD number | e.g., AD-449, AD-450 |
| Public-repo summary | One-line what the public entry says |
| Pricing exposure? | Yes / No — does the public entry mention dollar figures? |
| Customer naming exposure? | Yes / No — does the public entry name customers, deals, or pilots? |
| Go-to-market language? | Yes / No — does the public entry describe sales motion or positioning? |
| Revenue model exposure? | Yes / No — does the public entry describe how the feature is monetized (subscription, license, services)? |
| Last reviewed | Date |
| Status | Clean / Needs redaction / Redacted |

A public AD passes audit if all four exposure columns are "No".

## Detection Patterns (what to grep for)

When auditing, run these checks against `docs/development/roadmap.md`:

```pwsh
# Dollar-figure detection
Select-String -Pattern '\$\d+[KMB]?' docs/development/roadmap.md

# Subscription / license language
Select-String -Pattern '/year|/month|per-month|per-year|annual license|subscription|managed service' docs/development/roadmap.md

# Customer / deal naming
Select-String -Pattern 'reference engagement|first customer|pilot customer|design partner|case study' docs/development/roadmap.md

# Revenue projections
Select-String -Pattern 'revenue|ARR|MRR|TAM|SAM|expected to generate' docs/development/roadmap.md
```

False positives are common (e.g., "OpenTelemetry traces" matches "trace" in some contexts). The architect runs these as a triage filter, not a hard gate.

## What Goes Where

| Information type | OSS repo (this one) | Private commercial repo |
|---|---|---|
| Architectural extension point | ✅ | ✅ |
| Code that implements the OSS half | ✅ | ❌ |
| Code that implements the commercial half | ❌ | ✅ |
| Feature description (what it does) | ✅ | ✅ (with commercial detail) |
| Pricing tiers and dollar figures | ❌ | ✅ |
| Sales positioning / GTM motion | ❌ | ✅ |
| Customer count / deal pipeline | ❌ | ✅ |
| Competitive analysis tables | ❌ | ✅ |
| OSS tier feature list | ✅ | ✅ (mirrored) |
| Commercial tier feature list | ❌ (just "see commercial repo") | ✅ |
| Migration path OSS → commercial | ✅ (technical) | ✅ (with sales context) |

## Historical Failures

These are the boundary failures that have happened on this repo, documented here so they don't repeat:

- **AD-450 pricing leak (2026-05-01).** AD-450 entry in `roadmap.md:4113` contained per-entity configuration ($5K-25K), managed service ($2K-5K/month), and Ship Class license ($10K/year) figures, plus "First Nooplex professional services reference engagement" framing. Tagged `*(Commercial)*` but contained commercial details inline. Survived the wave 1-4 commercial-boundary review undetected. Redacted on 2026-05-01 in commit `ed78d4f`. The 3-week public exposure window cannot be retracted from forks (2 forks, 6 stars). Force-rewriting history was rejected as a louder signal than the original leak. Hard rule added to `.github/copilot-instructions.md` to prevent recurrence.

If a new boundary failure happens, add it here with date, location, exposure window, and the commit that redacted it.

## Related Process

- The pre-commit deletion sanity check in `prompts/BUILDER-EXECUTION-PLAN.md` catches *deletions* but does NOT catch *additions* of commercial details. Commercial-boundary auditing is the additive equivalent.
- Architect-drafted prompts and roadmap edits should be checked against this guide before commit, not after.

## Maintenance

This guide is updated when:
- A new boundary-failure category is discovered.
- The grep pattern set needs new entries (e.g., new financial vocabulary).
- The "What Goes Where" matrix needs a new row for a previously-undocumented information type.

The guide does NOT contain the audit itself — that's in the private repo. This file documents the *process*, not the *data*.
