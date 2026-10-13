#!/usr/bin/env bash
# Create the Lumitrace server on AWS Lightsail (docs/runbook.md -> Deploying on AWS Lightsail).
#
# Creates, if missing: an SSH key pair, a 2 GB Ubuntu 24.04 instance with daily automatic
# snapshots, a static IP, and a firewall that only lets SSH in from this computer's current IP
# (the services are reached through Tailscale). Safe to re-run: existing resources are kept,
# and the firewall is reset to SSH from the current IP.
#
# Settings (environment variables): AWS_PROFILE, REGION (us-east-2), ZONE (<region>a),
# NAME (lumitrace), KEY_FILE (~/.ssh/lumitrace-lightsail), SNAPSHOT_TIME (09:00 UTC).
set -euo pipefail

REGION="${REGION:-us-east-2}"
ZONE="${ZONE:-${REGION}a}"
NAME="${NAME:-lumitrace}"
KEY_FILE="${KEY_FILE:-$HOME/.ssh/lumitrace-lightsail}"
SNAPSHOT_TIME="${SNAPSHOT_TIME:-09:00}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ls_() { aws lightsail --region "$REGION" "$@"; }

account="$(aws sts get-caller-identity --query Account --output text)"
echo "AWS account $account, region $REGION, instance '$NAME'"

if [ ! -f "$KEY_FILE" ]; then
  ssh-keygen -t ed25519 -N "" -C "lumitrace-lightsail" -f "$KEY_FILE"
fi
# Lightsail names must be unique across resource types, so the key pair can't be "$NAME".
KEY_PAIR="$NAME-key"
if ! ls_ get-key-pair --key-pair-name "$KEY_PAIR" >/dev/null 2>&1; then
  ls_ import-key-pair --key-pair-name "$KEY_PAIR" \
    --public-key-base64 "$(cat "$KEY_FILE.pub")" >/dev/null
  echo "Imported SSH key $KEY_FILE.pub as key pair '$KEY_PAIR'"
fi

if ! ls_ get-instance --instance-name "$NAME" >/dev/null 2>&1; then
  bundle="$(ls_ get-bundles --query "sort_by(bundles[?isActive && ramSizeInGb==\`2.0\` \
&& contains(supportedPlatforms, 'LINUX_UNIX') && !contains(bundleId, 'ipv6')], &price)[0].bundleId" \
    --output text)"
  price="$(ls_ get-bundles --query "bundles[?bundleId=='$bundle'].price | [0]" --output text)"
  echo "Creating instance with bundle $bundle (\$$price per month)"
  ls_ create-instances --instance-names "$NAME" --availability-zone "$ZONE" \
    --blueprint-id ubuntu_24_04 --bundle-id "$bundle" --key-pair-name "$KEY_PAIR" \
    --user-data "file://$HERE/cloud-init.sh" \
    --add-ons "addOnType=AutoSnapshot,autoSnapshotAddOnRequest={snapshotTimeOfDay=$SNAPSHOT_TIME}" \
    --tags key=project,value=lumitrace >/dev/null
fi

printf "Waiting for the instance to run"
until [ "$(ls_ get-instance-state --instance-name "$NAME" --query state.name --output text)" \
  = running ]; do
  printf "."
  sleep 5
done
echo

if ! ls_ get-static-ip --static-ip-name "$NAME-ip" >/dev/null 2>&1; then
  ls_ allocate-static-ip --static-ip-name "$NAME-ip" >/dev/null
fi
if [ "$(ls_ get-static-ip --static-ip-name "$NAME-ip" --query staticIp.isAttached \
  --output text)" != True ]; then
  ls_ attach-static-ip --static-ip-name "$NAME-ip" --instance-name "$NAME" >/dev/null
fi
ip="$(ls_ get-static-ip --static-ip-name "$NAME-ip" --query staticIp.ipAddress --output text)"

my_ip="$(curl -fsS https://checkip.amazonaws.com | tr -d '[:space:]')"
ls_ put-instance-public-ports --instance-name "$NAME" \
  --port-infos "fromPort=22,toPort=22,protocol=TCP,cidrs=$my_ip/32" >/dev/null

cat <<EOF

Server ready at $ip (SSH allowed only from $my_ip; first-boot setup takes a few minutes).
  ssh -i $KEY_FILE ubuntu@$ip
Next: deploy/lightsail/deploy.sh, then the Tailscale step (docs/runbook.md).
EOF
