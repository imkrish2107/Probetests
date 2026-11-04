"""Tiny fake backend for dashboard/smoke_test.sh. stdlib only, no network."""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

UPLOAD_LOG = "/tmp/smoke_upload.log"

HUNT = {
    "hunt": {"id": 1, "flow": "shopping", "status": "done", "searches_used": 2,
             "cost_usd": 0.01, "spot": '{"colour":"red","garment":"shirt"}',
             "top_reason": "Best verified price of the 1 listings checked"},
    "steps": [{"agent": a, "state": "done", "detail": "smoke", "at": "now"}
              for a in ("Spotter", "Finder", "Checker", "Matcher", "Ranker",
                        "Messenger", "Picker", "Buyer", "Tracker", "Plan Reader",
                        "Quantity Surveyor", "House Artist", "Quote Caller")],
    "listings": [{"id": 1, "url": "https://example.com/x", "title": "Red shirt",
                  "seller": "Demo Seller", "seller_id": 1, "price": 100.0,
                  "unit": "pc", "city": "Mumbai", "in_stock": "yes",
                  "similarity": 90, "verified": 1, "delivery": "2 days",
                  "whatsapp": "919999999999"}],
    "rooms": [],
}

PURCHASE = {"id": 1, "item": "Red shirt", "seller_name": "Demo", "price": 100.0,
            "unit": "pc", "status": "seller_confirmed", "delivery_option": "2 days",
            "delivery_reason": "cheapest", "courier": "", "tracking_number": "",
            "tracking_link": "",
            "events": [{"id": 1, "status": "order_sent", "at": "now", "note": "hi"}]}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/api/auth/me":
            return self._send({"user": {"id": 1, "name": "T", "email": "t@x",
                                        "role": "owner"},
                               "business": {"id": 1, "name": "B", "slug": "b"}})
        if p == "/api/hunts":
            return self._send({"items": [{"id": 1, "flow": "shopping",
                                           "status": "done", "searches_used": 2,
                                           "cost_usd": 0.01,
                                           "top_reason": "Best verified price"}]})
        if p == "/api/hunts/1":
            return self._send(HUNT)
        if p == "/api/hunts/1/photo":
            return self._send(b"\xff\xd8fakejpeg", ctype="image/jpeg")
        if p == "/api/hunts/1/image":
            return self._send(b"\xff\xd8fakejpeg", ctype="image/jpeg")
        if p == "/api/hunts/1/boq.csv":
            return self._send(b"item,qty\nCement,10\n", ctype="text/csv")
        if p == "/api/hunts/1/vendors":
            return self._send({"items": []})
        if p == "/api/hunts/1/approval":
            return self._send({"approved": False, "reason": "Build the BOQ first."})
        if p == "/api/listings/1/delivery-pick":
            return self._send({"options": [{"label": "2 days", "price": 100.0,
                                            "days": 2}],
                               "pick": {"label": "2 days"}, "reason": "cheapest",
                               "pref": "cheapest"})
        if p == "/api/listings/1/invite":
            return self._send({"invite_from_whatsapp": "https://wa.me/919999999999"})
        if p == "/api/purchases":
            return self._send({"items": [PURCHASE]})
        if p == "/api/purchases/1":
            return self._send(PURCHASE)
        if p == "/api/sellers":
            return self._send({"items": [{"id": 1, "name": "Demo",
                                          "phone": "91111", "kind": "shop",
                                          "opted_in": 1}]})
        if p == "/api/business":
            return self._send({"name": "B", "timezone": "Asia/Kolkata",
                               "delivery_pref": "cheapest"})
        if p == "/api/templates":
            return self._send({"items": []})
        if p == "/api/bookings":
            return self._send({"items": []})
        if p == "/api/tasks":
            return self._send({"items": []})
        if p == "/api/contacts":
            return self._send({"items": []})
        if p == "/api/contacts/1":
            return self._send({"id": 1, "name": "C", "language": "en",
                               "stage": "new", "phone": "", "calls_count": 0,
                               "call_permission": 0, "tags": [], "notes": ""})
        if p == "/api/stats":
            return self._send({"calls": 0, "bookings": 0, "open_tasks": 0,
                               "urgent_tasks": 0, "cost_usd": 0})
        if p == "/api/calls":
            return self._send({"items": [], "next_before": None})
        if p == "/api/calls/1":
            return self._send({"id": 1, "language": "en", "outcome": "done",
                               "started_at": "now", "duration_s": 1,
                               "direction": "in", "tokens_in": 0, "tokens_out": 0,
                               "audio_seconds": 0, "cost_usd": 0,
                               "transcript": [], "bookings": [], "tasks": [],
                               "messages": []})
        if p == "/api/public/businesses/demo":
            return self._send({"name": "B"})
        return self._send({"error": {"message": "no route " + p}}, 404)

    def do_POST(self):
        p = urlparse(self.path).path
        if p == "/api/hunts":
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            ok = b"filename=" in body and b"flow" in body
            with open(UPLOAD_LOG, "a") as f:
                f.write(f"upload bytes={len(body)} file={ok}\n")
            if not ok:
                return self._send({"error": {"message": "bad upload"}}, 400)
            return self._send({"id": 1})
        return self._send({"error": {"message": "no route " + p}}, 404)


HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
