#!/usr/bin/env bash
# Run once on the server: sudo /opt/lumen/app/deploy/lightsail/tailscale.sh
#
# Joins your tailnet (prints a sign-in link the first time; Tailscale SSH is enabled), then:
#   https://<name>.<tailnet>.ts.net:8443  -> Prism (tailnet only: your iPhone)
#   https://<name>.<tailnet>.ts.net       -> Lens (public through Funnel: Claude / ChatGPT)
# The first `tailscale funnel` may print a link to allow Funnel for this machine.
set -euo pipefail

if ! tailscale status >/dev/null 2>&1; then
  tailscale up --ssh --hostname "${TS_HOSTNAME:-lumen}"
fi
tailscale serve --bg --https=8443 http://127.0.0.1:8000
tailscale funnel --bg --https=443 http://127.0.0.1:8002

host="$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
cat <<EOF

Prism (Flash shortcuts, tailnet only): https://$host:8443
Lens (AI apps, public):                https://$host/mcp
In /opt/lumen/.env set LUMEN_MCP_PUBLIC_URL=https://$host and LUMEN_MCP_AUTH_MODE=oauth,
then redeploy (deploy/lightsail/deploy.sh).
EOF
tailscale serve status
