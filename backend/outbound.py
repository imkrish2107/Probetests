"""WhatsApp sends for the agents dashboard: Graph helpers only.

Safety: sellers are messaged only after a logged-in user clicks, with an
opted-in seller from our database. This module never decides recipients.
"""
import json
import os

GRAPH = "https://graph.facebook.com/v21.0"


def creds() -> tuple[str, str]:
    from dotenv import load_dotenv
    load_dotenv()
    token = os.getenv("WHATSAPP_TOKEN", "")
    pnid = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    if not token or not pnid:
        raise RuntimeError("WHATSAPP_TOKEN / WHATSAPP_PHONE_NUMBER_ID missing in backend/.env")
    return token, pnid


class GraphError(Exception):
    def __init__(self, status: int, body: str):
        super().__init__(f"graph {status}: {body[:200]}")
        self.status = status
        self.body = body


def _call(method: str, path: str, token: str, **kw) -> dict:
    import httpx
    r = httpx.request(method, f"{GRAPH}/{path}", headers={"Authorization": f"Bearer {token}"},
                      timeout=20, **kw)
    try:
        data = r.json()
    except ValueError:
        data = {}
    if r.status_code >= 400 or (isinstance(data, dict) and data.get("error")):
        raise GraphError(r.status_code, json.dumps(data.get("error", r.text)))
    return data if isinstance(data, dict) else {}


def template_payload(to: str, name: str, lang: str, params: list[str]) -> dict:
    """Pure approved-template payload. Params are database values only."""
    return {
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to, "type": "template",
        "template": {"name": name, "language": {"code": lang},
                     "components": [{"type": "body", "parameters": [
                         {"type": "text", "text": p} for p in params]}]}}


def send_template(to: str, name: str, lang: str, params: list[str]) -> dict:
    """Send an approved UTILITY template. Raises GraphError when the template
    is missing or unapproved; the caller decides the fallback."""
    token, pnid = creds()
    return _call("POST", f"{pnid}/messages", token,
                 json=template_payload(to, name, lang, params))


def send_text(to: str, text: str) -> dict:
    """Free-form text; needs the 24h service window open."""
    token, pnid = creds()
    return _call("POST", f"{pnid}/messages", token, json={
        "messaging_product": "whatsapp", "recipient_type": "individual",
        "to": to, "type": "text", "text": {"body": text}})


def selfcheck() -> None:
    """Offline: template payload shape only. Never touches the network."""
    p = template_payload("+911234567890", "stock_check", "en",
                         ["Meera", "Escape Oversized Tee", "M"])
    t = p["template"]
    assert t["name"] == "stock_check" and t["language"] == {"code": "en"}
    assert [x["text"] for x in t["components"][0]["parameters"]] == [
        "Meera", "Escape Oversized Tee", "M"]
    print("outbound selfcheck: PASS")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "selfcheck":
        selfcheck()
    else:
        print("usage: python outbound.py selfcheck")
