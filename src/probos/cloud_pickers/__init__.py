"""AD-720c: OAuth-bound cloud file pickers (Google Drive v1; OneDrive/Dropbox stubs).

All file bytes flow through ``AttachmentStore.write(sha, blob, mime)`` per
AD-731 — the browser never sees raw bytes, only the SHA ref. Tokens are
stored exclusively in the AD-706f ``CredentialVault`` under refs of the form
``cloud_provider:{provider_id}:{captain_id}``.
"""
