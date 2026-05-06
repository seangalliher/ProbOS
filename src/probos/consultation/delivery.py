"""AD-594d v1: Consultation delivery pipeline.

Format transformation engine + ``DeliveryAdapter`` Protocol with built-in
``LocalFileAdapter`` and ``GitHubAdapter`` + captain approval gate + audit
trail (``delivery.yaml`` + journal) + atomic-vs-partial dispatch + revision
cycle (``COMPLETED -> CONSULTING / EXECUTING``).

PDF rendering is deferred behind the ``FormatTransformer`` Protocol seam,
mirroring AD-594a's ``InputProcessor`` precedent. Concrete transformers
ship for stdlib-covered formats (markdown -> HTML, JSON -> markdown).
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol, TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from probos.consultation.workspace import (
        ConsultationWorkspace,
        WorkspaceLifecycleState,
        WorkspaceRegistry,
    )

logger = logging.getLogger(__name__)

_DELIVERY_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Format transformers
# ---------------------------------------------------------------------------


class FormatTransformer(Protocol):
    """Convert one artifact's content + filename into a delivered shape.

    Returns ``(transformed_content, new_filename)`` where ``new_filename`` is
    the basename only (the adapter chooses the destination path).
    """

    def transform(self, content: str, *, source_path: str) -> tuple[str, str]: ...


class PassthroughTransformer:
    """Identity transformer; returns ``(content, basename(source_path))``."""

    def transform(self, content: str, *, source_path: str) -> tuple[str, str]:
        return content, _basename(source_path)


class MarkdownToHTMLTransformer:
    """Stdlib-only minimal markdown -> HTML renderer.

    Handles ATX headings, bold/italic/inline-code, fenced code blocks,
    unordered (``- ``) and ordered (``1. ``) lists, and blank-line
    paragraph splitting. NOT GFM-complete (no tables, task lists, link
    parsing). Docs-grade only; escapes ``<``, ``>``, ``&`` in text segments.
    """

    _CODE_FENCE = re.compile(r"^```(.*)$")
    _HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
    _UL_ITEM = re.compile(r"^-\s+(.*)$")
    _OL_ITEM = re.compile(r"^\d+\.\s+(.*)$")

    def transform(self, content: str, *, source_path: str) -> tuple[str, str]:
        lines = content.splitlines()
        out: list[str] = []
        i = 0
        in_para: list[str] = []
        in_ul = False
        in_ol = False

        def flush_para() -> None:
            nonlocal in_para
            if in_para:
                out.append("<p>" + " ".join(self._inline(s) for s in in_para) + "</p>")
                in_para = []

        def flush_lists() -> None:
            nonlocal in_ul, in_ol
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False

        while i < len(lines):
            line = lines[i]
            fence = self._CODE_FENCE.match(line)
            if fence:
                flush_para()
                flush_lists()
                lang = html.escape(fence.group(1).strip())
                code_lines: list[str] = []
                i += 1
                while i < len(lines) and not self._CODE_FENCE.match(lines[i]):
                    code_lines.append(html.escape(lines[i]))
                    i += 1
                cls = f' class="language-{lang}"' if lang else ""
                out.append(f"<pre><code{cls}>" + "\n".join(code_lines) + "</code></pre>")
                if i < len(lines):
                    i += 1  # consume closing fence
                continue

            if not line.strip():
                flush_para()
                flush_lists()
                i += 1
                continue

            heading = self._HEADING.match(line)
            if heading:
                flush_para()
                flush_lists()
                level = len(heading.group(1))
                text = self._inline(heading.group(2))
                out.append(f"<h{level}>{text}</h{level}>")
                i += 1
                continue

            ul = self._UL_ITEM.match(line)
            if ul:
                flush_para()
                if in_ol:
                    out.append("</ol>")
                    in_ol = False
                if not in_ul:
                    out.append("<ul>")
                    in_ul = True
                out.append(f"<li>{self._inline(ul.group(1))}</li>")
                i += 1
                continue

            ol = self._OL_ITEM.match(line)
            if ol:
                flush_para()
                if in_ul:
                    out.append("</ul>")
                    in_ul = False
                if not in_ol:
                    out.append("<ol>")
                    in_ol = True
                out.append(f"<li>{self._inline(ol.group(1))}</li>")
                i += 1
                continue

            flush_lists()
            in_para.append(line)
            i += 1

        flush_para()
        flush_lists()
        body = "\n".join(out)
        rendered = f"<!doctype html><html><body>{body}</body></html>"
        new_name = _basename(source_path)
        if new_name.lower().endswith(".md"):
            new_name = new_name[:-3] + ".html"
        else:
            stem = new_name.rsplit(".", 1)[0] if "." in new_name else new_name
            new_name = stem + ".html"
        return rendered, new_name

    @staticmethod
    def _inline(text: str) -> str:
        # Escape HTML first, then re-introduce inline tags via regex on escaped text.
        escaped = html.escape(text, quote=False)
        # Inline code first (so its contents are not re-interpreted).
        escaped = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", escaped)
        # Bold (must run before italic so ** is not consumed by *).
        escaped = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", escaped)
        # Italic
        escaped = re.sub(r"\*([^*]+)\*", lambda m: f"<em>{m.group(1)}</em>", escaped)
        return escaped


class JSONToMarkdownTransformer:
    """JSON dict/list -> markdown report. Top-level only; nested rendered as YAML."""

    def transform(self, content: str, *, source_path: str) -> tuple[str, str]:
        new_name = _basename(source_path)
        if new_name.lower().endswith(".json"):
            new_name = new_name[:-5] + ".md"
        else:
            stem = new_name.rsplit(".", 1)[0] if "." in new_name else new_name
            new_name = stem + ".md"
        try:
            parsed = json.loads(content)
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "AD-594d: JSONToMarkdownTransformer parse failed for %s; passing through",
                source_path,
            )
            return content, _basename(source_path)

        if isinstance(parsed, dict):
            sections: list[str] = []
            for key, value in parsed.items():
                sections.append(f"# {key}")
                sections.append("")
                sections.append(_render_value(value))
                sections.append("")
            return "\n".join(sections).rstrip() + "\n", new_name
        if isinstance(parsed, list):
            lines = [f"{idx + 1}. {_render_value_inline(item)}" for idx, item in enumerate(parsed)]
            return "\n".join(lines) + "\n", new_name
        return f"{parsed}\n", new_name


def _render_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)) or value is None:
        return str(value)
    rendered = yaml.safe_dump(value, sort_keys=False, default_flow_style=False).rstrip()
    return f"```yaml\n{rendered}\n```"


def _render_value_inline(value: Any) -> str:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)
    return yaml.safe_dump(value, sort_keys=False, default_flow_style=True).rstrip()


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1] or path


def build_format_transformer(name: str) -> FormatTransformer:
    """Factory: ``"passthrough" | "markdown_to_html" | "json_to_markdown" | ""``.

    Unknown name -> log WARNING and return ``PassthroughTransformer``
    (tier-2 log-and-degrade).
    """
    key = (name or "").strip().lower()
    if key in ("", "passthrough"):
        return PassthroughTransformer()
    if key == "markdown_to_html":
        return MarkdownToHTMLTransformer()
    if key == "json_to_markdown":
        return JSONToMarkdownTransformer()
    logger.warning(
        "AD-594d: unknown format transformer %r; falling back to passthrough", name,
    )
    return PassthroughTransformer()


# ---------------------------------------------------------------------------
# Adapter Protocol + dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeliveryArtifact:
    workspace_id: str
    source_path: str
    target_filename: str
    content: str
    content_type: str
    target_hint: str | None


@dataclass(frozen=True)
class AdapterResult:
    success: bool
    delivered_uri: str
    error: str = ""


class DeliveryAdapter(Protocol):
    """Protocol for one-shot artifact delivery to an external destination."""

    name: str

    async def deliver(self, request: DeliveryArtifact) -> AdapterResult: ...


@dataclass(frozen=True)
class DeliveryRequest:
    workspace_id: str
    source_paths: list[str]
    adapter: str
    transformer: str = "passthrough"
    target_hint: str | None = None
    atomic: bool = True
    requires_approval: bool = False


@dataclass
class DeliveryReceipt:
    delivery_id: str
    workspace_id: str
    state: str
    requested_at: float
    delivered_at: float | None
    adapter: str
    transformer: str
    items: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DeliveryReceipt":
        return cls(
            delivery_id=str(d.get("delivery_id", "")),
            workspace_id=str(d.get("workspace_id", "")),
            state=str(d.get("state", "")),
            requested_at=float(d.get("requested_at", 0.0)),
            delivered_at=(
                float(d["delivered_at"]) if d.get("delivered_at") is not None else None
            ),
            adapter=str(d.get("adapter", "")),
            transformer=str(d.get("transformer", "")),
            items=list(d.get("items") or []),
            summary=str(d.get("summary", "")),
        )


# ---------------------------------------------------------------------------
# LocalFileAdapter
# ---------------------------------------------------------------------------


class LocalFileAdapter:
    """Writes to a filesystem destination outside the records repo.

    Constructor-injected ``allowed_roots`` are resolved at ctor; every
    delivery target must resolve to a path under one of these roots.
    Empty ``allowed_roots`` is fail-safe (every delivery rejected).
    """

    name = "local_file"

    def __init__(self, allowed_roots: list[Path] | None = None) -> None:
        roots = allowed_roots or []
        self._allowed_roots: list[Path] = [Path(r).resolve() for r in roots]

    @property
    def allowed_roots(self) -> list[Path]:
        return list(self._allowed_roots)

    async def deliver(self, request: DeliveryArtifact) -> AdapterResult:
        if not self._allowed_roots:
            return AdapterResult(
                success=False,
                delivered_uri="",
                error="no allowed_roots configured",
            )
        if not request.target_hint:
            return AdapterResult(
                success=False,
                delivered_uri="",
                error="target_hint required for local_file adapter",
            )
        try:
            dest_dir = Path(request.target_hint).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            logger.warning(
                "AD-594d: invalid target_hint %r on workspace=%s adapter=%s: %s",
                request.target_hint, request.workspace_id, self.name, exc,
            )
            return AdapterResult(
                success=False, delivered_uri="", error=f"invalid target_hint: {exc}",
            )
        if not self._under_allowed(dest_dir):
            logger.warning(
                "AD-594d: path outside allowed_roots on workspace=%s adapter=%s dest=%s",
                request.workspace_id, self.name, dest_dir,
            )
            return AdapterResult(
                success=False,
                delivered_uri="",
                error=f"path outside allowed_roots: {dest_dir}",
            )
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            file_path = (dest_dir / request.target_filename).resolve()
            if not self._under_allowed(file_path):
                return AdapterResult(
                    success=False,
                    delivered_uri="",
                    error=f"path outside allowed_roots: {file_path}",
                )
            file_path.write_text(request.content, encoding="utf-8")
        except OSError as exc:
            logger.warning(
                "AD-594d: write failed on workspace=%s adapter=%s: %s",
                request.workspace_id, self.name, exc,
            )
            return AdapterResult(
                success=False, delivered_uri="", error=f"write failed: {exc}",
            )
        uri = "file:///" + str(file_path).replace("\\", "/").lstrip("/")
        return AdapterResult(success=True, delivered_uri=uri, error="")

    async def rollback(self, uri: str) -> bool:
        """Delete a previously delivered file. Idempotent (missing -> True)."""
        if not uri.startswith("file:///"):
            logger.warning("AD-594d: rollback URI not file:// scheme: %s", uri)
            return False
        raw = uri[len("file:///") :]
        # Re-add leading slash on POSIX paths
        if not raw.startswith("/") and not (len(raw) >= 2 and raw[1] == ":"):
            raw = "/" + raw
        try:
            target = Path(raw).resolve()
        except (OSError, RuntimeError) as exc:
            logger.warning("AD-594d: rollback resolve failed for %s: %s", uri, exc)
            return False
        if not self._under_allowed(target):
            logger.warning(
                "AD-594d: rollback target outside allowed_roots: %s", target,
            )
            return False
        try:
            if target.exists():
                target.unlink()
            return True
        except OSError as exc:
            logger.warning("AD-594d: rollback unlink failed for %s: %s", target, exc)
            return False

    def _under_allowed(self, path: Path) -> bool:
        for root in self._allowed_roots:
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False


# ---------------------------------------------------------------------------
# GitHubAdapter
# ---------------------------------------------------------------------------


HttpPostFn = Callable[..., Awaitable[tuple[int, dict[str, Any]]]]


class GitHubAdapter:
    """PUT https://api.github.com/repos/{owner}/{repo}/contents/{path}.

    Auth via env-resolved token (default ``GITHUB_TOKEN``). Constructor
    accepts an injected ``http_post`` callable for testability; default
    impl uses ``httpx.AsyncClient`` (imported lazily so importing this
    module does not pull httpx in unless GitHub delivery is wired).
    """

    name = "github"

    def __init__(
        self,
        *,
        token_env: str = "GITHUB_TOKEN",
        http_post: HttpPostFn | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._token_env = token_env
        self._http_post: HttpPostFn = http_post or self._default_http_post
        self._clock = clock

    async def deliver(self, request: DeliveryArtifact) -> AdapterResult:
        token = os.environ.get(self._token_env, "")
        if not token:
            logger.warning(
                "AD-594d: no token in env %s on workspace=%s adapter=%s",
                self._token_env, request.workspace_id, self.name,
            )
            return AdapterResult(
                success=False,
                delivered_uri="",
                error=f"no token in env {self._token_env}",
            )
        if not request.target_hint:
            return AdapterResult(
                success=False,
                delivered_uri="",
                error="target_hint required (owner/repo:branch:path)",
            )
        parsed = self._parse_hint(request.target_hint)
        if parsed is None:
            return AdapterResult(
                success=False,
                delivered_uri="",
                error=f"invalid target_hint: {request.target_hint!r} (expect owner/repo:branch:path)",
            )
        owner_repo, branch, path = parsed
        owner, _, repo = owner_repo.partition("/")
        if not owner or not repo:
            return AdapterResult(
                success=False,
                delivered_uri="",
                error=f"invalid owner/repo segment: {owner_repo!r}",
            )
        path_segment = path.strip("/")
        joined = (
            f"{path_segment}/{request.target_filename}"
            if path_segment
            else request.target_filename
        )
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{joined}"
        body: dict[str, Any] = {
            "message": "AD-594d delivery",
            "content": base64.b64encode(request.content.encode("utf-8")).decode("ascii"),
        }
        if branch:
            body["branch"] = branch
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        try:
            status, payload = await self._http_post(url=url, headers=headers, json=body)
        except Exception as exc:  # noqa: BLE001 — adapter must never raise
            logger.warning(
                "AD-594d: github http call failed on workspace=%s adapter=%s: %s",
                request.workspace_id, self.name, exc,
            )
            return AdapterResult(
                success=False, delivered_uri="", error=f"http error: {exc}",
            )
        if 200 <= status < 300:
            html_url = ""
            if isinstance(payload, dict):
                content = payload.get("content")
                if isinstance(content, dict):
                    html_url = str(content.get("html_url") or "")
            return AdapterResult(success=True, delivered_uri=html_url, error="")
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("message") or payload.get("error") or "")
        if not message:
            message = f"http {status}"
        logger.warning(
            "AD-594d: github non-2xx on workspace=%s adapter=%s status=%d: %s",
            request.workspace_id, self.name, status, message,
        )
        return AdapterResult(success=False, delivered_uri="", error=message)

    @staticmethod
    def _parse_hint(hint: str) -> tuple[str, str, str] | None:
        parts = hint.split(":")
        if len(parts) != 3:
            return None
        owner_repo, branch, path = parts
        if not owner_repo:
            return None
        return owner_repo, branch, path

    async def _default_http_post(
        self, *, url: str, headers: dict[str, str], json: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        import httpx  # lazy import — see module docstring
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.put(url, headers=headers, json=json)
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
        return resp.status_code, payload


# ---------------------------------------------------------------------------
# DeliveryPipeline
# ---------------------------------------------------------------------------


class DeliveryPipeline:
    """Owns adapter registry + executes ``DeliveryRequest``s against a registry.

    See module docstring for the full behavior contract.
    """

    def __init__(
        self,
        registry: "WorkspaceRegistry",
        *,
        adapters: dict[str, DeliveryAdapter] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if registry is None:
            raise ValueError("DeliveryPipeline requires a WorkspaceRegistry")
        self._registry = registry
        self._adapters: dict[str, DeliveryAdapter] = {}
        if adapters:
            for adp in adapters.values():
                self.register_adapter(adp)
        self._clock = clock

    # ------------------------------------------------------------------
    # Adapter registry
    # ------------------------------------------------------------------
    def register_adapter(self, adapter: DeliveryAdapter) -> None:
        name = getattr(adapter, "name", None)
        if not name or not isinstance(name, str):
            raise ValueError("DeliveryAdapter must expose a non-empty 'name' attribute")
        if name in self._adapters:
            logger.warning(
                "AD-594d: adapter %r already registered; replacing", name,
            )
        self._adapters[name] = adapter

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters)

    # ------------------------------------------------------------------
    # Public API: deliver / approve / reject / list / revise
    # ------------------------------------------------------------------
    async def deliver(
        self, request: DeliveryRequest, *, agent_id: str = "captain",
    ) -> DeliveryReceipt:
        delivery_id = uuid.uuid4().hex[:12]
        ws = await self._registry.get(request.workspace_id)
        receipt = DeliveryReceipt(
            delivery_id=delivery_id,
            workspace_id=request.workspace_id,
            state="pending_approval" if request.requires_approval else "pending",
            requested_at=self._clock(),
            delivered_at=None,
            adapter=request.adapter,
            transformer=request.transformer,
            items=[],
            summary="",
        )
        if ws is None:
            receipt.state = "failed"
            receipt.summary = f"workspace not found: {request.workspace_id}"
            logger.warning(
                "AD-594d: deliver on missing workspace=%s adapter=%s",
                request.workspace_id, request.adapter,
            )
            return receipt

        if request.requires_approval:
            receipt.summary = f"pending approval ({len(request.source_paths)} item(s))"
            await self._persist_receipt(ws, receipt)
            await self._safe_journal(
                ws,
                f"delivery {delivery_id} pending approval (adapter={request.adapter})",
                agent_id,
            )
            return receipt

        await self._dispatch(ws, request, receipt, agent_id=agent_id)
        return receipt

    async def approve(
        self,
        workspace_id: str,
        delivery_id: str,
        *,
        agent_id: str = "captain",
    ) -> DeliveryReceipt | None:
        ws = await self._registry.get(workspace_id)
        if ws is None:
            return None
        receipts = await self._load_receipts(ws)
        receipt = next((r for r in receipts if r.delivery_id == delivery_id), None)
        if receipt is None:
            return None
        if receipt.state != "pending_approval":
            return receipt
        request = DeliveryRequest(
            workspace_id=workspace_id,
            source_paths=[item.get("source_path", "") for item in receipt.items]
            or [],
            adapter=receipt.adapter,
            transformer=receipt.transformer,
            target_hint=None,
            atomic=True,
            requires_approval=False,
        )
        # Reset items for fresh dispatch.
        receipt.items = []
        receipt.state = "approved"
        await self._dispatch(
            ws, request, receipt, agent_id=agent_id, action_label="approved",
        )
        return receipt

    async def reject(
        self,
        workspace_id: str,
        delivery_id: str,
        *,
        agent_id: str = "captain",
        reason: str = "",
    ) -> DeliveryReceipt | None:
        ws = await self._registry.get(workspace_id)
        if ws is None:
            return None
        receipts = await self._load_receipts(ws)
        receipt = next((r for r in receipts if r.delivery_id == delivery_id), None)
        if receipt is None:
            return None
        receipt.state = "rolled_back"
        receipt.delivered_at = self._clock()
        receipt.summary = f"rejected: {reason}" if reason else "rejected"
        await self._persist_receipt(ws, receipt)
        await self._safe_journal(
            ws,
            f"delivery {delivery_id} rejected: {reason}" if reason
            else f"delivery {delivery_id} rejected",
            agent_id,
        )
        return receipt

    async def list_deliveries(self, workspace_id: str) -> list[DeliveryReceipt]:
        ws = await self._registry.get(workspace_id)
        if ws is None:
            return []
        return await self._load_receipts(ws)

    async def revise(
        self,
        workspace_id: str,
        *,
        target: "WorkspaceLifecycleState",
        agent_id: str = "captain",
        reason: str = "",
    ) -> bool:
        ws = await self._registry.get(workspace_id)
        if ws is None:
            return False
        ok = await ws.transition_to(target, agent_id=agent_id)
        if ok and reason:
            await self._safe_journal(
                ws, f"revise -> {target.name}: {reason}", agent_id,
            )
        return ok

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _dispatch(
        self,
        ws: "ConsultationWorkspace",
        request: DeliveryRequest,
        receipt: DeliveryReceipt,
        *,
        agent_id: str,
        action_label: str = "delivered",
    ) -> None:
        adapter = self._adapters.get(request.adapter)
        if adapter is None:
            receipt.state = "failed"
            receipt.summary = f"adapter not registered: {request.adapter}"
            receipt.delivered_at = self._clock()
            logger.warning(
                "AD-594d: adapter %r not registered on workspace=%s",
                request.adapter, request.workspace_id,
            )
            await self._persist_receipt(ws, receipt)
            await self._safe_journal(
                ws,
                f"delivery {receipt.delivery_id} failed: adapter {request.adapter} not registered",
                agent_id,
            )
            return

        transformer = build_format_transformer(request.transformer)
        successes: list[tuple[dict[str, str], AdapterResult]] = []
        failed = False
        for src in request.source_paths:
            item: dict[str, str] = {
                "source_path": src,
                "target_filename": "",
                "delivered_uri": "",
                "error": "",
                "success": "false",
            }
            ws_path = self._workspace_path(ws, src)
            content = await self._safe_read(ws, ws_path)
            if content is None:
                item["error"] = f"source missing: {src}"
                receipt.items.append(item)
                logger.warning(
                    "AD-594d: source missing on workspace=%s adapter=%s path=%s",
                    request.workspace_id, request.adapter, src,
                )
                if request.atomic:
                    failed = True
                    break
                continue
            try:
                transformed, new_filename = transformer.transform(
                    content, source_path=src,
                )
            except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
                item["error"] = f"transform failed: {exc}"
                receipt.items.append(item)
                logger.warning(
                    "AD-594d: transform failed on workspace=%s adapter=%s: %s",
                    request.workspace_id, request.adapter, exc,
                )
                if request.atomic:
                    failed = True
                    break
                continue
            item["target_filename"] = new_filename
            artifact = DeliveryArtifact(
                workspace_id=request.workspace_id,
                source_path=src,
                target_filename=new_filename,
                content=transformed,
                content_type=_content_type_for(new_filename),
                target_hint=request.target_hint,
            )
            try:
                result = await adapter.deliver(artifact)
            except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
                logger.warning(
                    "AD-594d: adapter raised on workspace=%s adapter=%s: %s",
                    request.workspace_id, request.adapter, exc,
                )
                result = AdapterResult(
                    success=False, delivered_uri="", error=f"adapter raised: {exc}",
                )
            item["delivered_uri"] = result.delivered_uri
            item["error"] = result.error
            item["success"] = "true" if result.success else "false"
            receipt.items.append(item)
            if result.success:
                successes.append((item, result))
            else:
                if request.atomic:
                    failed = True
                    break

        if request.atomic and failed:
            # Roll back any successful prior items where the adapter supports it.
            await self._rollback_items(adapter, successes, receipt)
            receipt.state = "failed"
        elif request.atomic:
            receipt.state = "delivered"
        else:
            any_success = any(item.get("success") == "true" for item in receipt.items)
            receipt.state = "delivered" if any_success else "failed"

        receipt.delivered_at = self._clock()
        if not receipt.summary:
            ok_count = sum(1 for it in receipt.items if it.get("success") == "true")
            receipt.summary = (
                f"{action_label}: {ok_count}/{len(receipt.items)} item(s)"
            )
        await self._persist_receipt(ws, receipt)
        await self._safe_journal(
            ws,
            f"delivery {receipt.delivery_id} {receipt.state} "
            f"(adapter={request.adapter}, {receipt.summary})",
            agent_id,
        )

    async def _rollback_items(
        self,
        adapter: DeliveryAdapter,
        successes: list[tuple[dict[str, str], AdapterResult]],
        receipt: DeliveryReceipt,
    ) -> None:
        rollback_fn = getattr(adapter, "rollback", None)
        for item, result in successes:
            if rollback_fn is None:
                item["error"] = item.get("error") or "rollback not supported by adapter"
                continue
            try:
                ok = await rollback_fn(result.delivered_uri)
            except Exception as exc:  # noqa: BLE001 — tier-2 log-and-degrade
                logger.warning(
                    "AD-594d: rollback raised on workspace=%s adapter=%s: %s",
                    receipt.workspace_id, getattr(adapter, "name", "?"), exc,
                )
                ok = False
            item["success"] = "false"
            item["delivered_uri"] = "" if ok else item.get("delivered_uri", "")
            item["error"] = (
                "rolled back due to atomic failure" if ok
                else item.get("error") or "rollback failed"
            )

    @staticmethod
    def _workspace_path(ws: "ConsultationWorkspace", src: str) -> str:
        # Accept either workspace-relative ("outputs/x.md") or already
        # rooted ("consultations/<id>/outputs/x.md").
        if src.startswith("consultations/"):
            return src
        return f"{ws.root_path}/{src.lstrip('/')}"

    @staticmethod
    async def _safe_read(ws: "ConsultationWorkspace", path: str) -> str | None:
        try:
            # ws._records is the records store; reuse the same plumbing the
            # workspace itself uses (read-only, raw text).
            return await ws._records.read_workspace_file(path)  # noqa: SLF001
        except Exception:  # noqa: BLE001 — tier-2 log-and-degrade
            logger.warning(
                "AD-594d: read failed on workspace=%s path=%s",
                ws.id, path, exc_info=True,
            )
            return None

    async def _safe_journal(
        self, ws: "ConsultationWorkspace", message: str, agent_id: str,
    ) -> None:
        try:
            await ws.append_journal(message, agent_id=agent_id)
        except Exception:  # noqa: BLE001 — tier-2 log-and-degrade
            logger.warning(
                "AD-594d: journal append failed on workspace=%s",
                ws.id, exc_info=True,
            )

    async def _load_receipts(
        self, ws: "ConsultationWorkspace",
    ) -> list[DeliveryReceipt]:
        path = f"{ws.root_path}/delivery.yaml"
        try:
            text = await ws._records.read_workspace_file(path)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            logger.warning(
                "AD-594d: delivery.yaml read failed on workspace=%s",
                ws.id, exc_info=True,
            )
            return []
        if not text:
            return []
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            logger.warning(
                "AD-594d: delivery.yaml malformed on workspace=%s", ws.id,
            )
            return []
        if not isinstance(doc, dict):
            return []
        deliveries = doc.get("deliveries") or []
        out: list[DeliveryReceipt] = []
        for entry in deliveries:
            if isinstance(entry, dict):
                try:
                    out.append(DeliveryReceipt.from_dict(entry))
                except (TypeError, ValueError):
                    continue
        return out

    async def _persist_receipt(
        self, ws: "ConsultationWorkspace", receipt: DeliveryReceipt,
    ) -> None:
        path = f"{ws.root_path}/delivery.yaml"
        existing = await self._load_receipts(ws)
        # Upsert by delivery_id.
        replaced = False
        merged: list[DeliveryReceipt] = []
        for r in existing:
            if r.delivery_id == receipt.delivery_id:
                merged.append(receipt)
                replaced = True
            else:
                merged.append(r)
        if not replaced:
            merged.append(receipt)
        doc = {
            "schema_version": _DELIVERY_SCHEMA_VERSION,
            "deliveries": [r.to_dict() for r in merged],
        }
        text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
        try:
            await ws._records.write_workspace_file(  # noqa: SLF001
                "captain", path, text,
                f"AD-594d: delivery receipt {receipt.delivery_id} on {ws.id}",
            )
        except Exception:  # noqa: BLE001 — tier-2 log-and-degrade
            logger.warning(
                "AD-594d: persist receipt failed on workspace=%s delivery=%s",
                ws.id, receipt.delivery_id, exc_info=True,
            )


def _content_type_for(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".html") or lower.endswith(".htm"):
        return "text/html"
    if lower.endswith(".md") or lower.endswith(".markdown"):
        return "text/markdown"
    if lower.endswith(".json"):
        return "application/json"
    return "text/plain"


__all__ = [
    "AdapterResult",
    "DeliveryAdapter",
    "DeliveryArtifact",
    "DeliveryPipeline",
    "DeliveryReceipt",
    "DeliveryRequest",
    "FormatTransformer",
    "GitHubAdapter",
    "JSONToMarkdownTransformer",
    "LocalFileAdapter",
    "MarkdownToHTMLTransformer",
    "PassthroughTransformer",
    "build_format_transformer",
]
