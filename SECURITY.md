# Security Policy

## Supported Versions

We release security updates for the latest version only. Please ensure you are running the latest release.

| Version  | Supported          |
| -------- | ------------------ |
| Latest   | :white_check_mark: |
| < Latest | :x:                |

## Reporting a Vulnerability

We take the security of eating-medication seriously. If you believe you have found a security vulnerability, please report it responsibly.

### How to Report

**Please do NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities via:

1. **GitHub Security Advisories** (preferred): Navigate to the [Security tab](https://github.com/diaoyunxi/eating-medication/security/advisories) and click "Report a vulnerability"
2. **Email**: Contact the repository maintainer directly via GitHub profile

### What to Include

When reporting a vulnerability, please include:

- A description of the vulnerability
- Steps to reproduce the issue
- Potential impact assessment
- Any suggested fixes or mitigations

### Response Timeline

- **Acknowledgment**: We will acknowledge receipt within 48 hours
- **Assessment**: We will assess the vulnerability within 7 days
- **Resolution**: We aim to release a fix within 30 days for confirmed vulnerabilities

### Disclosure Policy

- We will work with you to understand and validate the vulnerability
- We will notify users via GitHub Security Advisory once a fix is available
- Public disclosure will occur after a fix has been released and users have had reasonable time to update

## Security Best Practices for Deployers

When deploying eating-medication in production:

1. **Set `DEBUG=false`** in all `.env` files
2. **Configure a strong `SECRET_KEY`** — the server will refuse to start with weak or auto-generated keys in production mode
3. **Configure `TURNSTILE_SECRET_KEY`** — without it, all login/registration requests will be rejected in production
4. **Set `ALLOWED_ORIGINS`** to your actual domain(s) — leaving it empty disables CORS entirely
5. **Use HTTPS** via Cloudflare Tunnel or reverse proxy — the application listens on HTTP locally
6. **Keep dependencies updated** — run `pip install -r requirements.txt` periodically
7. **Protect `.env` files** — they contain secrets and should never be committed to version control
8. **Use systemd** for process management in production deployments
9. **Enable automatic updates** (`AUTO_PULL=true`) to receive security patches promptly

## Security Features

This project implements the following security measures:

- **JWT Authentication** with algorithm whitelisting (prevents `alg=none` downgrade attacks)
- **bcrypt password hashing** (12 rounds)
- **Timing-safe comparison** for device tokens (`secrets.compare_digest`)
- **Cloudflare Turnstile** bot protection for login/registration
- **Rate limiting** on sensitive endpoints (login, register, email codes, AI queries)
- **Security headers** (CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
- **CORS whitelist** (no wildcard origins; disabled when unconfigured)
- **Release Attestation** verification for automatic updates (via `gh attestation verify`)
- **Production hardening**: weak SECRET_KEY rejection, API docs hidden, debug mode guards
- **Input validation** via Pydantic schemas
- **SQL injection prevention** via SQLAlchemy ORM parameterized queries

## Scope

Security reports are in-scope for:

- The eating-medication server (`server/`)
- The family monitor web application (`family_monitor/`)
- The elderly assistant client (`elderly_assistant/`)
- The shared common library (`common/`)
- Deployment scripts and configurations (`deploy/`)

Out of scope:

- Third-party services (Cloudflare, GitHub OAuth, ZhipuAI, Baidu OCR)
- Vulnerabilities in dependencies (report to upstream; we update promptly)
- Issues requiring physical access to the device
