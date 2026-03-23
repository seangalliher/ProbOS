"""Channel adapters for external messaging integrations."""

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.utils.response_formatter import extract_response_text

__all__ = ["ChannelAdapter", "ChannelMessage", "extract_response_text"]
