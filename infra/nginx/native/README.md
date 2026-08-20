# Native nginx vhost

`docker compose up` only brings up the Docker edge nginx, which listens on
`8786`/`8787` with a self-signed certificate. Public HTTPS is terminated one
layer above by the **host's own nginx**, which proxies into that edge:

```
browser ──HTTPS 443──> host nginx (Let's Encrypt)
                         └──HTTPS 8787──> Docker nginx (self-signed)
                              └──> avatar / admin / backend
```

That layer is not managed by compose, so it has to be set up once per machine.

## Files

| File | Role |
| --- | --- |
| `openvman.conf.template` | Source of truth. Edit this. |
| `146-openvman.conf` | What currently runs on the production host, kept for reference and asserted against the template by `backend/tests/config/test_https_edge_proxy.py`. |
| `openvman.conf` | Render output. Git-ignored — never edit by hand. |

## Deploying to a new host

Start the Compose stack from the profiles and service URLs configured in
`.env`, then run the one-time setup as the deployment user. The setup uses
`sudo` only for the host nginx files and reload; certbot itself runs in Docker.

```sh
docker compose up -d

./scripts/setup-public-https.sh
```

Set `PUBLIC_DOMAIN` and `LETSENCRYPT_EMAIL` in the repository root `.env`
before running setup. Explicit shell environment values override `.env` when a
one-off value is needed.

The script performs the whole initial flow:

1. Render the repository's nginx template.
2. Install a temporary HTTP-only ACME vhost when the certificate is absent.
3. Issue the initial certificate with the pinned certbot container.
4. Install the full HTTPS vhost and reload host nginx.
5. Install or replace one marked renewal block in the current user's crontab.

It is safe to rerun: an existing certificate is not reissued, the vhost is
validated before reload, and the cron block is replaced rather than appended.
Use `--dry-run` to print the planned operations without changing nginx,
certificates, or crontab.

| Variable | Default |
| --- | --- |
| `PUBLIC_DOMAIN` | `.env` *(required)* |
| `LETSENCRYPT_EMAIL` | `.env` *(required)* |
| `LETSENCRYPT_DIR` | `<repo>/infra/nginx/certs/letsencrypt` |
| `EDGE_UPSTREAM` | `127.0.0.1:8787` |
| `ACME_WEBROOT` | `/usr/share/nginx/html` |
| `NGINX_CONFIG_PATH` | `/etc/nginx/conf.d/openvman.conf` |
| `LETSENCRYPT_CRON_SCHEDULE` | `17 4 * * *` |
| `LETSENCRYPT_RENEW_LOG` | `<repo>/backend/logs/letsencrypt-renew.log` |

DNS must already point at this host, inbound port 80 must reach host nginx, and
the deployment user must have Docker and crontab access.

## Why `/openvman/` is not configurable

The admin bundle hard-codes the same prefix
(`frontend/admin/src/components/app/navigation.ts`). Making it a template
variable would let the two drift apart, so both sides keep it literal.
