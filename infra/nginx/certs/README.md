# Nginx TLS Certificates

The admin/nginx container uses these filenames for HTTPS:

- `openvman.crt`
- `openvman.key`

If either file is missing, the development container generates a local self-signed certificate at startup. For browser webcam access from another machine, replace these files with a certificate trusted by that browser and include the host name or IP address in the certificate SAN.
