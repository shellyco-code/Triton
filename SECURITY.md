# Security Policy

Triton can delete pods, so security reports are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private
[security advisory form](https://github.com/shellyco-code/Triton/security/advisories/new).
You should get a response within 7 days.

Especially in scope:

- Any way for pod logs, events, or other cluster data to make the agent read or act on a pod other than the incident pod (prompt injection).
- Bypasses of the remediation safety rails (target pinning, protected namespaces, controller check, rate limit).
- Unauthenticated access to mutating endpoints when `TRITON_API_TOKEN` is set.
- RBAC in `deploy/k8s` granting more than documented.

## Hardening checklist for deployments

- Set `TRITON_API_TOKEN` and keep `AUTO_REMEDIATE=false` until you trust the evals on your workloads.
- Add your critical namespaces to `PROTECTED_NAMESPACES`.
- Don't expose the Service publicly; use `kubectl port-forward` or an authenticated ingress.
