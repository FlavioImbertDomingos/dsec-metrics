#!/bin/sh
# Create local secrets for the development Compose stack:
#   - random passwords for Postgres and the dev admin account
#   - a short-lived development CA, name-constrained to local names, that signs the
#     Postgres server certificate and the certificate Caddy serves
# The CA private key is deleted once both certificates are signed, so the CA cannot
# sign anything else. Run again with FORCE=1 to replace everything.
#
# Works with OpenSSL 3 and with LibreSSL (macOS).
set -eu

DIR="${DSEC_SECRETS_DIR:-deploy/compose/secrets}"
HOST="${DSEC_HOSTNAME:-localhost}"
DAYS=365

umask 077
mkdir -p "$DIR"
chmod 700 "$DIR"

if [ -f "$DIR/dev_ca.crt" ] && [ "${FORCE:-0}" != "1" ]; then
  echo "Secrets already exist in $DIR. Run 'FORCE=1 make dev-secrets' to replace them."
  exit 0
fi

rand() {
  openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | cut -c "1-$1"
}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# Name constraints limit what the CA can vouch for, even if someone trusts it.
CONSTRAINTS="permitted;DNS:localhost,permitted;DNS:postgres,permitted;IP:127.0.0.1/255.255.255.255"
WEB_SAN="DNS:localhost,IP:127.0.0.1"
if [ "$HOST" != "localhost" ]; then
  CONSTRAINTS="$CONSTRAINTS,permitted;DNS:$HOST"
  WEB_SAN="$WEB_SAN,DNS:$HOST"
fi

cat > "$WORK/openssl.cnf" <<CNF
[ req ]
distinguished_name = dn
prompt = no
[ dn ]
CN = dsec-metrics development CA
[ v3_ca ]
basicConstraints = critical, CA:TRUE, pathlen:0
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
nameConstraints = critical, $CONSTRAINTS
[ web ]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = $WEB_SAN
authorityKeyIdentifier = keyid
[ db ]
basicConstraints = critical, CA:FALSE
keyUsage = critical, digitalSignature
extendedKeyUsage = serverAuth
subjectAltName = DNS:postgres,DNS:localhost,IP:127.0.0.1
authorityKeyIdentifier = keyid
CNF

serial() { echo "0x$(openssl rand -hex 16)"; }

openssl ecparam -name prime256v1 -genkey -noout -out "$WORK/ca.key"
openssl req -x509 -new -key "$WORK/ca.key" -sha256 -days "$DAYS" \
  -config "$WORK/openssl.cnf" -extensions v3_ca -set_serial "$(serial)" \
  -out "$DIR/dev_ca.crt"

issue() { # name, CN, extension section
  openssl ecparam -name prime256v1 -genkey -noout -out "$DIR/$1.key"
  openssl req -new -key "$DIR/$1.key" -subj "/CN=$2" -out "$WORK/$1.csr"
  openssl x509 -req -in "$WORK/$1.csr" -CA "$DIR/dev_ca.crt" -CAkey "$WORK/ca.key" \
    -sha256 -days "$DAYS" -set_serial "$(serial)" \
    -extfile "$WORK/openssl.cnf" -extensions "$3" -out "$DIR/$1.crt" 2>/dev/null
}

issue web_tls "$HOST" web
issue db_tls postgres db
rm -f "$WORK/ca.key"

rand 32 > "$DIR/db_password"
rand 24 > "$DIR/dev_admin_password"

# Containers run as different users (Postgres as 999, the app and Caddy as 65532), so
# the files are world-readable inside a directory only you can open.
chmod 644 "$DIR"/*
chmod 700 "$DIR"

echo "Wrote development secrets to $DIR"
echo "Dev admin: dev-admin / $(cat "$DIR/dev_admin_password")"
echo "Trust $DIR/dev_ca.crt in your OS for a clean padlock, or accept the browser warning."
