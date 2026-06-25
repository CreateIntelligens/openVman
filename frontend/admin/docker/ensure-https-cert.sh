#!/bin/sh
set -eu

cert_dir="${OPENVMAN_TLS_CERT_DIR:-/etc/nginx/certs}"
cert_file="${OPENVMAN_TLS_CERT:-$cert_dir/openvman.crt}"
key_file="${OPENVMAN_TLS_KEY:-$cert_dir/openvman.key}"
days="${OPENVMAN_TLS_DAYS:-825}"
dns_csv="${OPENVMAN_TLS_DNS:-localhost,openvman.local}"
ip_csv="${OPENVMAN_TLS_IPS:-127.0.0.1}"
cert_owner="${OPENVMAN_TLS_CERT_OWNER:-node:node}"

mkdir -p "$cert_dir"

set_cert_permissions() {
  chmod 644 "$cert_file"
  chmod 600 "$key_file"
  chown "$cert_owner" "$cert_file" "$key_file" 2>/dev/null || true
}

if [ -s "$cert_file" ] && [ -s "$key_file" ]; then
  set_cert_permissions
  exit 0
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
openssl_config="$tmp_dir/openssl.cnf"

cat > "$openssl_config" <<'EOF'
[req]
distinguished_name = dn
x509_extensions = v3_req
prompt = no

[dn]
CN = openvman.local

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
EOF

old_ifs="$IFS"
IFS=","
index=1
for dns_name in $dns_csv; do
  dns_name="$(echo "$dns_name" | xargs)"
  if [ -n "$dns_name" ]; then
    printf 'DNS.%s = %s\n' "$index" "$dns_name" >> "$openssl_config"
    index=$((index + 1))
  fi
done

index=1
for ip_addr in $ip_csv; do
  ip_addr="$(echo "$ip_addr" | xargs)"
  if [ -n "$ip_addr" ]; then
    printf 'IP.%s = %s\n' "$index" "$ip_addr" >> "$openssl_config"
    index=$((index + 1))
  fi
done
IFS="$old_ifs"

openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -days "$days" \
  -keyout "$key_file" \
  -out "$cert_file" \
  -config "$openssl_config" \
  >/dev/null 2>&1

set_cert_permissions
