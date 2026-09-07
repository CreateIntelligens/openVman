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
| `deploy.sh` | Renders, backs up, validates and reloads the host vhost. |
| `146-openvman.conf` | What currently runs on the production host, kept for reference and asserted against the template by `backend/tests/config/test_https_edge_proxy.py`. |
| `openvman.conf` | Render output. Git-ignored — never edit by hand. |

## Updating an already-deployed host

The host's nginx is a deployment target, not a source. Edit the template, then
push it out — an edit that is never deployed leaves the two silently diverged,
which is how `/static/` once went missing in production while the repository
looked correct:

```sh
./infra/nginx/native/deploy.sh --check   # diff only, changes nothing
./infra/nginx/native/deploy.sh           # back up, install, nginx -t, reload
```

`deploy.sh` rolls back to the backup if `nginx -t` rejects the result, so a bad
template cannot take the vhost down. It writes to `146-openvman.conf`, the
filename the production host actually loads; override `NGINX_CONFIG_PATH` for a
host that uses a different one.

### Getting reminded to deploy

Committing a template change does not deploy it, and CI cannot notice the gap
either — a GitHub runner has no `/etc/nginx` to compare against. The check has
to run on the deployment host, so it ships as a git hook installed per clone:

```sh
./infra/nginx/native/hooks/install.sh
```

It runs `deploy.sh --check` whenever a commit touches the template and prints
whether the host still matches. It never blocks a commit — deploying is a
separate, deliberate step, and a commit from a machine that is not the host is
perfectly normal.

A global `core.hooksPath` (gitleaks and similar) keeps working: that hook
chains into the repo-local one, so both run.

### Why the installed file is a copy, not a symlink

Symlinking `/etc/nginx/conf.d/` into the working tree looks tidier but couples
the public vhost to a developer path: the config lives under `/home/human`,
which is `drwxr-x---`, so anything but root loses the whole vhost, and a
`git checkout` of another branch silently rewrites what production serves.
nginx only reads these files on start and reload, so such a break surfaces at
the next reload rather than at the moment it is introduced. Copying keeps the
deployed bytes stable until someone deploys on purpose, and `--check` recovers
the one thing the symlink was for — knowing whether the two agree.

## Deploying to a new host

Start the Compose stack from the profiles and service URLs configured in
`.env`, then run the one-time setup as the deployment user. The setup uses
`sudo` only for the host nginx files and reload; certbot itself runs in Docker.

```sh
docker compose up -d

./scripts/setup-public-https.sh
```

Use `setup-public-https.sh` only for a host that has no certificate yet; an
existing deployment is updated with `deploy.sh` above.

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
| `NGINX_CONFIG_PATH` | `/etc/nginx/conf.d/146-openvman.conf` |
| `LETSENCRYPT_CRON_SCHEDULE` | `17 4 * * *` |
| `LETSENCRYPT_RENEW_LOG` | `<repo>/backend/logs/letsencrypt-renew.log` |

DNS must already point at this host, inbound port 80 must reach host nginx, and
the deployment user must have Docker and crontab access.

## Why `/openvman/` is not configurable

The admin bundle hard-codes the same prefix
(`frontend/admin/src/components/app/navigation.ts`). Making it a template
variable would let the two drift apart, so both sides keep it literal.
