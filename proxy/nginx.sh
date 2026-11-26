#!/bin/sh
set -eu

if [ -z "${OMEGA_AUTH_SECRET:-}" ] && [ -n "${OMEGACLAW_AUTH_SECRET:-}" ]; then
    echo "OMEGACLAW_AUTH_SECRET is deprecated, rename it to OMEGA_AUTH_SECRET" >&2
    OMEGA_AUTH_SECRET=${OMEGACLAW_AUTH_SECRET}
    export OMEGA_AUTH_SECRET
fi

NGINX_TEMPLATE=${NGINX_TEMPLATE:-/opt/nginx/nginx.conf.template}
NGINX_CONFIG=${NGINX_CONFIG:-/opt/nginx/nginx.conf}
SUBST_VARS=$(grep -o '\${[A-Z_0-9]*}' "${NGINX_TEMPLATE}" | sort -u | tr '\n' ' ')
touch "${NGINX_CONFIG}"
chmod 0600 "${NGINX_CONFIG}"
envsubst "$SUBST_VARS" \
    < "${NGINX_TEMPLATE}" \
    > "${NGINX_CONFIG}"

if [ "${1:-}" = "--auth-state" ]; then
    rm -f /opt/nginx/auth-state.sock
    python3 -I /opt/nginx/auth_state.py &
    auth_pid=$!
    while [ ! -S /opt/nginx/auth-state.sock ]; do
        kill -0 "$auth_pid" || exit 1
        sleep 0.05
    done
fi

nginx -c "${NGINX_CONFIG}"

