"""AD-805: Microsoft Teams channel adapter.

Inbound: webhook-driven (Bot Framework POSTs activities to
``/api/channels/teams/webhook``). Unlike Telegram/Slack/Matrix this
adapter does NOT run a polling loop — Bot Service pushes activities at
us and we dispatch via ``dispatch_activity()``.

Outbound: via :class:`TeamsClient.send_activity` which acquires a
client-credentials token from
``login.microsoftonline.com/botframework.com`` (cached in-memory) and
POSTs to ``{serviceUrl}/v3/conversations/{id}/activities``, or to
``.../activities/{activityId}`` when threading a reply (BF-802).

Pairing: AD-802a hook fires via ``channel_name = "teams"`` and the
base-class ``_check_pairing`` machinery. The sender's AAD object ID
(``from.aadObjectId``) is the stable identity used for pairing
resolution; we fall back to ``from.id`` when AAD ID is absent.

Forward markers:
    * AD-805a — full AAD OAuth (federated identity, managed identity)
    * AD-805b — JWT signature verification of the inbound webhook
    * AD-805c — Adaptive Cards rendering for richer replies
"""

from __future__ import annotations

import logging
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.channels.teams_client import TeamsAPIError, TeamsClient
from probos.channels.teams_config import TeamsAdapterConfig

logger = logging.getLogger(__name__)


class TeamsAdapter(ChannelAdapter):
    """Microsoft Teams Bot Framework adapter (webhook inbound)."""

    channel_name = "teams"

    def __init__(
        self,
        runtime: Any,
        config: TeamsAdapterConfig,
        *,
        client: TeamsClient | None = None,
    ) -> None:
        super().__init__(runtime, config)
        self._teams_config = config
        self._client = client or TeamsClient(
            app_id=config.app_id,
            app_password=config.app_password,
        )
        # Map conversation_id -> serviceUrl (Bot Framework requires us
        # to remember which Azure region a conversation lives in to
        # send replies back).
        self._service_urls: dict[str, str] = {}

    async def start(self) -> None:
        if self._started:
            return
        if not self._teams_config.app_id or not self._teams_config.app_password:
            logger.warning(
                "AD-805: TeamsAdapter has no app_id/app_password; webhook "
                "will accept activities but outbound replies will fail"
            )
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self._client.aclose()
        self._started = False

    def _extract_message(self, activity: dict) -> ChannelMessage | None:
        """Convert a Bot Framework Activity into a ChannelMessage.

        Returns None for non-message activity types (typing, contactRelationUpdate,
        conversationUpdate, etc.) which we don't dispatch in v1.
        """
        if activity.get("type") != "message":
            return None
        from_obj = activity.get("from") or {}
        user_id = from_obj.get("aadObjectId") or from_obj.get("id") or ""
        if not user_id:
            return None

        # AD-805 allow-list enforcement
        if (
            self._teams_config.allowed_user_aads
            and user_id not in self._teams_config.allowed_user_aads
        ):
            return None
        conversation = activity.get("conversation") or {}
        team_id = (
            conversation.get("teamId")
            or (activity.get("channelData") or {}).get("team", {}).get("id")
            or ""
        )
        if (
            self._teams_config.allowed_team_ids
            and team_id
            and team_id not in self._teams_config.allowed_team_ids
        ):
            return None

        text = (activity.get("text") or "").strip()
        if not text:
            return None
        return ChannelMessage(
            text=text,
            channel_id=conversation.get("id", ""),
            user_id=user_id,
            user_display_name=from_obj.get("name", ""),
            reply_to_message_id=activity.get("id"),
        )

    async def dispatch_activity(self, activity: dict) -> dict:
        """Called by the FastAPI webhook handler for each inbound activity.

        Returns a dict with ``status`` for the HTTP response. Always
        returns 200-shape (Bot Framework retries on non-2xx, which would
        cause duplicate dispatch).
        """
        # Remember serviceUrl for outbound replies on this conversation.
        service_url = activity.get("serviceUrl")
        conversation = activity.get("conversation") or {}
        conv_id = conversation.get("id")
        if service_url and conv_id:
            self._service_urls[conv_id] = service_url

        msg = self._extract_message(activity)
        if msg is None:
            return {"status": "ignored", "reason": "non-message-or-filtered"}

        # BF-802 (#1266): handle_message RETURNS the reply; it does not send
        # it. Teams discarded that return, so the crew reasoned, produced an
        # answer, and the Captain saw silence. Forward it to send_response the
        # way Telegram and Discord already do.
        reply = await self.handle_message(msg)
        if reply:
            await self.send_response(
                msg.channel_id,
                reply,
                # BF-802: `_extract_message` sets this and the dispatcher used
                # to drop it, so every Teams reply reached the client with
                # reply_to_id=None and threaded nowhere.
                reply_to_message_id=msg.reply_to_message_id,
            )
        return {"status": "ok"}

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        service_url = self._service_urls.get(channel_id)
        if not service_url:
            logger.warning(
                "AD-805: no serviceUrl cached for conversation %s; "
                "cannot send reply (was the conversation initiated by an "
                "inbound activity?)",
                channel_id,
            )
            return
        try:
            await self._client.send_activity(
                service_url=service_url,
                conversation_id=channel_id,
                text=response,
                reply_to_id=kwargs.get("reply_to_message_id"),
            )
        except TeamsAPIError as exc:
            logger.warning("AD-805: send_activity failed: %s", exc)
