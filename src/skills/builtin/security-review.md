---
name: security-review
description: Security-focused code review checking for OWASP Top 10 and common vulnerabilities
aliases: [sec, security]
allowedTools: [bash, glob, grep, read_file]
context: inline
---
Perform a security review of the codebase or specified file/change.

Check for the following vulnerability classes:

**Injection**
- SQL injection (string formatting into queries — must use parameterized queries)
- Command injection (shell=True with user input, unsanitized subprocess args)
- LDAP, XPath, template injection

**Broken Authentication / Authorization**
- Hardcoded credentials or API keys
- Weak password hashing (MD5, SHA1 — use bcrypt/argon2)
- Missing authorization checks on sensitive endpoints
- Insecure JWT handling

**Sensitive Data Exposure**
- Secrets committed to version control (.env files, API keys in code)
- Unencrypted sensitive data at rest or in transit
- Excessive logging of sensitive fields (passwords, tokens, PII)

**Broken Access Control**
- Path traversal (../../../etc/passwd via user-controlled paths)
- IDOR (accessing resources by ID without ownership check)
- Privilege escalation

**Security Misconfigurations**
- Debug mode enabled in production
- CORS configured too broadly
- Missing security headers (CSP, HSTS, X-Frame-Options)
- Default credentials

**Vulnerable Dependencies**
- Run `pip audit`, `npm audit`, or `safety check` if available

**Cryptography Issues**
- Weak algorithms (DES, RC4, MD5 for security)
- Static/predictable IVs or seeds
- Incorrect TLS configuration

For each finding: severity (Critical/High/Medium/Low), file:line, description, and recommended fix.

{{{args}}}
