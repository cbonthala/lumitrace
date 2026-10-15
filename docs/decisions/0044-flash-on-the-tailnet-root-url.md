# 0044. The Flash app gets the plain tailnet address; the Lens moves to port 8443

- Status: accepted
- Date: 2026-10-14

## Context

Decision 0041 put the Lens on Funnel's port 443 and the Prism on the tailnet at `:8443`, so
the Flash app lived at `https://lumitrace.<tailnet>.ts.net:8443/flash/`. The owner types that
address on new devices and wants something easy to remember. The Lens address, by contrast,
is typed once per AI app into its connector settings.

Tailscale Funnel works per port: every handler on a funnelled port is public, so the Prism
cannot share 443 with the Lens without becoming public. Funnel only allows ports 443, 8443
and 10000. Tailscale does not issue certificates for custom domains.

## Decision

- `tailscale serve --https=443` → Prism (tailnet only), so the Flash app is at
  `https://lumitrace.<tailnet>.ts.net` (`/` already redirects to `/flash/`).
- `tailscale funnel --https=8443` → Lens; `LUMITRACE_MCP_PUBLIC_URL` is
  `https://lumitrace.<tailnet>.ts.net:8443`. The OAuth issuer is still the server's root (a
  port is allowed; no path).
- `tailscale.sh` runs `tailscale serve reset` first, so re-running it moves an existing server
  to this layout.
- The owner also renames the tailnet in the Tailscale admin console to one of its two-word
  names (for example `blue-heron.ts.net`) instead of the random `tailXXXXXX`.

Rejected: a custom domain with Caddy and a DNS-challenge certificate (memorable, but a domain,
a proxy container and Route 53 credentials to run for one address).

## Consequences

- Moving changes both addresses: the Flash Home Screen icon and Flash Config are set up again,
  captures waiting in the old site's browser storage must be sent first, and every AI app
  re-adds its connector (the OAuth resource URL changed). Steps: `docs/runbook.md` →
  *Renaming the tailnet*.
- The Lens URL has a port; if an AI app ever refuses one, swap back (Funnel on 443).
