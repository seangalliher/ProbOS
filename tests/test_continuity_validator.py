import pytest
from probos.identity import ContinuityValidator

def test_continuity_validator_checksum():
    validator = ContinuityValidator()
    card_dict = {"id": "captain-1", "name": "Jean-Luc Picard", "email": "picard@starfleet.com"}
    checksum = validator.compute_checksum(card_dict)
    assert isinstance(checksum, str)
    assert len(checksum) == 64


def test_continuity_validator_validate():
    validator = ContinuityValidator()
    card_dict = {"id": "captain-1", "name": "Jean-Luc Picard", "email": "picard@starfleet.com"}
    checksum = validator.compute_checksum(card_dict)
    assert validator.validate(card_dict, checksum)
    assert not validator.validate(card_dict, "badchecksum")
