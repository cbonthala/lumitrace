#!/bin/sh
# First-boot setup of the Lumitrace server (Lightsail runs this once as root; see provision.sh).
# Installs Docker (official repository, for Compose's `!override`), Tailscale and jq, adds a
# 2 GB swap file for image builds, and prepares /opt/lumitrace. Contains no secrets: Lightsail
# shows user data in the console.
#
# Lightsail appends user data to its own /bin/sh launch script, so this file must stay POSIX
# sh; the setup itself runs under bash (for pipefail). Safe to run again by hand:
# ssh ... 'sudo sh -s' < deploy/lightsail/cloud-init.sh
set -eu
cat > /root/lumitrace-bootstrap.sh <<'BOOTSTRAP'
#!/bin/bash
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
command -v docker >/dev/null || curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh

install -d -m 0750 -o ubuntu -g ubuntu /opt/lumitrace /opt/lumitrace/secrets
touch /var/lib/lumitrace-bootstrap-done
BOOTSTRAP
bash /root/lumitrace-bootstrap.sh
