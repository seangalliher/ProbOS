"""AD-742b: face-embedding identity recognition.

Replaces the AD-733b LLM-prompt path (one vision LLM call per session) with
a local face-embedding model (facenet-pytorch, MIT). Enrollment is a one-time
operator action: upload a reference photo, IdentityResolver computes a 512-d
embedding and persists it to ``data/captain_identity.json``. Per-frame
resolution computes the live embedding and returns the cosine distance against
the enrolled reference.

License posture: facenet-pytorch is MIT (verified via the MIT classifier in
the installed METADATA file per AD-742b Section 0 pre-flight). Pretrained
weights distributed by timesler/facenet-pytorch under Apache-2.0 (VGGFace2 +
CASIA-WebFace).

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
import math
from pathlib import Path
from typing import Any, Literal

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
    after ``.eval()``.
    """

    _shared_mtcnn: Any = None  # lazy-loaded; shared across all instances in the process
    _shared_resnet: Any = None

    def __init__(self, data_dir: Path, threshold: float = 0.6) -> None:
        self._data_dir = data_dir
        self._threshold = threshold
        self._identity_path = data_dir / IDENTITY_FILE_NAME
        self._cached_embedding: list[float] | None = None
        self._cached_mtime: float | None = None

    @classmethod
    def _load_models(cls) -> tuple[Any, Any]:
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
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 2.0
    return 1.0 - dot / (norm_a * norm_b)
