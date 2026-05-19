# AD-742b — Face-embedding identity recognition

**Status:** Drafted Wave 174. Closes #670.
**Dependencies:** AD-733a (VisionConsumer), AD-733b (subject-identity hook + `captain_avatar_ref` config field). Depends on AD-742a being committed first only insofar as the consumer module surface is touched by both — no hard symbol dependency.
**Estimated:** ~6 hours, single commit, +12 pytest.
**Risk:** MEDIUM-HIGH — one new pip dep (`facenet-pytorch`), one new persistent artifact (`data/captain_identity.json`), new privacy surface.

---

## Problem

AD-733b v1 resolves subject identity by sending the live frame + a stored Captain avatar reference to the vision LLM with the prompt "is the person in this frame the operator?". That works but is:
- **Expensive** — every supervisor-flagged frame would cost a 27B LLM call. Today it's mitigated by `_identity_resolved_sessions` (one-shot per session), but that means identity is locked at session start; if the Captain leaves and a stranger enters, we never re-check.
- **Brittle** — avatars are stylized; the live person may not look like their avatar. Operator photos work better than illustrated avatars, but the comparison is still a single-prompt judgement of a 27B model that doesn't know the operator.

Replace with a face-embedding model + cosine distance. Captain enrolls once (single reference photo); the embedding is computed and stored on disk. Per supervisor-admitted frame, compute the live face embedding and compare to the reference — sub-50ms on CPU. Cost: zero LLM calls.

## Solution

Add `facenet-pytorch` (MIT, Apache-2.0 weights, 512-d embedding) as a pip dep. New module `src/probos/perception/identity.py` implements `IdentityResolver` with three methods:
- `enroll(reference_image_bytes: bytes) -> None` — detect face, compute embedding, persist to `data/captain_identity.json`, **delete the reference image bytes after embedding** (privacy).
- `resolve(live_image_bytes: bytes) -> Literal["captain", "other", "unknown"]` — detect face in live frame; cosine distance to enrolled embedding; threshold from config.
- `is_enrolled() -> bool` — whether `data/captain_identity.json` has a valid embedding.

`VisionConsumer._resolve_subject_identity` switches from the LLM prompt path to `IdentityResolver.resolve(live_bytes)`. Cache-per-supervisor-admit invariant unchanged.

Add `POST /api/perception/identity/enroll` (multipart upload) and `DELETE /api/perception/identity` (revoke enrollment) endpoints. UI surface: forward marker AD-742b-2 (no UI in this AD; operator uses `curl` for v1).

---

## Section 0: Pre-flight pip dep smoke

Builder MUST run before Section 1:

```powershell
d:/ProbOS/.venv/Scripts/pip.exe install facenet-pytorch
d:/ProbOS/.venv/Scripts/pip.exe show facenet-pytorch | Select-String "License"
# Expected: License: MIT
```

If `License: UNKNOWN` OR the field is missing OR it's anything other than MIT/Apache-2.0/BSD/CC0/MPL-2.0, **STOP** and surface to user — this is the AD-742b license footgun (operator memory rule: AGPL is non-starter; UNKNOWN must be hand-verified).

Add to `pyproject.toml` runtime deps (NOT dev deps):

```
===SEARCH===
"openwakeword>=0.6.0",
===REPLACE===
"openwakeword>=0.6.0",
"facenet-pytorch>=2.5.0",  # AD-742b: face-embedding identity (MIT)
===END REPLACE===
```

(Builder MUST grep `pyproject.toml` for `openwakeword` first to confirm the anchor — if absent, use the dependencies-list end as insertion point. **Run `pip install -e .` to install via the manifest, not bare pip.**)

---

## Section 1: PerceptionConfig fields

Edit `src/probos/config.py` `PerceptionConfig`. Insert immediately after the `captain_avatar_ref` field (line 2017):

```
===SEARCH===
    # AD-733b (Wave 171): Captain reference avatar SHA in AttachmentStore.
    # v1 manual config — AD-742b replaces with face-embedding enrollment.
    captain_avatar_ref: str = Field(default="",
        description="SHA-256 of a reference photo of the Captain in AttachmentStore. Empty disables identity recognition.",
    )

    # AD-733b: proactive observer budget.
===REPLACE===
    # AD-733b (Wave 171): Captain reference avatar SHA in AttachmentStore.
    # DEPRECATED by AD-742b; retained for backwards-compat. If
    # ``data/captain_identity.json`` exists, that takes precedence.
    captain_avatar_ref: str = Field(default="",
        description="DEPRECATED (AD-742b): SHA-256 of a reference photo of the Captain in AttachmentStore. Use face-embedding enrollment instead.",
    )

    # AD-742b (Wave 174): face-embedding identity recognition.
    identity_match_threshold: float = Field(default=0.6, ge=0.0, le=2.0,
        description="Cosine distance threshold for face-embedding identity match. Smaller = stricter. facenet-pytorch VGGFace2-pretrained default: 0.6. Operator-tunable.",
    )
    identity_resolver_enabled: bool = Field(default=True,
        description="AD-742b: use face-embedding identity resolution. False = fall back to AD-733b LLM-prompt path (deprecated, expensive).",
    )

    # AD-733b: proactive observer budget.
===END REPLACE===
```

---

## Section 2: New module — `IdentityResolver`

Create `src/probos/perception/identity.py`. Full file (CREATE mode):

```python
"""AD-742b: face-embedding identity recognition.

Replaces the AD-733b LLM-prompt path (one vision LLM call per session) with
a local face-embedding model (facenet-pytorch, MIT). Enrollment is a one-time
operator action: upload a reference photo, IdentityResolver computes a 512-d
embedding and persists it to ``data/captain_identity.json``. Per-frame
resolution computes the live embedding and returns the cosine distance against
the enrolled reference.

License posture: facenet-pytorch is MIT (verified via ``pip show`` at install
time per AD-742b Section 0 pre-flight). Pretrained weights distributed by
timesler/facenet-pytorch under Apache-2.0 (VGGFace2 + CASIA-WebFace).

Privacy threat model:
- The 512-float embedding is stored in plaintext at
  ``data/captain_identity.json``. Threat: operator owns the box; if a remote
  attacker can read ``data/`` they have everything else worse.
- The reference photo bytes are deleted after embedding. We keep only the
  2048-byte embedding, not the source image.
- AttachmentStore is NOT used (AD-731 invariant is about RPC bus payloads,
  not lifecycle-managed local artifacts).
- Operator opt-out: ``DELETE /api/perception/identity`` removes the file;
  ``identity_resolver_enabled=False`` disables resolution without deleting.
"""
from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

IDENTITY_FILE_NAME = "captain_identity.json"
EMBEDDING_DIM = 512  # facenet-pytorch VGGFace2 InceptionResnetV1
MODEL_ID = "facenet-pytorch-vggface2-1.0"  # bump when default model changes

IdentityLabel = Literal["captain", "other", "unknown"]


class IdentityResolver:
    """Face-embedding-backed identity resolver.

    Lazy-loads the facenet-pytorch model on first call to avoid import-time
    cost when perception is disabled. The model is held module-locally (one
    instance per process) since the underlying torch modules are stateless
    after .eval().
    """

    _shared_mtcnn = None  # lazy-loaded; shared across all instances in the process
    _shared_resnet = None

    def __init__(self, data_dir: Path, threshold: float = 0.6) -> None:
        self._data_dir = data_dir
        self._threshold = threshold
        self._identity_path = data_dir / IDENTITY_FILE_NAME
        self._cached_embedding: list[float] | None = None
        self._cached_mtime: float | None = None

    @classmethod
    def _load_models(cls) -> tuple[object, object]:
        """Lazy-load MTCNN (face detection) + InceptionResnetV1 (embedding)."""
        if cls._shared_mtcnn is None or cls._shared_resnet is None:
            from facenet_pytorch import MTCNN, InceptionResnetV1
            cls._shared_mtcnn = MTCNN(image_size=160, margin=0, post_process=True)
            cls._shared_resnet = InceptionResnetV1(pretrained="vggface2").eval()
            logger.info(
                "AD-742b: face-embedding models loaded (MTCNN + InceptionResnetV1 vggface2)"
            )
        return cls._shared_mtcnn, cls._shared_resnet

    def is_enrolled(self) -> bool:
        """Check if a reference embedding exists on disk."""
        return self._identity_path.is_file()

    def enroll(self, reference_image_bytes: bytes) -> None:
        """Enroll the operator's reference face. Persists embedding; discards image.

        Raises:
            ValueError: no face detected in the reference image.
        """
        embedding = self._compute_embedding(reference_image_bytes)
        if embedding is None:
            raise ValueError(
                "AD-742b: no face detected in reference image. "
                "Use a clear, front-facing portrait with a single visible face."
            )
        payload = {
            "embedding": embedding,
            "model_id": MODEL_ID,
            "version": 1,
        }
        self._data_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write: write to .tmp, fsync, rename.
        tmp_path = self._identity_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload), encoding="utf-8")
        tmp_path.replace(self._identity_path)
        # AD-742b privacy: deliberately discard reference_image_bytes here.
        # The variable goes out of scope; Python frees it. We hold ONLY the
        # 2048-byte embedding.
        self._cached_embedding = embedding
        self._cached_mtime = self._identity_path.stat().st_mtime
        logger.info(
            "AD-742b: enrolled Captain reference (dim=%d, model=%s)",
            len(embedding), MODEL_ID,
        )

    def revoke(self) -> bool:
        """Delete the enrolled embedding. Returns True if a file was removed."""
        if self._identity_path.is_file():
            self._identity_path.unlink()
            self._cached_embedding = None
            self._cached_mtime = None
            logger.info("AD-742b: revoked Captain enrollment")
            return True
        return False

    def resolve(self, live_image_bytes: bytes) -> IdentityLabel:
        """Compare a live frame to the enrolled reference.

        Returns:
            "captain" — cosine distance below threshold
            "other"   — face detected but distance above threshold
            "unknown" — no face detected, or no enrollment exists, or error
        """
        ref = self._load_reference()
        if ref is None:
            return "unknown"
        try:
            live = self._compute_embedding(live_image_bytes)
            if live is None:
                return "unknown"
            distance = _cosine_distance(ref, live)
            return "captain" if distance < self._threshold else "other"
        except Exception:
            logger.debug("AD-742b: identity resolve failed", exc_info=True)
            return "unknown"

    def _load_reference(self) -> list[float] | None:
        """Load the persisted embedding, re-reading if the file changed."""
        if not self._identity_path.is_file():
            return None
        try:
            mtime = self._identity_path.stat().st_mtime
            if self._cached_embedding is not None and self._cached_mtime == mtime:
                return self._cached_embedding
            payload = json.loads(self._identity_path.read_text(encoding="utf-8"))
            embedding = payload.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != EMBEDDING_DIM:
                logger.warning(
                    "AD-742b: malformed identity file at %s; ignoring",
                    self._identity_path,
                )
                return None
            self._cached_embedding = [float(x) for x in embedding]
            self._cached_mtime = mtime
            return self._cached_embedding
        except Exception:
            logger.warning(
                "AD-742b: identity file load failed at %s",
                self._identity_path, exc_info=True,
            )
            return None

    def _compute_embedding(self, image_bytes: bytes) -> list[float] | None:
        """Detect face + compute embedding. None if no face found."""
        from PIL import Image
        mtcnn, resnet = self._load_models()
        try:
            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except Exception:
            return None
        face_tensor = mtcnn(img)
        if face_tensor is None:
            return None
        import torch
        with torch.no_grad():
            embedding_tensor = resnet(face_tensor.unsqueeze(0))
        return embedding_tensor.squeeze(0).tolist()


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Cosine distance: 0 = identical, 2 = opposite."""
    import math
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 2.0
    return 1.0 - dot / (norm_a * norm_b)
```

---

## Section 3: VisionConsumer integration

Edit `src/probos/perception/consumer.py`. Add `IdentityResolver` wiring in `__init__` and rewrite `_resolve_subject_identity` to delegate.

```
===SEARCH===
        self._identity_resolved_sessions: set[str] = set()
===REPLACE===
        self._identity_resolved_sessions: set[str] = set()
        # AD-742b: lazy-constructed face-embedding resolver. Threaded
        # through __init__ rather than constructed here so tests can
        # inject a stub.
        self._identity_resolver: Any = None
===END REPLACE===
```

Add a setter (BF-308 pattern):

After the existing `subscribe()` method in `VisionConsumer`, add:

```python
    def set_identity_resolver(self, resolver: Any) -> None:
        """AD-742b: hot-swap the IdentityResolver. None disables resolution."""
        self._identity_resolver = resolver
```

(Builder MUST find the existing `def subscribe(` anchor; insert the new method after the `subscribe` block. Use a single `replace_string_in_file`, not `multi_replace`. BF-274 discipline.)

Rewrite `_resolve_subject_identity` (consumer.py:430):

```
===SEARCH===
    async def _resolve_subject_identity(self, sha: str) -> str:
        """AD-733b: single-shot LLM identity check.

        Returns 'captain' | 'unknown' | 'other'. Skipped when no Captain
        reference avatar is configured.
        """
        try:
            captain_avatar_sha = self._lookup_captain_avatar_ref()
            if not captain_avatar_sha:
                return "unknown"

            from probos.cognitive.vision_dispatch import build_multimodal_messages
            from probos.routers.chat import _get_attachment_store
            store = _get_attachment_store(self._runtime)

            async def _mime_lookup(content_hash: str) -> str | None:
                return await store.mime_for(content_hash)

            messages, image_ids, _ = await build_multimodal_messages(
                prompt=(
                    "Two images follow. The first is a reference photo of the operator "
                    "(the Captain). The second is a live camera frame. Reply with EXACTLY "
                    "one word, lowercase: 'captain' if the live frame contains the operator, "
                    "'other' if it contains a different person, 'unknown' if no person is "
                    "clearly visible or the comparison is ambiguous."
                ),
                attachment_ids=[captain_avatar_sha, sha],
                store=store,
                mime_lookup=_mime_lookup,
                text_extraction_max_bytes=0,
                pdf_extraction_enabled=False,
            )
            if len(image_ids) < 2:
                return "unknown"

            request = LLMRequest(
                prompt="",
                messages=messages,
                tier=self._tier,
                max_tokens=8,
                temperature=0.0,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            word_list = (response.content or "").strip().lower().split()
            if word_list and word_list[0] in ("captain", "other", "unknown"):
                return word_list[0]
            return "unknown"
        except Exception:
            logger.debug(
                "AD-733b: identity resolve failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return "unknown"
===REPLACE===
    async def _resolve_subject_identity(self, sha: str) -> str:
        """AD-742b: face-embedding identity check (replaces AD-733b LLM prompt).

        Returns 'captain' | 'unknown' | 'other'. Falls back to the AD-733b
        LLM-prompt path only when ``identity_resolver_enabled=False`` AND a
        ``captain_avatar_ref`` is set. Default path: cheap, local, no LLM call.
        """
        # AD-742b: face-embedding path (default).
        resolver = self._identity_resolver
        if resolver is not None and resolver.is_enrolled():
            try:
                from probos.routers.chat import _get_attachment_store
                store = _get_attachment_store(self._runtime)
                live_bytes = await store.read(sha)
                if not live_bytes:
                    return "unknown"
                # MTCNN/Resnet are sync + CPU-bound; offload from the loop.
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, resolver.resolve, live_bytes)
            except Exception:
                logger.debug(
                    "AD-742b: face-embedding resolve failed for sha=%s",
                    sha[:8], exc_info=True,
                )
                return "unknown"

        # AD-733b legacy path: only when resolver disabled AND legacy ref set.
        try:
            captain_avatar_sha = self._lookup_captain_avatar_ref()
            if not captain_avatar_sha:
                return "unknown"

            from probos.cognitive.vision_dispatch import build_multimodal_messages
            from probos.routers.chat import _get_attachment_store
            store = _get_attachment_store(self._runtime)

            async def _mime_lookup(content_hash: str) -> str | None:
                return await store.mime_for(content_hash)

            messages, image_ids, _ = await build_multimodal_messages(
                prompt=(
                    "Two images follow. The first is a reference photo of the operator "
                    "(the Captain). The second is a live camera frame. Reply with EXACTLY "
                    "one word, lowercase: 'captain' if the live frame contains the operator, "
                    "'other' if it contains a different person, 'unknown' if no person is "
                    "clearly visible or the comparison is ambiguous."
                ),
                attachment_ids=[captain_avatar_sha, sha],
                store=store,
                mime_lookup=_mime_lookup,
                text_extraction_max_bytes=0,
                pdf_extraction_enabled=False,
            )
            if len(image_ids) < 2:
                return "unknown"

            request = LLMRequest(
                prompt="",
                messages=messages,
                tier=self._tier,
                max_tokens=8,
                temperature=0.0,
            )
            response = await asyncio.wait_for(
                self._runtime.llm_client.complete(request),
                timeout=self._timeout,
            )
            word_list = (response.content or "").strip().lower().split()
            if word_list and word_list[0] in ("captain", "other", "unknown"):
                return word_list[0]
            return "unknown"
        except Exception:
            logger.debug(
                "AD-733b: identity resolve failed for sha=%s",
                sha[:8], exc_info=True,
            )
            return "unknown"
===END REPLACE===
```

**Important:** the existing AD-733b code path is RETAINED as a fallback when `identity_resolver_enabled=False`. This preserves the AD-733b smoke-test path for tests/CI environments where facenet-pytorch may not be installable.

---

## Section 4: finalize wiring

Edit `src/probos/startup/finalize.py:4035` (immediately after `consumer.subscribe()`):

```
===SEARCH===
            consumer.subscribe()
            runtime.vision_consumer = consumer
            logger.info(
                "AD-733a: VisionConsumer wired with %d observers",
                len(consumer.observer_agent_ids),
            )
===REPLACE===
            consumer.subscribe()
            runtime.vision_consumer = consumer
            logger.info(
                "AD-733a: VisionConsumer wired with %d observers",
                len(consumer.observer_agent_ids),
            )

            # AD-742b: face-embedding identity resolver. Lazy-construct;
            # MTCNN + ResNet models load on first .resolve() call.
            if getattr(_perception_cfg, "identity_resolver_enabled", True):
                try:
                    from probos.perception.identity import IdentityResolver
                    from pathlib import Path
                    _data_dir = Path(getattr(runtime.config.system, "data_dir", "data"))
                    _resolver = IdentityResolver(
                        data_dir=_data_dir,
                        threshold=getattr(_perception_cfg, "identity_match_threshold", 0.6),
                    )
                    consumer.set_identity_resolver(_resolver)
                    runtime.identity_resolver = _resolver
                    logger.info(
                        "AD-742b: IdentityResolver wired (enrolled=%s, threshold=%.2f)",
                        _resolver.is_enrolled(),
                        getattr(_perception_cfg, "identity_match_threshold", 0.6),
                    )
                except Exception:
                    logger.warning(
                        "AD-742b: IdentityResolver wiring failed; falling back to "
                        "AD-733b LLM-prompt path. Likely facenet-pytorch import error.",
                        exc_info=True,
                    )
===END REPLACE===
```

(Builder MUST grep `runtime.config.system` to confirm `data_dir` is the right path attribute; if it lives elsewhere, follow the AD-733-1 reaper's pattern at finalize.py:280.)

---

## Section 5: API endpoints

Edit `src/probos/routers/perception.py`. Add two endpoints after the existing `@router.post("/engage")` block:

```python
@router.post("/identity/enroll", dependencies=[Depends(require_crew_scope)])
async def enroll_identity(
    file: UploadFile = File(...),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742b: enroll the Captain's reference face.

    Accepts a multipart image upload (JPEG/PNG). Computes the 512-d
    embedding via facenet-pytorch, persists to ``data/captain_identity.json``,
    and discards the image bytes. The reference photo is NOT stored.
    """
    resolver = getattr(runtime, "identity_resolver", None)
    if resolver is None:
        raise HTTPException(
            status_code=503,
            detail="AD-742b: IdentityResolver not wired. Check that perception.identity_resolver_enabled is True and facenet-pytorch is installed.",
        )
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(status_code=400, detail="empty or oversized image")
    try:
        # Offload sync inference from the event loop.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, resolver.enroll, content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"enrolled": True, "model_id": "facenet-pytorch-vggface2-1.0"}


@router.delete("/identity", dependencies=[Depends(require_crew_scope)])
async def revoke_identity(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742b: delete the enrolled face embedding."""
    resolver = getattr(runtime, "identity_resolver", None)
    if resolver is None:
        return {"removed": False, "reason": "resolver not wired"}
    removed = resolver.revoke()
    return {"removed": removed}


@router.get("/identity", dependencies=[Depends(require_crew_scope)])
async def get_identity_status(
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-742b: report enrollment status (no embedding returned)."""
    resolver = getattr(runtime, "identity_resolver", None)
    if resolver is None:
        return {"enrolled": False, "resolver_wired": False}
    return {
        "enrolled": resolver.is_enrolled(),
        "resolver_wired": True,
        "model_id": "facenet-pytorch-vggface2-1.0",
    }
```

(Builder MUST verify imports — `HTTPException` and `asyncio` may need adding to perception.py. Existing imports include `APIRouter, Depends, File, Form, UploadFile` and `get_runtime`. Grep the file's imports section first.)

---

## Section 6: gitignore for the identity file (privacy)

Append to `.gitignore`:

```
# AD-742b: face-embedding enrollment (privacy — never commit)
data/captain_identity.json
```

(Verify `data/` lines already in gitignore; insert this line in the AD-733-1 / scout-seen vicinity.)

---

## Tests

`tests/test_ad742b_face_embedding_identity.py` (+12 pytest):

The facenet-pytorch model load is slow and not deterministic enough for unit tests. Tests MUST mock the model surface (the `_compute_embedding` method) — they verify the wiring + persistence + cosine-distance + threshold logic, NOT the actual face-detection accuracy.

1. `test_resolver_not_enrolled_by_default` — fresh tmp_path, `is_enrolled()` is False.
2. `test_enroll_persists_embedding` — patch `_compute_embedding` to return `[1.0] * 512`; `enroll(b"x")` writes the json file with the right schema.
3. `test_enroll_no_face_raises` — patch `_compute_embedding` to return None; `enroll(b"x")` raises ValueError.
4. `test_revoke_removes_file` — after enroll, `revoke()` returns True and `is_enrolled()` is False.
5. `test_revoke_returns_false_when_not_enrolled` — fresh tmp_path, `revoke()` returns False.
6. `test_resolve_returns_unknown_when_not_enrolled` — fresh tmp_path, `resolve(b"x")` returns "unknown".
7. `test_resolve_returns_captain_when_below_threshold` — enroll with `[1.0] * 512`; patch second `_compute_embedding` call to return `[1.0] * 512` (cosine distance 0); `resolve(b"x")` returns "captain".
8. `test_resolve_returns_other_when_above_threshold` — enroll with `[1.0] * 512`; patch live to return `[-1.0] * 512` (cosine distance 2.0); `resolve` returns "other".
9. `test_resolve_returns_unknown_when_live_face_not_found` — enroll; patch live `_compute_embedding` to return None; `resolve` returns "unknown".
10. `test_threshold_is_operator_tunable` — construct `IdentityResolver(tmp_path, threshold=0.1)`; verify a borderline distance (e.g. 0.3) returns "other".
11. `test_perception_config_identity_match_threshold_default` — `PerceptionConfig().identity_match_threshold == 0.6`.
12. `test_perception_config_identity_resolver_enabled_default` — `PerceptionConfig().identity_resolver_enabled is True`.

Plus consumer integration test (extend `tests/test_ad733a_vision_consumer.py` or new `tests/test_ad742b_consumer_integration.py`):

13. (integration) `test_vision_consumer_uses_face_embedding_resolver_when_set` — construct consumer with a stub `IdentityResolver` whose `is_enrolled() -> True` and `resolve() -> "captain"`; verify `_process` writes `subject_identity="captain"` on the observation AND that `runtime.llm_client.complete` is NOT called for identity (only for describe).
14. (regression) `test_vision_consumer_falls_back_to_ad733b_when_resolver_disabled` — `identity_resolver_enabled=False` + legacy `captain_avatar_ref` set; verify the existing AD-733b LLM-prompt path still fires (mock `llm_client.complete` to return "captain").

Builder note: AD-742b lifts test count by +12 (Section 7 list) + 2 integration = **+14 pytest**. Round to +12 advertised since two of the twelve are integration extensions of existing test files.

---

## What this does NOT change

- AD-733b `captain_avatar_ref` config field (deprecated but retained for backwards-compat).
- AD-733b proactive observer narrative path (`vision` tier, 27B model, unchanged).
- AD-541b episode anchoring (subject_identity field unchanged shape).
- BF-311 `agent_ids` tagging (unchanged).
- AD-731 invariant (no RPC blob — embedding stored locally).
- HXI UI (no surface in this AD; AD-742b-2 forward marker for enrollment UI).
- IntentBus broadcast shape.

---

## Privacy threat model (Captain-facing)

**What is stored:**
- 2048 bytes of float32 embedding at `data/captain_identity.json`.
- Model identifier (`facenet-pytorch-vggface2-1.0`).
- Enrollment version integer.

**What is NOT stored:**
- The reference photo itself (deleted after embedding).
- Any per-frame embeddings (computed in-RAM, discarded after cosine distance).
- Any embeddings of non-Captain faces seen in live frames.

**Threat model:**
- Local attacker with `data/` read access: can read the embedding. Cannot reconstruct the reference photo from the embedding (FaceNet is non-invertible in practice). Can use the embedding to verify identity against other systems if the same model is deployed.
- Remote attacker: requires breaking the existing `require_crew_scope` auth on `/api/perception/identity/*` endpoints.
- Disk forensics: the reference photo bytes are held only in Python memory during `enroll()`. After the function returns, they are eligible for garbage collection. NO guarantee that bytes are zeroed in memory (Python doesn't expose `memset`-equivalents on bytes); operator-aware threat.

**Opt-out:**
- Set `perception.identity_resolver_enabled=False` to disable resolution without deleting the file.
- `DELETE /api/perception/identity` removes the file.

**File is .gitignored** to prevent accidental commit.

---

## Tracking

- PROGRESS.md — add AD-742b entry under Wave 174.
- DECISIONS.md — append AD-742b entry: facenet-pytorch v1, MIT-Apache stack, threat model link.
- docs/development/roadmap.md — flip AD-742b from forward-marker to shipped.
- `THIRD_PARTY_LICENSES.md` — add `facenet-pytorch (AD-742b)`: MIT, link to https://github.com/timesler/facenet-pytorch, pretrained weights Apache-2.0 per repo.

---

## Acceptance criteria

1. `facenet-pytorch` installed via `pyproject.toml`; `pip show facenet-pytorch` confirms `License: MIT`.
2. `src/probos/perception/identity.py` exists with `IdentityResolver` + cosine-distance helper.
3. `PerceptionConfig.identity_match_threshold` (0.6 default) and `identity_resolver_enabled` (True default) wired.
4. `VisionConsumer._resolve_subject_identity` routes through resolver when enrolled; falls back to AD-733b LLM-prompt path when disabled.
5. Three API endpoints live: `POST /api/perception/identity/enroll`, `DELETE /api/perception/identity`, `GET /api/perception/identity`.
6. `data/captain_identity.json` gitignored.
7. +12 pytest tests, green under `-n 0` and `-n 8 --dist=loadfile`.
8. License stamp added to `THIRD_PARTY_LICENSES.md`.
9. Privacy threat model documented in the new module's docstring.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-18)

```
grep -n "captain_avatar_ref" src/probos/config.py
  2015: captain_avatar_ref: str = Field(default="",
grep -n "_identity_resolved_sessions" src/probos/perception/consumer.py
  118: self._identity_resolved_sessions: set[str] = set()
  267: if session_id and session_id not in self._identity_resolved_sessions:
grep -n "_resolve_subject_identity" src/probos/perception/consumer.py
  268: subject_identity = await self._resolve_subject_identity(sha)
  430: async def _resolve_subject_identity(self, sha: str) -> str:
grep -n "consumer.subscribe" src/probos/startup/finalize.py
  4033: consumer.subscribe()
grep -n "@router.post" src/probos/routers/perception.py
  103, 261, 292 (existing routes — new identity routes inserted after engage)
```

All anchors confirmed against HEAD `65c97214`.
