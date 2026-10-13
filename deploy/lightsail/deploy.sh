#!/usr/bin/env bash
# Deploy the committed code (git HEAD) to the Lightsail server and (re)start Lumitrace.
#
# Copies HEAD to /opt/lumitrace/app (never uncommitted changes), optionally uploads the production
# env file and the Google Drive secrets folder, then builds and starts the three services with
# their ports bound to 127.0.0.1 (Tailscale publishes them; see tailscale.sh).
#
# Settings (environment variables): AWS_PROFILE, REGION (us-east-2), NAME (lumitrace),
# KEY_FILE (~/.ssh/lumitrace-lightsail), ENV_FILE (a local .env to upload, e.g. .env.production),
# SECRETS_DIR (a local folder to upload as /opt/lumitrace/secrets, e.g. secrets).
set -euo pipefail

REGION="${REGION:-us-east-2}"
NAME="${NAME:-lumitrace}"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/lumitrace-lightsail}"
cd "$(git rev-parse --show-toplevel)"

if [ -n "$(git status --porcelain)" ]; then
  echo "Uncommitted changes: commit first (only HEAD is deployed)." >&2
  exit 1
fi
ip="$(aws lightsail --region "$REGION" get-static-ip --static-ip-name "$NAME-ip" \
  --query staticIp.ipAddress --output text)"
target="ubuntu@$ip"
ssh_opts=(-i "$KEY_FILE" -o StrictHostKeyChecking=accept-new)
remote() { ssh "${ssh_opts[@]}" "$target" "$@"; }

if ! remote test -f /var/lib/lumitrace-bootstrap-done; then
  echo "The server is still running its first-boot setup; try again in a few minutes." >&2
  exit 1
fi
if [ -n "${ENV_FILE:-}" ]; then
  scp "${ssh_opts[@]}" "$ENV_FILE" "$target:/opt/lumitrace/.env"
  remote chmod 600 /opt/lumitrace/.env
fi
if [ -n "${SECRETS_DIR:-}" ]; then
  remote 'rm -rf /tmp/lumitrace-secrets && mkdir -m 700 /tmp/lumitrace-secrets'
  scp "${ssh_opts[@]}" -r "$SECRETS_DIR/." "$target:/tmp/lumitrace-secrets/"
  # The containers run as uid 10001 (Dockerfile) and must read and refresh the Drive token.
  remote 'sudo cp -r /tmp/lumitrace-secrets/. /opt/lumitrace/secrets/ && rm -rf /tmp/lumitrace-secrets &&
    sudo chown -R 10001:10001 /opt/lumitrace/secrets && sudo chmod -R u=rwX,go= /opt/lumitrace/secrets'
fi
if ! remote test -f /opt/lumitrace/.env; then
  echo "No /opt/lumitrace/.env on the server: run again with ENV_FILE=<your production .env>." >&2
  exit 1
fi

echo "Deploying $(git rev-parse --short HEAD) to $ip"
git archive --format=tar HEAD | remote '
  set -e
  rm -rf /opt/lumitrace/app.new && mkdir /opt/lumitrace/app.new
  tar -x -C /opt/lumitrace/app.new
  ln -s /opt/lumitrace/.env /opt/lumitrace/app.new/.env
  ln -s /opt/lumitrace/secrets /opt/lumitrace/app.new/secrets
  rm -rf /opt/lumitrace/app && mv /opt/lumitrace/app.new /opt/lumitrace/app
  cd /opt/lumitrace/app
  docker compose -p lumitrace -f docker-compose.yml -f deploy/lightsail/compose.lightsail.yml \
    up -d --build --remove-orphans
  for _ in $(seq 30); do curl -fsS http://127.0.0.1:8000/health && break; sleep 2; done
  echo
  curl -fsS http://127.0.0.1:8002/health
  echo
'
