"""AD-809: chat-handler slash-command helpers.

This package groups the per-command parser+handler pairs that the chat
routers consume before dispatching an IntentMessage. Each slash
command is a small, self-contained module: it inspects the message
body, applies any thread-state side effects, and returns a structured
result the router serializes into a system reply.
"""
