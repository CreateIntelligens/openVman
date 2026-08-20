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

1. **Render the vhost.** `PUBLIC_DOMAIN` is required; the rest default to the
   values this repo uses.

   ```sh
   PUBLIC_DOMAIN=example.com ./scripts/render-native-nginx.sh
   ```

   | Variable | Default |
   | --- | --- |
   | `PUBLIC_DOMAIN` | *(required)* |
   | `LETSENCRYPT_DIR` | `<repo>/infra/nginx/certs/letsencrypt` |
   | `EDGE_UPSTREAM` | `127.0.0.1:8787` |
   | `ACME_WEBROOT` | `/usr/share/nginx/html` |

2. **Issue the certificate.** certbot runs as a container rather than a host
   package, so the cert directory is bind-mounted at the standard
   `/etc/letsencrypt` path inside it. Serve the ACME challenge from
   `ACME_WEBROOT` first — the vhost's `/.well-known/acme-challenge/` location
   already points there.

   ```sh
   docker run --rm \
     -v /usr/share/nginx/html:/var/www/certbot \
     -v "$PWD/infra/nginx/certs/letsencrypt:/etc/letsencrypt" \
     certbot/certbot certonly --webroot --webroot-path /var/www/certbot \
     -d example.com
   ```

3. **Install and reload.**

   ```sh
   sudo cp infra/nginx/native/openvman.conf /etc/nginx/conf.d/
   sudo nginx -t && sudo systemctl reload nginx
   ```

4. **Schedule renewal.** See `infra/nginx/certs/README.md`.

   ```
   17 4 * * * /path/to/repo/scripts/renew-letsencrypt.sh >>/var/log/openvman-certbot-renew.log 2>&1
   ```

## Why `/openvman/` is not configurable

The admin bundle hard-codes the same prefix
(`frontend/admin/src/components/app/navigation.ts`). Making it a template
variable would let the two drift apart, so both sides keep it literal.
