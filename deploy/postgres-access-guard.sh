#!/usr/bin/env bash
# Restrict only externally forwarded connections to the published PostgreSQL port.
set -euo pipefail
CONFIG=${1:-/etc/lifereel/postgres-access.conf}
test -r "$CONFIG"
source "$CONFIG"
: "${POSTGRES_ADMIN_CIDR:?Set the administrator IPv4 CIDR}"
: "${POSTGRES_EXTERNAL_INTERFACE:?Set the external network interface}"
POSTGRES_PORT=${POSTGRES_PORT:-5432}
[[ "$POSTGRES_PORT" =~ ^[0-9]+$ ]]
(( POSTGRES_PORT > 0 && POSTGRES_PORT < 65536 ))
[[ "$POSTGRES_ADMIN_CIDR" =~ ^[0-9.]+/[0-9]+$ ]]
[[ "$POSTGRES_EXTERNAL_INTERFACE" =~ ^[a-zA-Z0-9_.:-]+$ ]]

iptables -w -S DOCKER-USER >/dev/null
iptables -w -N LIFEREEL-PG-ACCESS 2>/dev/null || true
iptables -w -F LIFEREEL-PG-ACCESS
iptables -w -A LIFEREEL-PG-ACCESS -s "$POSTGRES_ADMIN_CIDR" -j RETURN
iptables -w -A LIFEREEL-PG-ACCESS -j DROP
if ! iptables -w -C DOCKER-USER -i "$POSTGRES_EXTERNAL_INTERFACE" -p tcp \
    -m conntrack --ctdir ORIGINAL --ctorigdstport "$POSTGRES_PORT" \
    -j LIFEREEL-PG-ACCESS 2>/dev/null; then
    iptables -w -I DOCKER-USER 1 -i "$POSTGRES_EXTERNAL_INTERFACE" -p tcp \
        -m conntrack --ctdir ORIGINAL --ctorigdstport "$POSTGRES_PORT" \
        -j LIFEREEL-PG-ACCESS
fi
printf 'PostgreSQL access rule applied for %s on port %s\n' \
    "$POSTGRES_ADMIN_CIDR" "$POSTGRES_PORT"
