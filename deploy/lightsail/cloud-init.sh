#!/bin/bash
# First-boot setup of the Lumen server (Lightsail runs this once as root; see provision.sh).
# Installs Docker (official repository, for Compose's `!override`), Tailscale and jq, adds a
# 2 GB swap file for image builds, and prepares /opt/lumen. Contains no secrets: Lightsail
# shows user data in the console.
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

if [ ! -f /swapfile ]; then
  fallocate -l 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

apt-get update
apt-get install -y ca-certificates curl git jq
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
curl -fsSL https://tailscale.com/install.sh | sh

install -d -m 0750 -o ubuntu -g ubuntu /opt/lumen /opt/lumen/secrets
touch /var/lib/lumen-bootstrap-done
