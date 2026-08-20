# Nginx TLS Certificates

The admin/nginx container uses these filenames for HTTPS:

- `openvman.crt`
- `openvman.key`

If either file is missing, the development container generates a local self-signed certificate at startup. For browser webcam access from another machine, replace these files with a certificate trusted by that browser and include the host name or IP address in the certificate SAN.

## Public HTTPS (native nginx)

The host's own nginx terminates TLS for the public domain and proxies into the
Docker nginx on `127.0.0.1:8787`. Its vhost lives in
`infra/nginx/native/146-openvman.conf` and is deployed by copying it to
`/etc/nginx/conf.d/`.

That certificate is issued by Let's Encrypt and kept in `letsencrypt/` here
(git-ignored) rather than `/etc/letsencrypt`, because certbot runs as a
container rather than a host package. The directory is bind-mounted at the
standard `/etc/letsencrypt` path inside that container, so the renewal config
stays portable while the host nginx reads the same files through their real
path.

`scripts/setup-public-https.sh` installs the renewal cron automatically during
the initial public HTTPS setup. The marked cron block is replaced on rerun, so
it does not create duplicate jobs. Its default log is
`backend/logs/letsencrypt-renew.log`.

To renew manually, run `scripts/renew-letsencrypt.sh` (add `--dry-run` to
rehearse without touching the live certificate). The default cron schedule is:

```
17 4 * * * <repo>/scripts/renew-letsencrypt.sh
```
