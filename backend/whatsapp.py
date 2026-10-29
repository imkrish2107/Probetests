"""WhatsApp Graph API helpers (step 2: signature only)."""
import hashlib
import hmac


def verify_signature(payload: bytes, signature: str, app_secret: str) -> bool:
    """Check X-Hub-Signature-256 ('sha256=<hex>')."""
    if not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature.removeprefix("sha256="), expected)


def iter_value_items(event: dict):
    """Yield (phone_number_id, kind, item); kinds: call | message | status."""
    for entry in event.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            pnid = value.get("metadata", {}).get("phone_number_id", "")
            for item in value.get("calls", []):
                yield pnid, "call", item
            for item in value.get("messages", []):
                yield pnid, "message", item
            for item in value.get("statuses", []):
                yield pnid, "status", item


def selfcheck() -> None:
    event = {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "123"},
        "messages": [{"from": "u1", "type": "text"}],
        "statuses": [{"id": "w1", "status": "read"}],
        "calls": [{"event": "connect"}]}}]}]}
    assert list(iter_value_items(event)) == [
        ("123", "call", {"event": "connect"}),
        ("123", "message", {"from": "u1", "type": "text"}),
        ("123", "status", {"id": "w1", "status": "read"})]
    assert list(iter_value_items({})) == []
    print("whatsapp selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python whatsapp.py selfcheck")
