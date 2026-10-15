#!/usr/bin/env bash
# Run on the server: sudo /opt/lumitrace/app/deploy/lightsail/tailscale.sh
#
# Joins your tailnet (prints a sign-in link the first time; Tailscale SSH is enabled), then
# replaces any earlier serve/funnel setup with (decision 0044):
#   https://<name>.<tailnet>.ts.net        -> Prism (tailnet only: the Flash app, your iPhone)
#   https://<name>.<tailnet>.ts.net:8443   -> Lens (public through Funnel: Claude / ChatGPT)
# The first `tailscale funnel` may print a link to allow Funnel for this machine.
# Never serve or funnel 8001 (Spectrum) or 8003 (Lens admin API).
set -euo pipefail

if ! tailscale status >/dev/null 2>&1; then
  tailscale up --ssh --hostname "${TS_HOSTNAME:-lumitrace}"
fi
tailscale serve reset
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale funnel --bg --https=8443 http://127.0.0.1:8002

host="$(tailscale status --json | jq -r '.Self.DNSName' | sed 's/\.$//')"
cat <<EOF

Prism (Flash app and shortcuts, tailnet only): https://$host
Lens (AI apps, public):                        https://$host:8443/mcp
In /opt/lumitrace/.env set LUMITRACE_MCP_PUBLIC_URL=https://$host:8443 and
LUMITRACE_MCP_AUTH_MODE=oauth, then redeploy (deploy/lightsail/deploy.sh).
EOF
tailscale serve status
