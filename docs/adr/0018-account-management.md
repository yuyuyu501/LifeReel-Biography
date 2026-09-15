# ADR 0018: SMS Registration and Account Management

Status: Accepted, 2026-09-15

## Scope

Public registration requires a verified mainland China phone number, a name and
an 8-200 character password. Existing email accounts continue to log in. Each new
account gets a separate tenant, the standard interview chapters, and the configured
welcome credit (currently CNY 20), in the same transaction as consuming its code.
Unverified email self-registration is removed rather than kept as a bypass.

Personal settings at `/account` provide profile updates, password changes, verified
phone binding/replacement, and account closure. `/forgot-password` accepts a phone
verification challenge. Password changes/reset, phone replacement, logout,
administrative changes, disable and deletion invalidate existing signed sessions.
The signed session contains a version checked against the database on every request.
Logout currently signs out all devices. Existing sessions without a version remain
valid only while the account's version is zero.

Platform administrators have `/admin/accounts`: paginated search, status filter,
individual account details, creation, editing, password reset, disable/re-enable,
and deletion. Administrator-created accounts use email and a password; they must
verify a phone themselves before using SMS recovery. The API does not expose role
promotion or unverified phone assignment. Ordinary family owners are not platform
administrators. Administrator accounts cannot be disabled/deleted through these
management endpoints, preventing accidental loss of the management entry point.

## SMS Provider

Use the official Alibaba Cloud `alibabacloud-dysmsapi20170525` SDK and SendSms API
over HTTPS. `SMS_ACCESS_KEY_ID` and `SMS_ACCESS_KEY_SECRET`, when empty, reuse the
server's existing `S3_ACCESS_KEY` and `S3_SECRET_KEY`. Nothing is sent to the frontend
or stored in tracked configuration. A dedicated least-privilege RAM key is preferable
for production; it needs `dysms:SendSms` permission. Query permissions alone do not
prove sending permission or carrier delivery.

Configuration:

| Setting | Meaning |
| --- | --- |
| `REGISTRATION_ENABLED` | Opens public verified registration |
| `SMS_ENABLED` | Enables the real SMS adapter |
| `SMS_SIGN_NAME` | Approved signature associated with the template |
| `SMS_TEMPLATE_CODE` | Registration verification template |
| `SMS_SECURITY_TEMPLATE_CODE` | Generic identity-verification template for binding and closure |
| `SMS_RESET_TEMPLATE_CODE` | Optional password recovery template; falls back only to the security template |
| `SMS_CODE_PARAMETER` | Template variable name, default `code` |
| `SMS_CODE_TTL_SECONDS` | Challenge validity, default 300 seconds |
| `SMS_DAILY_LIMIT` | Global sending quota, default 500 per rolling 24 hours |

Never fall back from identity verification to a registration-only template. The
public configuration endpoint describes which flows are configured. A provider
acceptance response means submitted, not delivered. SDK retries are off to avoid
silently sending duplicate paid messages after an ambiguous network timeout.

## Abuse and Concurrency

- Six digits are generated with `secrets.randbelow`; only an HMAC is stored.
- The HMAC includes challenge ID, phone and purpose. A challenge cannot verify a
  different phone or operation, expires after five minutes, and allows five mistakes.
- Resending invalidates previous outstanding challenges for that phone/purpose.
- Successful consumption and account mutation commit together under a PostgreSQL
  row lock. A replay cannot create a second account or repeat a reset.
- Phone ownership claims are retained across replacement and closure. Old numbers
  cannot be used to repeatedly register and collect welcome credit. Recycled-number
  ownership disputes require a support process; the UI does not release claims.
- Database-backed atomic rate counters are shared across API processes, not Python
  memory. Sending limits are one per phone/60 seconds, five per phone/hour, ten per
  phone/day, twenty per client IP/hour, plus the global quota. Failed sending attempts
  also count. Login is limited per account and IP; sensitive operations per account.
- Expired challenge/counter cleanup runs opportunistically during auth requests.
- The public host proxy appends the actual source IP. The private web proxy trusts
  its local/Docker upstream, uses the last address (not attacker-supplied earlier
  entries), overwrites `X-Real-IP`, clears `X-Forwarded-For` and injects its private
  API key. The API accepts `X-Real-IP` only from authenticated internal requests.
  Keep web port 5173 loopback-only and the API private. Revisit trusted ranges when
  changing the network topology.

These are baseline controls, not a claim to defeat phone farms. Before a broad
promotion, add Alibaba captcha/risk checks and configure provider-side spending
and daily SMS limits as a second boundary.

## Deletion and Audit

Deletion is a soft delete: no login, not listed among manageable accounts, and not
reactivatable through the normal management API. Original tenant data and billing
records are not deleted. Closure is blocked when there are paid funds, debt, frozen
funds or unfinished jobs. Platform admins can disable access while those obligations
are being resolved. Phone users must present their password and a closure-specific
SMS challenge to close their own account; legacy email-only users use their password.

An account audit row records actor, target, action and changed field names. Passwords,
codes and provider credentials are excluded. The platform admin API does not grant
access to another family's biography content through the normal tenant APIs.

## Migration and Release

Migration `20260915_0026` adds nullable unique phones, admin status, session version,
deletion timestamp, phone claims, SMS challenges, rate counters and account audits.
It promotes only the configured bootstrap owner who already owns the default
tenant. It does not alter existing password hashes, wallet balances, scripts or
assets. Fresh bootstraps create that owner as an administrator. Later seed runs do
not re-enable deleted users or reassign existing privileges.

Deploy in the established order: local implementation and tests, Git commit/push,
server fast-forward pull, backup, migrate/restart, verify. There is no production
test OTP. Automated tests use an explicitly substituted sender and isolated database.
Avoid schema downgrade after phone registration begins; the downgrade refuses when
phone or deleted accounts exist. A previous application image can run against the
additive schema, but cannot manage phone-only accounts.

## Verification

Backend tests cover registration isolation and welcome credit, code expiration,
incorrect attempts, replay, resend, phone/purpose mismatch, failed sending,
password reset, session invalidation, anti-credit farming, admin CRUD, permissions,
protected administrators, deletion obligations, rate limits and official SDK request
construction. Frontend tests cover forms, errors, cooldowns, reset and administration.
Browser QA uses real HTTP API calls with an isolated database and a fake sender;
the existing family data and real SMS delivery are not touched.
