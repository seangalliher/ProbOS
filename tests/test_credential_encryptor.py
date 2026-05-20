"""AD-754: CredentialEncryptor tests."""

from __future__ import annotations

from probos.security.credential_encryption import CredentialEncryptor


def test_store_retrieve_roundtrip(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {}

    def _set_password(service: str, username: str, value: str) -> None:
        values[(service, username)] = value

    def _get_password(service: str, username: str) -> str | None:
        return values.get((service, username))

    monkeypatch.setattr("keyring.set_password", _set_password)
    monkeypatch.setattr("keyring.get_password", _get_password)

    encryptor = CredentialEncryptor(app_name="ProbOSTest")
    encryptor.store("m365_refresh_token", "token-value")

    assert encryptor.retrieve("m365_refresh_token") == "token-value"


def test_delete_removes_credential(monkeypatch) -> None:
    values: dict[tuple[str, str], str] = {("ProbOSTest", "m365_refresh_token"): "token-value"}

    def _delete_password(service: str, username: str) -> None:
        values.pop((service, username), None)

    def _get_password(service: str, username: str) -> str | None:
        return values.get((service, username))

    monkeypatch.setattr("keyring.delete_password", _delete_password)
    monkeypatch.setattr("keyring.get_password", _get_password)

    encryptor = CredentialEncryptor(app_name="ProbOSTest")
    encryptor.delete("m365_refresh_token")

    assert encryptor.retrieve("m365_refresh_token") is None
