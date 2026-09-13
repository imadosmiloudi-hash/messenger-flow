#!/bin/sh
set -eu
if [ -z "${REDIS_URL:-}" ]; then
  echo "REDIS_URL is not set" >&2
  exit 1
fi
case "$REDIS_URL" in
  redis://*|rediss://*|unix://*) ;;
  *)
    echo "Invalid REDIS_URL scheme: $REDIS_URL" >&2
    exit 1
    ;;
esac
exec rq worker messenger --url "$REDIS_URL"
