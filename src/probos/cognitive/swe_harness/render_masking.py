"""AD-1337 S3 (#1560): the render seam. The text the agentic loop hands a model is masked before the model sees it.

The producer seam (AD-1337 S2, ``ToolExecutor._invoke_once``) masks every ``ToolResult`` a registry returns. Some
text reaches the model without passing it, and this seam masks it:

- a raised exception's text (``Tool X failed: ...``), in the loop's own conversion and in the parallel batch's;
- the ``str()`` of an output the producer seam leaves as it is (a custom object, ``bytes``, a container past its walk
  bounds), and BF-728's re-render of a container from the raw value;
- AD-1240's captured text, which becomes the offloaded payload, the recovery slices read from it and the result the
  run records.

``RenderMask`` holds one tool result's two passes, ``capture`` before ``prepare_result`` and ``final`` on the result
the loop returns, and emits at most one ``SECRET_MASKED`` (``seam: "render"``) for both. After the producer seam a hit
here means text the producer seam did not see, so it is also logged at WARNING, with labels only.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from probos.cognitive.swe_harness.tool_call import (
    CapturedConversion,
    DelegatedToolCallResult,
    InstructionToolCallResult,
    ToolCallResult,
    capture_tool_result,
    result_delivery,
)
from probos.tools.executor import SECRET_MASKED_MAX_NAMES, tool_record_identity
from probos.tools.protocol import ToolResult

if TYPE_CHECKING:
    from probos.execution.effect_types import EffectCorrelation
    from probos.security.secret_masking import SecretMasker

logger = logging.getLogger(__name__)

#: The longest tool-call id a SECRET_MASKED payload carries. The id is the model's (its JSON is unchecked), so a
#: longer one is left out rather than stored.
CALL_ID_MAX_CHARS = 128


class SecretMaskerSlot:
    """``AgenticLoop.secret_masker`` as a data descriptor: a ``SecretMasker``, or None (the default: nothing is masked).

    Anything else raises ``TypeError``, so a wiring bug cannot pass silently. It is not a constructor keyword because
    the AD-1152 golden pins the loop's constructor keywords; both constructions assign it right after construction, as
    AD-1240 assigns ``workspace_results``.
    """

    def __set_name__(self, owner: type, name: str) -> None:
        self._name = f"_{name}"

    def __get__(self, instance: object | None, owner: type | None = None) -> Any:
        if instance is None:
            return self
        return instance.__dict__.get(self._name)

    def __set__(self, instance: object, value: object) -> None:
        from probos.security.secret_masking import SecretMasker

        if value is not None and not isinstance(value, SecretMasker):
            raise TypeError("secret_masker must be a SecretMasker or None")
        instance.__dict__[self._name] = value


class RenderMask:
    """One tool result's render-seam passes and the one ``SECRET_MASKED`` they share.

    Without a masker both passes return their argument itself. With one and no match, the same: ``mask_text`` returns
    the same string, so the loop's text, the offloaded payload and its sha256 are byte-identical to a run without one.
    """

    def __init__(self, masker: SecretMasker | None) -> None:
        self._masker = masker
        self._names: set[str] = set()
        self._failed = False

    def capture(self, captured: CapturedConversion) -> CapturedConversion:
        """Mask AD-1240's captured text before ``prepare_result`` stores, frames or returns any of it.

        A failed pass replaces the capture with a withheld result's (``MASKING_FAILED_TEXT`` as its error), so nothing
        of the original text or its raw value is delivered, offloaded or re-rendered.
        """
        if self._masker is None or captured.text is None:
            return captured
        outcome = self._masker.mask_text(captured.text)
        if outcome.failed:
            from probos.security.secret_masking import MASKING_FAILED_TEXT

            self._failed = True
            return capture_tool_result(
                captured.request_id, ToolResult(error=MASKING_FAILED_TEXT), captured.duration_ms,
                max_chars=captured.max_chars,
            )
        if outcome.text is captured.text:
            return captured
        self._names |= outcome.names
        return replace(captured, text=outcome.text)

    async def final(
        self,
        result: ToolCallResult,
        *,
        emit_fn: Callable[..., Any] | None,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> ToolCallResult:
        """Mask the text this call hands the model, then emit ``SECRET_MASKED`` once if either pass masked or withheld.

        The model reads a delivered result's frame instead of its output (``format_tool_result_content``), so the frame
        is checked too. A failed pass, or a frame that holds a known value, withholds (``_withheld``).
        """
        masker = self._masker
        if masker is None:
            return result
        result = self._mask_final(masker, result)
        if self._names or self._failed:
            await self._emit(masker, emit_fn, result, tool_name=tool_name, strict=strict, correlation=correlation)
        return result

    def _mask_final(self, masker: SecretMasker, result: ToolCallResult) -> ToolCallResult:
        if isinstance(result.output, str):
            outcome = masker.mask_text(result.output)
            if outcome.failed:
                return self._withheld(result)
            if outcome.text is not result.output:
                self._names |= outcome.names
                result = replace(result, output=outcome.text)
        delivery = result_delivery(result)
        if delivery is not None:
            # A frame is never rewritten: a masked worked path would send the recovery to a file that does not exist.
            # One that holds a known value (a workspace root or a source path that contains one) is withheld, and so
            # is one whose pass failed (its text is then MASKING_FAILED_TEXT, which differs too).
            framed = masker.mask_text(delivery.presentation)
            if framed.text is not delivery.presentation:
                self._names |= framed.names
                return self._withheld(result)
        return result

    def _withheld(self, result: ToolCallResult) -> ToolCallResult:
        """``result`` as an error whose output is ``MASKING_FAILED_TEXT``, with no frame the model would read instead.

        A failed delivery keeps its extension: its frame is a fixed code, and the run still stops on it (BF-946). Any
        other delivery is dropped; an instruction or delegation extension is kept as it was.
        """
        from probos.security.secret_masking import MASKING_FAILED_TEXT

        self._failed = True
        delivery = result_delivery(result)
        if delivery is None or delivery.status == "failed":
            return replace(result, output=MASKING_FAILED_TEXT, is_error=True)
        kept = {"id": result.id, "output": MASKING_FAILED_TEXT, "is_error": True, "duration_ms": result.duration_ms}
        if isinstance(result, DelegatedToolCallResult):
            return DelegatedToolCallResult(**kept, evidence=result.evidence)
        if isinstance(result, InstructionToolCallResult):
            return InstructionToolCallResult(**kept, repository_instructions=result.repository_instructions)
        return ToolCallResult(**kept)

    @staticmethod
    def _carried_call_id(masker: SecretMasker, call_id: object) -> str | None:
        """The model's tool-call id for the payload, or None: not a str, longer than ``CALL_ID_MAX_CHARS``, or holding
        a known value. The id is the model's (its JSON is unchecked), so it is checked like the text and never masked
        into the record; a failed pass returns ``MASKING_FAILED_TEXT``, which leaves it out too."""
        if type(call_id) is not str or len(call_id) > CALL_ID_MAX_CHARS:
            return None
        return call_id if masker.mask_text(call_id).text is call_id else None

    async def _emit(
        self,
        masker: SecretMasker,
        emit_fn: Callable[..., Any] | None,
        result: ToolCallResult,
        *,
        tool_name: object,
        strict: bool,
        correlation: EffectCorrelation | None,
    ) -> None:
        from probos.events import EventType

        names = sorted(self._names)
        payload = {
            "seam": "render",
            "tool_id": None if strict else tool_record_identity(tool_name),
            "invocation_id": None if strict else self._carried_call_id(masker, result.id),
            "operation_id": correlation.operation_id if correlation is not None else None,
            "attempt_id": correlation.attempt_id if correlation is not None else None,
            "names": names[:SECRET_MASKED_MAX_NAMES],
            "names_omitted": max(0, len(names) - SECRET_MASKED_MAX_NAMES),
            "failed": self._failed,
        }
        logger.warning(
            "AD-1337: render seam masked names=%s tool=%s failed=%s",
            payload["names"], payload["tool_id"], self._failed,
        )
        if emit_fn is None:
            return
        try:
            emitted = emit_fn(EventType.SECRET_MASKED, payload)
            if inspect.isawaitable(emitted):
                await emitted
        except Exception:
            logger.warning(
                "AD-1337: SECRET_MASKED could not be emitted at the render seam for tool=%s; the text stays masked",
                payload["tool_id"],
            )
