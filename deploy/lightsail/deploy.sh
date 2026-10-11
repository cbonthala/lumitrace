#!/usr/bin/env bash
# Deploy the committed code (git HEAD) to the Lightsail server and (re)start Lumen.
#
# Copies HEAD to /opt/lumen/app (never uncommitted changes), optionally uploads the production
# env file and the Google Drive secrets folder, then builds and starts the three services with
# their ports bound to 127.0.0.1 (Tailscale publishes them; see tailscale.sh).
#
# Settings (environment variables): AWS_PROFILE, REGION (us-east-2), NAME (lumen),
# KEY_FILE (~/.ssh/lumen-lightsail), ENV_FILE (a local .env to upload, e.g. .env.production),
# SECRETS_DIR (a local folder to upload as /opt/lumen/secrets, e.g. secrets).
set -euo pipefail

REGION="${REGION:-us-east-2}"
NAME="${NAME:-lumen}"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/lumen-lightsail}"
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

if ! remote test -f /var/lib/lumen-bootstrap-done; then
  echo "The server is still running its first-boot setup; try again in a few minutes." >&2
  exit 1
fi
if [ -n "${ENV_FILE:-}" ]; then
  scp "${ssh_opts[@]}" "$ENV_FILE" "$target:/opt/lumen/.env"
  remote chmod 600 /opt/lumen/.env
fi
if [ -n "${SECRETS_DIR:-}" ]; then
  scp "${ssh_opts[@]}" -r "$SECRETS_DIR/." "$target:/opt/lumen/secrets/"
  remote chmod -R go-rwx /opt/lumen/secrets
fi
if ! remote test -f /opt/lumen/.env; then
  echo "No /opt/lumen/.env on the server: run again with ENV_FILE=<your production .env>." >&2
  exit 1
fi

echo "Deploying $(git rev-parse --short HEAD) to $ip"
git archive --format=tar HEAD | remote '
  set -e
  rm -rf /opt/lumen/app.new && mkdir /opt/lumen/app.new
  tar -x -C /opt/lumen/app.new
  ln -s /opt/lumen/.env /opt/lumen/app.new/.env
  ln -s /opt/lumen/secrets /opt/lumen/app.new/secrets
  rm -rf /opt/lumen/app && mv /opt/lumen/app.new /opt/lumen/app
  cd /opt/lumen/app
  docker compose -p lumen -f docker-compose.yml -f deploy/lightsail/compose.lightsail.yml \
    up -d --build --remove-orphans
  for _ in $(seq 30); do curl -fsS http://127.0.0.1:8000/health && break; sleep 2; done
  echo
  curl -fsS http://127.0.0.1:8002/health
  echo
'
