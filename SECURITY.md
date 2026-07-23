# Security policy

**English** · [简体中文](SECURITY.zh-CN.md)

Security is part of the design boundary of 漫读 (`novel-platform`), especially around
authentication, Passkeys, device authorization, private reading state, imported files, and
deployment defaults. That focus does not guarantee that the software is free of vulnerabilities.
Thank you for reporting security issues responsibly.

## Supported versions

Security fixes target the current default branch. Until the project publishes its first tagged
release, the latest commit on `main` is the only supported version. After tagged releases begin,
only the newest release line is supported unless the project states otherwise.

| Version | Supported |
| --- | --- |
| Current `main` (currently `0.9.x`) | Yes |
| Other branches and earlier commits | Best effort only |
| Older release lines | No |

If a report affects an older version, first check whether the issue is reproducible on the latest
release. The maintainer may still coordinate a disclosure for a serious issue with broad impact,
but no backport is promised.

## Reporting a vulnerability

Do not open a public GitHub Issue, Discussion, or pull request for a suspected vulnerability.
Email [alnemark0403@gmail.com](mailto:alnemark0403@gmail.com) with the subject
`[novel-platform security] short description`.

GitHub private vulnerability reports are available only after repository administrators enable
Private vulnerability reporting. If the repository's Security page displays **Report a
vulnerability**, you may use the
[private report form](https://github.com/taoning0403/novel-platform/security/advisories/new)
instead.

Email is not an end-to-end encrypted channel. Do not send live credentials, tokens, Cookies,
private keys, database dumps, imported books, or personal data. If sensitive material is required
to reproduce the issue, first send a minimal description and arrange a safer transfer method.

Please include, where possible:

- the affected version, commit, deployment mode, and relevant configuration with secrets removed;
- the security boundary that is bypassed and the practical impact;
- minimal, deterministic reproduction steps or a proof of concept using disposable test data;
- relevant request/response details, logs, or screenshots after removing credentials, Cookies,
  storage paths, book content, and personal information;
- whether the issue is already public or known to another party;
- your preferred name for acknowledgement, or a request to remain anonymous.

## Safe research expectations

- Test only against systems and data you own or are explicitly authorized to use.
- Prefer a local disposable environment created from this repository.
- Do not access, modify, retain, or disclose another person's data or imported content.
- Do not perform denial-of-service, destructive, persistence, phishing, or social-engineering
  tests.
- Stop testing and report immediately if you encounter live secrets, private data, or book files.
- Collect only the evidence needed to demonstrate the issue.

This policy does not grant authorization to test a deployment operated by someone else.

## What to expect

The maintainer aims to:

- acknowledge a complete report within five business days;
- provide an initial triage or request for more information within ten business days;
- keep the reporter informed when the status materially changes;
- coordinate a fix, release, and disclosure timeline based on severity and affected users.

These are response targets, not service-level guarantees. Please allow a reasonable remediation
period before public disclosure. The maintainer will credit reporters who request acknowledgement
and will respect requests for anonymity. This project currently offers no bug bounty or monetary
reward.

## Security scope

The intended deployment is a self-hosted personal site with one trusted server operator and one
logical administrator. Administrator or host-operator access to raw library files, PostgreSQL,
backups, and deployment secrets is expected. A security report should demonstrate that an
anonymous user, invited reader, or other lower-privileged actor can cross that boundary.

Examples of in-scope reports include:

- authentication, Passkey, recovery, Session, refresh-token, or device-authorization bypasses;
- administrator/reader authorization or cross-reader private-state violations;
- exposure of credentials, tokens, Cookies, storage paths, file hashes, audit secrets, or book
  content;
- unsafe EPUB/TXT parsing, archive traversal, active-content injection, or protected-resource
  bypasses;
- proxy trust, Origin, Cookie, rate-limit, or deployment-default weaknesses that create a concrete
  security impact;
- backup, restore, migration, or CLI flaws that expose or corrupt protected data outside the
  documented trusted-operator boundary;
- dependency vulnerabilities with a demonstrated impact on this project's supported release.

Ordinary bugs, feature requests, documentation corrections, and hardening ideas without a concrete
security impact may be filed as public Issues. Automated scanner output without a reproducible
impact, reports against unsupported versions only, and attacks requiring prior administrator
control without crossing another boundary are generally not treated as vulnerabilities.

## Coordinated disclosure

Do not publish details while a report is being validated or fixed. The maintainer and reporter
should agree on a reasonable public disclosure date. After remediation, the maintainer may publish
a GitHub Security Advisory containing affected versions, impact, mitigation, and reporter credit.
If the report is rejected or considered out of scope, the maintainer will explain why; reporters
may reply with additional evidence or request reconsideration.
