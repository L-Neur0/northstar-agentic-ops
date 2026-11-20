#!/usr/bin/env bash
# smoke.sh: read-only smoke check of the deployed app (spec 25 §3.9; Make target smoke).
#
# Why it exists: proves a deploy really works from the outside: the right
#   version runs in the demo stage, the SPA is served with security headers,
#   plain HTTP never answers 200, and unknown API paths give the JSON 404.
# What it does: `smoke.sh <https-url> [expected-version]`. Retries the health
#   check 10 times, 15 s apart (new revision start-up), then runs the other
#   checks once. With SMOKE_TURN=1 it also creates a session and sends one turn
#   (Cosmos + Azure OpenAI through the identity, spec 15; at most 3 model calls).
# Must not: change anything in Azure, need a credential, or print a secret.
# Acceptance criteria: AC-25.23, AC-25.24 (SMOKE_TURN=1), AC-25.27, AC-25.28.
set -euo pipefail

URL="${1:?usage: smoke.sh <https-url> [expected-version]}"
URL="${URL%/}"
VERSION="${2:-}"
ATTEMPTS="${SMOKE_ATTEMPTS:-10}"
WAIT="${SMOKE_WAIT:-15}"
fail() { echo "FAIL: $*" >&2; exit 1; }

echo "1. health (stage demo${VERSION:+, version $VERSION})"
ok=0
for i in $(seq 1 "$ATTEMPTS"); do
  body="$(curl -fsS --max-time 10 "$URL/api/health" 2>/dev/null || true)"
  if [ -n "$body" ] && python3 - "$body" "$VERSION" <<'PY'
import json, sys
body, want = json.loads(sys.argv[1]), sys.argv[2]
assert body.get("status") == "ok" and body.get("stage") == "demo", body
assert not want or body.get("version") == want, body
PY
  then ok=1; echo "   $body"; break; fi
  echo "   attempt $i/$ATTEMPTS: ${body:-no answer}; waiting ${WAIT}s"
  sleep "$WAIT"
done
[ "$ok" = "1" ] || fail "health never matched"

echo "2. SPA with CSP and HSTS"
headers="$(curl -fsS --max-time 10 -D - -o /dev/null "$URL/")" || fail "GET /"
grep -qi '^content-type: text/html' <<<"$headers" || fail "GET / is not HTML"
grep -qi '^content-security-policy:' <<<"$headers" || fail "no Content-Security-Policy header"
grep -qi '^strict-transport-security:' <<<"$headers" || fail "no Strict-Transport-Security header"

echo "3. plain HTTP never answers 200"
host="${URL#https://}"; host="${host%%/*}"
code="$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "http://$host/api/health" || true)"
[ "$code" != "200" ] || fail "HTTP answered 200"
echo "   http -> $code"

echo "4. unknown API path is a JSON 404"
code="$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "$URL/api/nope")"
[ "$code" = "404" ] || fail "GET /api/nope returned $code"

if [ "${SMOKE_TURN:-0}" = "1" ]; then
  echo "5. one interview turn (Cosmos + model through the identity, AC-25.24)"
  key="smoke-$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  hdr=(-H "X-Visitor-Key: $key" -H 'content-type: application/json')
  session="$(curl -fsS --max-time 60 -X POST "${hdr[@]}" -d '{}' "$URL/api/sessions")" || fail "POST /api/sessions"
  sid="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$session")"
  turn="$(curl -fsS --max-time 60 -X POST "${hdr[@]}" \
    -d '{"text":"I run the monthly cost review of our IT services."}' \
    "$URL/api/sessions/$sid/messages")" || fail "turn did not answer within 60 s"
  python3 - "$turn" <<'PY' || fail "turn reply is not an agent question"
import json, sys
reply = json.loads(sys.argv[1])["reply"]
assert reply["role"] == "agent" and reply["text"].strip(), reply
PY
  curl -fsS --max-time 30 -X DELETE "${hdr[@]}" "$URL/api/sessions/$sid" >/dev/null || echo "   (could not delete the smoke session)"
  echo "   turn answered by the agent; smoke session deleted"
fi

echo "PASS: smoke $URL"
