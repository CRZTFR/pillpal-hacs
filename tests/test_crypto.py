"""crypto.py against the lamp contract's own vectors (integration_approval.json)."""
from custom_components.pill_pal.crypto import Approval, framed, read_tag, tag

from .conftest import fixture

APPROVAL = fixture("integration_approval.json")


def test_every_vector() -> None:
    for case in APPROVAL["cases"]:
        integration = Approval.from_private_bytes(bytes.fromhex(case["integrationPrivateKey"]))
        lamp = Approval.from_private_bytes(bytes.fromhex(case["lampPrivateKey"]))
        assert integration.public_key.hex() == case["integrationPublicKey"], case["id"]
        assert lamp.public_key.hex() == case["lampPublicKey"], case["id"]
        assert integration.shared(lamp.public_key).hex() == case["sharedSecret"], case["id"]
        key, code = integration.derive(
            case["deviceId"], bytes.fromhex(case["requestId"]), lamp.public_key
        )
        assert key.hex() == case["grantKey"], case["id"]
        assert code == case["code"], case["id"]


def test_codes_are_six_digits_with_leading_zeros() -> None:
    for case in APPROVAL["cases"]:
        assert len(case["code"]) == 6 and case["code"].isdigit()


def test_framing() -> None:
    assert framed("ab", b"\x01") == b"\x00\x00\x00\x02ab\x00\x00\x00\x01\x01"


def test_tags() -> None:
    key = bytes(range(32))
    assert len(tag(key, b"x")) == 32
    assert read_tag(key, "/events", 9, "n") == tag(key, b"GET /events\n9\nn")
