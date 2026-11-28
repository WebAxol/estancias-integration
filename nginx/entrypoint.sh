#!/bin/sh
set -e

CERT_DIR="/etc/nginx/certs"
KEY_FILE="${CERT_DIR}/ec_key.pem"
CERT_FILE="${CERT_DIR}/ec_cert.pem"
TLS_CN="${TLS_CN:-localhost}"
TLS_SAN="${TLS_SAN:-DNS:localhost,IP:127.0.0.1}"

mkdir -p "$CERT_DIR"

if [ ! -f "$KEY_FILE" ] || [ ! -f "$CERT_FILE" ]; then
    echo "Generando certificado TLS autofirmado (EC prime256v1) para CN=${TLS_CN}..."
    openssl ecparam -genkey -name prime256v1 -out "$KEY_FILE"
    openssl req -x509 -new -key "$KEY_FILE" -out "$CERT_FILE" \
        -sha256 -days 365 -nodes \
        -subj "/CN=${TLS_CN}" \
        -addext "subjectAltName=${TLS_SAN}"
    chmod 600 "$KEY_FILE"
    chmod 644 "$CERT_FILE"
fi