# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability, please **do NOT open a public issue**.

Instead, email the maintainer privately with:
- A description of the issue
- Steps to reproduce
- Affected version

You should receive a response within 72 hours.

## Hardening Checklist (Production Deployment)

Before exposing Ye to the internet, make sure you have done ALL of the following:

### Required
- [ ] Generated a random 64+ char `SECRET_KEY` (never use the default)
- [ ] Set `ENV=production` (this makes startup fail-fast on insecure config)
- [ ] Set `CORS_ORIGINS` to an explicit allowlist — NO wildcards
- [ ] Rotated `ZHIPU_API_KEY` and stored it in a secret manager
- [ ] Removed all `*.apk` and binary blobs from git history
- [ ] Enabled HTTPS (via Nginx/Caddy/Traefik in front of the app)
- [ ] Run behind a reverse proxy with rate limiting

### Recommended
- [ ] Add login rate limiting (slowapi)
- [ ] Run the Docker container as non-root user
- [ ] Enable Docker `--security-opt no-new-privileges`
- [ ] Set up log aggregation and alerting
- [ ] Daily database backups

## Security Headers (Reverse Proxy)

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; ...
```
