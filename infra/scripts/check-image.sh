#!/usr/bin/env bash
# check-image.sh: local checks of the container image (spec 25 §3.8; Make target image-check).
#
# Why it exists: proves the image works before anything reaches Azure: it
#   builds with no Azure access or secret, serves health and the SPA, runs
#   non-root without dev tools, and refuses the demo stage without its secrets.
# What it does: docker build (APP_VERSION=check), runs the image in the local
#   stage on HOST_PORT (default 8090 -> container 8000), checks /api/health,
#   /, a deep SPA path and an unknown API path, inspects the image, runs it with
#   DEPLOYMENT_STAGE=demo and no secrets, reports the size. Always removes the
#   containers it started.
# Must not: call Azure, push the image, or pass any secret to the container.
# Acceptance criteria: AC-25.1, AC-25.2, AC-25.3, AC-25.4, AC-25.5, AC-25.7.
set -euo pipefail

IMAGE="${IMAGE:-discovery-agent:local}"
HOST_PORT="${HOST_PORT:-8090}"
NAME="discovery-check-$$"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="http://127.0.0.1:${HOST_PORT}"
fail() { echo "FAIL: $*" >&2; exit 1; }
cleanup() { docker rm -f "$NAME" "$NAME-demo" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "1. build (AC-25.1)"
if [ "${SKIP_BUILD:-0}" != "1" ]; then
  docker build --build-arg APP_VERSION=check -t "$IMAGE" "$ROOT"
fi

echo "2. run in the local stage on :${HOST_PORT} (AC-25.2)"
docker run -d --name "$NAME" -p "127.0.0.1:${HOST_PORT}:8000" -e DEPLOYMENT_STAGE=local "$IMAGE" >/dev/null
health=""
for _ in $(seq 1 30); do
  health="$(curl -fsS "$BASE/api/health" 2>/dev/null || true)"
  [ -n "$health" ] && break
  sleep 1
done
[ -n "$health" ] || { docker logs "$NAME" >&2; fail "no health within 30 s"; }
python3 - "$health" <<'PY' || fail "health body: $health"
import json, sys
body = json.loads(sys.argv[1])
want = {"status": "ok", "stage": "local", "version": "check"}
assert {k: body.get(k) for k in want} == want, body  # spec 15 adds a `store` field
PY
echo "   health: $health"

echo "3. SPA and API 404 (AC-25.3)"
for path in / /process-discovery/abc; do
  out="$(curl -fsS -D - "$BASE$path")" || fail "GET $path"
  grep -qi '^content-type: text/html' <<<"$out" || fail "GET $path is not HTML"
  grep -q 'id="root"' <<<"$out" || fail "GET $path has no app root"
done
code="$(curl -s -o /tmp/discovery-check-404.$$ -w '%{http_code}' "$BASE/api/nope")"
[ "$code" = "404" ] || fail "GET /api/nope returned $code"
grep -q '"code"' /tmp/discovery-check-404.$$ || fail "GET /api/nope is not the JSON error"
rm -f /tmp/discovery-check-404.$$

echo "4. user, tools, excluded paths (AC-25.4, AC-25.7)"
uid="$(docker exec "$NAME" id -u)"
[ "$uid" = "10001" ] || fail "runs as uid $uid"
docker exec "$NAME" sh -c 'for t in uv node npm gcc; do command -v "$t" && exit 1; done; exit 0' \
  || fail "a build tool is present in the image"
for p in /app/backend/tests /app/.work /app/brief /app/infra /app/specs; do
  docker exec "$NAME" test ! -e "$p" || fail "$p exists in the image"
done
cmd="$(docker inspect -f '{{json .Config.Cmd}}' "$IMAGE")"
grep -q '"app.main:app","--factory"' <<<"$cmd" && grep -q '"--workers","1"' <<<"$cmd" \
  && grep -q '"--port","8000"' <<<"$cmd" || fail "unexpected command $cmd"

echo "5. demo stage without secrets fails fast (AC-25.5)"
docker run -d --name "$NAME-demo" -e DEPLOYMENT_STAGE=demo "$IMAGE" >/dev/null
for _ in $(seq 1 15); do
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME-demo")" = "false" ] && break
  sleep 1
done
[ "$(docker inspect -f '{{.State.Running}}' "$NAME-demo")" = "false" ] || fail "demo container still running after 15 s"
exit_code="$(docker inspect -f '{{.State.ExitCode}}' "$NAME-demo")"
[ "$exit_code" != "0" ] || fail "demo container exited 0"
logs="$(docker logs "$NAME-demo" 2>&1)"
for s in STORE WORKSPACE_CODE_SPECIALIST WORKSPACE_CODE_ENGINEER WORKSPACE_TOKEN_SECRET; do
  grep -q "$s" <<<"$logs" || fail "demo log does not name $s"
done
echo "   exited $exit_code and named every missing setting"

echo "6. size (target < 600 MB)"
size="$(docker image inspect -f '{{.Size}}' "$IMAGE")"
echo "   $((size / 1024 / 1024)) MB"
[ "$size" -lt $((600 * 1024 * 1024)) ] || echo "   WARNING: image is over the 600 MB target"

echo "PASS: image checks"
