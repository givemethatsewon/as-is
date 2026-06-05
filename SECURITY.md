# Security Policy

## Supported Versions

The current public baseline is `v0.1.x`. Security fixes, if needed, will target the latest public release.

## Reporting A Vulnerability

Please do not open a public GitHub issue for a vulnerability or data exposure report.

Contact the maintainer privately through the email listed on the GitHub profile, or open a minimal private advisory request if GitHub Security Advisories are enabled for the repository.

Include:

- affected version or commit,
- reproduction steps,
- expected impact,
- whether the issue exposes uploaded files, local database contents, generated reports, credentials, or deployment secrets.

## Project Security Boundary

As-Is is currently a local-first demo application:

- default database: `sqlite:///./as_is.db`,
- default demo bind address: `127.0.0.1:8000`,
- no built-in user authentication,
- no multi-tenant authorization model,
- no production filing integration.

Do not expose this app directly to the public internet without adding authentication, authorization, transport security, audit logging, backup policy, and data retention rules.

## Data Handling

Do not commit real customer data, private declaration numbers, personal information, credentials, or production URLs. Use synthetic fixtures in `samples/` and `tests/`.

The matching engine is intended to produce review evidence. It should not be treated as legal, customs, tax, or refund eligibility advice without review by a qualified professional.
