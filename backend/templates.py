"""WhatsApp templates: bodies per language + create/status CLI.

Run `python templates.py dry-run` offline; create/status need WHATSAPP_TOKEN.
"""
import os
import sys

# shortcut: full bodies for demo languages (en/hi/ta); others fall back to English
TEMPLATES: dict[str, dict] = {
    "booking_confirmed": {"button": None, "body": {
        "en": "Hi {{1}}, your booking at {{2}} is confirmed for {{3}}. Reply here if you need to change it.",
        "hi": "नमस्ते {{1}}, {{2}} में आपकी बुकिंग {{3}} के लिए पक्की हो गई है। बदलाव के लिए यहीं जवाब दें।",
        "ta": "வணக்கம் {{1}}, {{2}}-இல் உங்கள் முன்பதிவு {{3}} அன்று உறுதி செய்யப்பட்டது. மாற்ற வேண்டுமென்றால் இங்கே பதில் அனுப்புங்கள்."}},
    "booking_reminder": {"button": None, "body": {
        "en": "Hi {{1}}, a reminder of your booking at {{2}} today at {{3}}. See you soon.",
        "hi": "नमस्ते {{1}}, आज {{3}} बजे {{2}} में आपकी बुकिंग की याद दिला रहे हैं। जल्द मिलते हैं।",
        "ta": "வணக்கம் {{1}}, இன்று {{3}} மணிக்கு {{2}}-இல் உங்கள் முன்பதிவு நினைவூட்டல். விரைவில் சந்திப்போம்."}},
    "booking_changed": {"button": None, "body": {
        "en": "Hi {{1}}, your booking at {{2}} is now {{3}}.",
        "hi": "नमस्ते {{1}}, {{2}} में आपकी बुकिंग अब {{3}} हो गई है।",
        "ta": "வணக்கம் {{1}}, {{2}}-இல் உங்கள் முன்பதிவு இப்போது {{3}}."}},
    "message_received": {"button": None, "body": {
        "en": "Hi {{1}}, thanks for calling {{2}}. We got your request and will update you here soon.",
        "hi": "नमस्ते {{1}}, {{2}} को कॉल करने के लिए धन्यवाद। आपका अनुरोध मिल गया है, जल्द ही यहीं बताएंगे।",
        "ta": "வணக்கம் {{1}}, {{2}}-ஐ அழைத்ததற்கு நன்றி. உங்கள் கோரிக்கை கிடைத்தது, விரைவில் இங்கே தெரிவிப்போம்."}},
    "task_done": {"button": None, "body": {
        "en": "Hi {{1}}, an update from {{2}} on your request: {{3}}",
        "hi": "नमस्ते {{1}}, आपके अनुरोध पर {{2}} की ओर से जानकारी: {{3}}",
        "ta": "வணக்கம் {{1}}, உங்கள் கோரிக்கை குறித்து {{2}}-இடமிருந்து தகவல்: {{3}}"}},
    "call_thanks": {"button": None, "body": {
        "en": "Hi {{1}}, thanks for calling {{2}}. Reply here anytime if you have more questions.",
        "hi": "नमस्ते {{1}}, {{2}} को कॉल करने के लिए धन्यवाद। और सवाल हों तो कभी भी यहीं लिखें।",
        "ta": "வணக்கம் {{1}}, {{2}}-ஐ அழைத்ததற்கு நன்றி. மேலும் கேள்விகள் இருந்தால் எப்போதும் இங்கே எழுதுங்கள்."}},
    "call_us": {"button": "Call Now", "body": {        "en": "Hi {{1}}, {{2}} would like to talk to you. Tap below to call us on WhatsApp.",
        "hi": "नमस्ते {{1}}, {{2}} आपसे बात करना चाहता है। WhatsApp पर कॉल करने के लिए नीचे दबाएं।",
        "ta": "வணக்கம் {{1}}, {{2}} உங்களுடன் பேச விரும்புகிறது. WhatsApp-இல் அழைக்க கீழே தட்டுங்கள்."}},
    "owner_new_lead": {"button": None, "body": {
        "en": "New call at {{1}}: {{2}}",
        "hi": "नई कॉल ({{1}}): {{2}}",
        "ta": "புதிய அழைப்பு ({{1}}): {{2}}"}},
    "otp_code": {"button": "Copy code", "category": "AUTHENTICATION", "body": {
        # en only: Meta owns authentication-template wording; approval takes
        # up to 24h, then `status` shows APPROVED and OTPs leave the 24h window.
        "en": "{{1}} is your ESCAPE verification code. It expires in 5 minutes. Never share it."}},
    "stock_check": {"langs": ["en"], "buttons": ["In stock", "Out of stock"], "body": {
        "en": "Hello {{1}}, a customer is asking about {{2}} in size {{3}}. Listing: {{4}}. Is it still in stock, and what is your final price with delivery to {{5}}? Thank you."}},
    "order_request": {"langs": ["en"], "buttons": ["Confirm order", "Can't fulfil"], "body": {
        "en": "Hello {{1}}, please confirm this order for {{2}}, size {{3}}, at {{4}}. Deliver by {{5}} to {{6}}, {{7}}, phone {{8}}. Payment is {{9}} directly to you. Please reply to confirm."}},
    "tracking_request": {"langs": ["en"], "button": None, "body": {
        "en": "Hello {{1}}, could you share the courier and tracking number for order {{2}}? Thank you."}},
    "quote_request": {"langs": ["en"], "buttons": ["Can't supply"], "body": {
        "en": "Hello {{1}}, we are collecting quotes for {{2}}, quantity {{3}}, delivery to {{4}}. Please reply with your price per unit, delivery time and minimum order. Thank you."}},
    "call_permission": {"langs": ["en"], "button": None, "body": {
        "en": "Hello {{1}}, may our AI assistant call you about a quote for {{2}}? You can say no at any time."}},
}

LANGS = ["en", "hi", "ta"]


def render(name: str, lang: str) -> str:
    bodies = TEMPLATES[name]["body"]
    return bodies.get(lang, bodies["en"])


def _graph():
    import httpx
    from dotenv import load_dotenv
    load_dotenv()
    token, waba = os.getenv("WHATSAPP_TOKEN", ""), os.getenv("WHATSAPP_WABA_ID", "")
    if not token or not waba:
        raise RuntimeError("WHATSAPP_TOKEN / WHATSAPP_WABA_ID missing in backend/.env")
    return httpx, token, waba


def _components(name: str, t: dict, lang: str) -> tuple[list, str]:
    if t.get("category") == "AUTHENTICATION":
        return ([{"type": "BODY", "add_security_recommendation": True},
                 {"type": "FOOTER", "code_expiration_minutes": 5},
                 {"type": "BUTTONS", "buttons": [
                     {"type": "OTP", "otp_type": "COPY_CODE", "text": t["button"]}]}],
                "AUTHENTICATION")
    components: list = [{"type": "BODY", "text": render(name, lang)}]
    if t.get("buttons"):  # seller quick replies
        components.append({"type": "BUTTONS", "buttons": [
            {"type": "QUICK_REPLY", "text": b} for b in t["buttons"]]})
    elif t.get("button"):  # voice_call button; confirm exact type at submit time
        components.append({"type": "BUTTONS", "buttons": [
            {"type": "VOICE_CALL", "text": t["button"]}]})
    return components, "UTILITY"


def create(name: str | None = None) -> None:
    """Submit all templates (or one, for the approval queue) in their languages."""
    httpx, token, waba = _graph()
    names = [name] if name else list(TEMPLATES)
    for n in names:
        t = TEMPLATES[n]
        for lang in t.get("langs", LANGS):
            components, category = _components(n, t, lang)
            r = httpx.post(f"https://graph.facebook.com/v21.0/{waba}/message_templates",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"name": n, "category": category, "language": lang,
                                 "components": components}, timeout=20)
            print(n, lang, r.status_code, r.text[:200])


def status() -> None:
    httpx, token, waba = _graph()
    r = httpx.get(f"https://graph.facebook.com/v21.0/{waba}/message_templates",
                  params={"fields": "name,language,status", "access_token": token}, timeout=15)
    r.raise_for_status()
    for t in r.json().get("data", []):
        print(t["name"], t.get("language"), t.get("status"))


def selfcheck() -> None:
    """Offline: every template has its languages, sequential {{n}} placeholders."""
    import re
    assert len(TEMPLATES) == 14, len(TEMPLATES)
    for name, t in TEMPLATES.items():
        langs = t.get("langs", ["en"] if t.get("category") == "AUTHENTICATION" else LANGS)
        for lang in langs:
            body = t["body"].get(lang)
            assert body, f"{name} missing {lang}"
            if name in ("stock_check", "order_request", "tracking_request",
                      "quote_request", "call_permission"):
                # new submissions only: old approved bodies stay untouched
                assert not body.startswith("{{") and not body.endswith("}}"), name
            nums = [int(n) for n in re.findall(r"\{\{(\d+)\}\}", body)]
            # set check, not order: hi/ta word order differs from en
            assert sorted(nums) == list(range(1, len(nums) + 1)), f"{name}/{lang}: {nums}"
    print("templates selfcheck: PASS")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "dry-run"
    if cmd == "dry-run":
        for name in TEMPLATES:
            print(f"== {name} ==")
            for lang in LANGS:
                print(f"[{lang}]", render(name, lang))
    elif cmd == "selfcheck":
        selfcheck()
    elif cmd == "create":
        which = sys.argv[2] if len(sys.argv) > 2 else None
        if which and which not in TEMPLATES:
            print(f"unknown template {which}; choices: {', '.join(TEMPLATES)}")
        else:
            create(which)
    elif cmd == "status":
        status()
    else:
        print("usage: python templates.py [dry-run|selfcheck|create [name]|status]")
