# PROV-O provenance mapping (AD-1145)

ProbOS projects provenance it **already persists** onto the
[W3C PROV-O vocabulary](https://www.w3.org/TR/prov-o/) as JSON-LD, so stock RDF
tooling can read it. The projection lives in `src/probos/knowledge/provo.py`.

It is a **pure function over data already written**. It performs no I/O, emits
no events, adds no instrumentation, and imports nothing from `probos` — so it
can be vendored verbatim by a third-party harness, exactly as
`federation/ard/jcs.py` can (AD-1144 DD-1). Not called ⇒ zero cost, and the
system behaves byte-identically.

Two surfaces carry PROV-O's Agent / Activity / Entity triad in full.

## A. Crew execution evidence

Source: the frozen 14-key `crew_execution` record built in
`cognitive/crew_executor.py`. Projected by `project_crew_execution(record)`.

| PROV-O term | ProbOS field |
|---|---|
| `prov:Activity` | `work_item_id` |
| `prov:Agent`, `prov:SoftwareAgent` | `assigned_to` |
| `prov:wasAssociatedWith` | Activity → Agent |
| `prov:wasInformedBy` | `parent_id` |
| `prov:Entity` + `prov:wasGeneratedBy` | each `artifact_refs[].content_hash` |
| `prov:used` | `tool_trace_ref` |
| `prov:startedAtTime` / `prov:endedAtTime` | `started_at` / `finished_at` |

## B. Ship's Records frontmatter

Source: the frontmatter written by `knowledge/records_store.py`. Projected by
`project_record_frontmatter(path, frontmatter)`.

| PROV-O term | ProbOS field |
|---|---|
| `prov:Entity` | the record, at one revision |
| `prov:wasAttributedTo` | `author` |
| `prov:generatedAtTime` | `created` |
| `prov:wasRevisionOf` | `revision` (n → n−1) |

A record `author` is typed `prov:Agent` only — never `prov:SoftwareAgent` —
because the author may be the human Captain, and this surface cannot tell.
A crew `assigned_to` is a crew agent, so it carries both types.

## What is deliberately **not** projected: token counts

`tokens_used` is **excluded**, and a test asserts the strings `tokens_used`
and `token_source` appear nowhere in projected output.

PROV-O has no term for a token count, but that is the lesser reason. The real
one is that at this surface the number's provenance is **unknowable**.
Following BF-680 a token count may be a client-side *estimate* rather than a
provider *measurement*. `WorkItemAgenticOutcome.token_source` records which —
but it lives in memory only and is dropped before persistence, because the
14-key `crew_execution` set is frozen and has no room for the label. So the
persisted record carries the integer without the fact that qualifies it.

Projecting it would publish an estimate as a measurement. The honest answer is
silence. Deciding where `token_source` should live is tracked separately, as
the prerequisite for any metrics export.

## IRIs

IRIs are opaque, deterministic and namespaced under `urn:probos:`:

- `urn:probos:activity:{work_item_id}`
- `urn:probos:agent:{assigned_to | author}`
- `urn:probos:entity:{sha256}`

For artifacts and tool traces the `{sha256}` is the full 64-hex digest already
in the record. For a Ship's Record it is `sha256("record:{path}@{revision}")` —
the path is **hashed rather than embedded** so no filesystem path appears in an
IRI, and the revision is included so `prov:wasRevisionOf` links two distinct
entities. The pre-image is documented here precisely so any consumer can
reproduce the IRI.

`cognitive/provenance.py`'s `compute_content_hash` is **not** used anywhere in
this projection: it truncates to `hexdigest()[:8]`, 32 bits, which is unusable
as a global identifier.

## Honest omission

A field that is absent, empty or ill-typed produces **no triple** — never a
placeholder. `assigned_to = None` yields no `prov:Agent` node and no
`prov:wasAssociatedWith` edge, so a consumer can distinguish *unattributed*
from *attributed to unknown*. Nothing raises: a malformed record projects to a
smaller document, and a record whose identity is unknowable projects to an
empty graph.

Every term the module can emit is in the explicit `PROV_TERMS` allowlist; a
test asserts both that emitted terms are a subset of it and that the allowlist
is exactly the thirteen real PROV-O terms above.

## Optional exposure

`GET /api/records/documents/{path}?format=prov-jsonld` returns the table-B
projection for one record. The parameter is **default-OFF**: absent it, the
response body is unchanged and the projection is never invoked. No other
endpoint, route or default response body is affected.

## Worked example — crew execution

For a completed child work item `WI-7.2` (parent `WI-7`, assigned to `scotty`,
one artifact, one tool trace):

```json
{
  "@context": {
    "prov": "http://www.w3.org/ns/prov#",
    "xsd": "http://www.w3.org/2001/XMLSchema#"
  },
  "@graph": [
    {
      "@id": "urn:probos:activity:WI-7.2",
      "@type": "prov:Activity",
      "prov:wasAssociatedWith": { "@id": "urn:probos:agent:scotty" },
      "prov:wasInformedBy": { "@id": "urn:probos:activity:WI-7" },
      "prov:used": { "@id": "urn:probos:entity:aaaa...aaaa" },
      "prov:startedAtTime": {
        "@value": "2025-07-08T18:40:00.500000+00:00",
        "@type": "xsd:dateTime"
      },
      "prov:endedAtTime": {
        "@value": "2025-07-08T18:42:03.250000+00:00",
        "@type": "xsd:dateTime"
      }
    },
    {
      "@id": "urn:probos:agent:scotty",
      "@type": ["prov:Agent", "prov:SoftwareAgent"]
    },
    { "@id": "urn:probos:activity:WI-7", "@type": "prov:Activity" },
    { "@id": "urn:probos:entity:aaaa...aaaa", "@type": "prov:Entity" },
    {
      "@id": "urn:probos:entity:bbbb...bbbb",
      "@type": "prov:Entity",
      "prov:wasGeneratedBy": { "@id": "urn:probos:activity:WI-7.2" }
    }
  ]
}
```

`tokens_used: 18342` was present in the source record and is absent here, by
design.

## Worked example — Ship's Record

For `notebooks/scotty/manifold.md` at revision 3, authored by `scotty`:

```json
{
  "@context": {
    "prov": "http://www.w3.org/ns/prov#",
    "xsd": "http://www.w3.org/2001/XMLSchema#"
  },
  "@graph": [
    {
      "@id": "urn:probos:entity:f481e5ff1a7e1360f550c03946194be98c95541a24d5d47b7c28f7bd47632eb7",
      "@type": "prov:Entity",
      "prov:wasAttributedTo": { "@id": "urn:probos:agent:scotty" },
      "prov:generatedAtTime": {
        "@value": "2026-07-26T10:00:00+00:00",
        "@type": "xsd:dateTime"
      },
      "prov:wasRevisionOf": {
        "@id": "urn:probos:entity:0cdfe75a0ea66e0d66a5b7d537238b8b6ec1c9e4b692c3b46ea5ccd3738be195"
      }
    },
    { "@id": "urn:probos:agent:scotty", "@type": "prov:Agent" },
    {
      "@id": "urn:probos:entity:0cdfe75a0ea66e0d66a5b7d537238b8b6ec1c9e4b692c3b46ea5ccd3738be195",
      "@type": "prov:Entity"
    }
  ]
}
```

## Out of scope

`ProvenanceTag` / `ProvenanceEnvelope` (`cognitive/provenance.py`) are **not**
projected. They carry a source tier, a retrieval timestamp, a confidence and a
truncated content hash — but no agent and no activity: `query_with_provenance`
accepts an `agent_id` and discards it. A PROV-O document built from them would
be valid and vacuous: entities with generation times, saying nothing about who
or how. Giving that structure an agent and an activity is a separate change,
not a projection.
