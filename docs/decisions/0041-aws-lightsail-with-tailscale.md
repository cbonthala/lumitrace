# 0041. Hosting: one AWS Lightsail instance behind Tailscale

- Status: accepted
- Date: 2026-10-11

## Context

Lumen is three small services for one owner, sharing one data volume and a SQLite index, with
Spectrum's unauthenticated `/nudge` port kept private. The owner wants AWS hosting but external
AI and speech providers (no Amazon Transcribe or Bedrock). The iPhone Shortcuts need HTTPS to
the Prism; the Claude and ChatGPT web connectors need a public HTTPS root URL for the Lens.

## Decision

- One Lightsail instance (2 GB, Ubuntu 24.04, `us-east-2`) running the existing Docker Compose
  file with an override that binds the Prism and the Lens to `127.0.0.1`. Daily automatic
  snapshots; static IP; the Lightsail firewall only allows SSH from the owner's IP.
- Tailscale publishes the services: the Prism on the tailnet only (`:8443`), the Lens publicly
  through Funnel on `:443` (root URL, as the OAuth issuer requires). No domain or certificates
  to manage.
- Provisioning and deploys are scripts using the AWS CLI (`deploy/lightsail/`); deploys copy the
  committed `HEAD` over SSH and build on the server. Secrets live only in `/opt/lumen/.env` and
  `/opt/lumen/secrets/`, never in user data or the repository.

## Consequences

- Flat, low cost (about $12 a month), and no AWS permissions or keys on the server.
- EC2 was not needed: its main advantage (IAM roles for AWS AI services) does not apply. ECS,
  Fargate and App Runner would split the services from the SQLite volume (EFS and SQLite don't
  mix well) at two to three times the cost; Lambda cannot run the long-lived worker and watcher.
- The Prism is unreachable unless the phone is on the tailnet (VPN On Demand). The Lens is on the
  internet, protected by OAuth and its token.
- All three services run all the time. Starting the Prism only when a recording arrives saves
  nothing on Lightsail (the instance is billed whether it is busy, idle or stopped) and an idle
  Prism uses no AI calls and little memory; paying per recording would mean moving the Prism to
  Lambda and S3 (about $5 a month less, but a rewrite of the worker and a public Prism).
- Images are built on the server (a swap file covers the build). If builds get slow, push images
  from a registry instead.
