#!/bin/bash
# Smoke test: build the app, start it against a fake backend, request every
# page with a session cookie. Any 500 fails. Also runs a real file upload
# through the createHunt server action via a temporary route.
set -euo pipefail
cd "$(dirname "$0")"

FAKE_PORT=8123
APP_PORT=3111
UPLOAD_ROUTE="src/app/api-smoke-upload/route.ts"
rm -f /tmp/smoke_upload.log

FAKE_PID=""
APP_PID=""
cleanup() {
  [ -n "$FAKE_PID" ] && kill "$FAKE_PID" 2>/dev/null || true
  [ -n "$APP_PID" ] && kill "$APP_PID" 2>/dev/null || true
  rm -f "$UPLOAD_ROUTE"
  rmdir "$(dirname "$UPLOAD_ROUTE")" 2>/dev/null || true
}
trap cleanup EXIT

# Temporary route: real upload path (multipart -> createHunt -> postForm).
mkdir -p "$(dirname "$UPLOAD_ROUTE")"
cat > "$UPLOAD_ROUTE" <<'EOF'
import { createHunt } from "@/lib/actions";
export async function POST(req: Request) {
  const fd = await req.formData();
  try {
    await createHunt(fd);
    return Response.json({ ok: true, redirected: null });
  } catch (e: any) {
    const d = typeof e?.digest === "string" ? e.digest : "";
    if (d.startsWith("NEXT_REDIRECT")) return Response.json({ ok: true, redirected: d });
    return Response.json({ ok: false, error: e?.message ?? String(e) }, { status: 500 });
  }
}
EOF

./node_modules/.bin/next build
python3 smoke_fake_backend.py "$FAKE_PORT" & FAKE_PID=$!
BACKEND_URL="http://127.0.0.1:$FAKE_PORT" BACKEND_API_KEY=test \
  ./node_modules/.bin/next start -p "$APP_PORT" & APP_PID=$!

BASE="http://127.0.0.1:$APP_PORT"
for i in $(seq 1 60); do
  curl -sf -o /dev/null "$BASE/login" && break || sleep 2
  [ "$i" = 60 ] && { echo "app never came up"; exit 1; }
done

fail=0
check() { # path expected_code [cookie]
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" ${3:+-b "$3"} "$BASE$1")
  if [ "$code" != "$2" ]; then echo "FAIL $1: got $code, want $2"; fail=1;
  else echo "ok $1 -> $code"; fi
}

COOKIE="session=smoke"
check /login 200
check /hunts 307
check / 200 "$COOKIE"
check /hunts 200 "$COOKIE"
check "/hunts?flow=construction" 200 "$COOKIE"
check /hunts/1 200 "$COOKIE"
check /hunts/1/order/1 200 "$COOKIE"
check /hunts/2 200 "$COOKIE"
check /hunts/2/photo 200 "$COOKIE"
check "/hunts/2/image?n=1" 200 "$COOKIE"
check /hunts/2/boq.csv 200 "$COOKIE"
check /hunts/3 200 "$COOKIE"
check /orders 200 "$COOKIE"
check /orders/1 200 "$COOKIE"
check /sellers 200 "$COOKIE"
check /setup 200 "$COOKIE"
check /bookings 200 "$COOKIE"
check /tasks 200 "$COOKIE"
check /contacts 200 "$COOKIE"
check /contacts/1 200 "$COOKIE"
check /calls/1 200 "$COOKIE"
check /c/demo 200
check /hunts/1/photo 200 "$COOKIE"
check "/hunts/1/image?n=1" 200 "$COOKIE"
check /hunts/1/boq.csv 200 "$COOKIE"
check /hunts/1/invite/1 307 "$COOKIE"

# Real upload through createHunt: multipart file + flow, like the dashboard form.
printf 'fakeplan' > /tmp/smoke_plan.jpg
resp=$(curl -s -b "$COOKIE" -F "flow=shopping" -F "file=@/tmp/smoke_plan.jpg;type=image/jpeg" \
  "$BASE/api-smoke-upload")
echo "upload: $resp"
echo "$resp" | grep -q "/hunts/1" || { echo "FAIL upload did not redirect to /hunts/1"; fail=1; }
grep -q "file=True" /tmp/smoke_upload.log || { echo "FAIL backend saw no file"; fail=1; }

[ "$fail" = 0 ] && echo "SMOKE PASS" || { echo "SMOKE FAIL"; exit 1; }
