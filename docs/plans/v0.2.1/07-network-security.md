# Private-Network Policy And MCP Discovery

Status: proposed focused review and implementation plan, not a completed audit.
Start early; demonstrated authority-expansion findings block affected features.

## Goal

Make intended local-service access explicit without allowing arbitrary web
content or discovery metadata to expand network authority or expose credentials.

## Existing File Targets

`capabilities/tools/web.py`, `browser/cdp.py`, browser tool handlers,
`mcp/client.py`, `mcp/oauth.py`, `mcp/registry.py`, settings, and syscall
mediation. Inspect the MCP SDK's transport hooks and existing `_valid_metadata_url`
behavior before assuming checks cover every discovery/token request.

## Policy Decisions

Define separately:

- Public web access from agent tools.
- Operator-authorized local services and MCP endpoints.
- OAuth loopback callbacks, which are not arbitrary private-network egress.
- Browser navigation/subresources, which have a different transport from httpx.

Recommend rejecting private/loopback/link-local/reserved destinations for general
web tools unless the operator explicitly grants a narrow exception. Preserve
intentional local MCP use through an explicit endpoint policy, not a blanket ban
or automatic exception for anything described as "local".

Record exception scope, audit visibility, revocation, and compatibility warnings.
Do not silently break approved local integrations or silently grandfather broad
authority. An allowlisted public hostname is not proof its resolved IP is public.

## Focused Threat Review

- URL credentials, unexpected schemes/ports, malformed hostnames, IPv4/IPv6 and
  mapped addresses, trailing dots, IDNA, and alternate IP representations.
- DNS rebinding and mixed public/private answers; redirects and proxy behavior.
- Browser subresources, frames, script-driven navigation, WebSockets, downloads,
  and redirects: top-level URL validation alone is insufficient.
- MCP resource metadata, authorization-server metadata, issuer consistency,
  endpoint substitutions, registration/token calls, and cross-origin redirects.
- Authorization headers/tokens must not follow untrusted destinations. Separate
  provider/MCP credential context from generic fetching.
- Body/time/redirect limits, metadata parse failures, and redaction of errors.

## Implementation Steps

1. Map every affected outbound request and existing approval/validation point.
   Record confirmed findings and supported local-service workflows.
2. Specify destination classification and exceptions behind one small policy
   interface; use transport-specific enforcement rather than duplicating rules.
3. Enforce web-fetch policy at every redirect and at actual connection resolution.
   Reject unhandled rebinding/proxy paths instead of claiming preflight DNS is
   complete protection. Test existing visited-source semantics on allowed URLs.
4. Select enforceable browser network controls for supported Chrome/CDP paths.
   If the control cannot cover a traffic class, block that class or explicitly
   gate the feature; document residual risk, not a false blanket guarantee.
5. Apply endpoint/issuer/credential checks through actual MCP SDK requests,
   preserving intended OAuth loopback and refresh behavior.
6. Add operator configuration, audit records, compatibility messaging, and
   regression tests before enabling changed policy.

## Verification

Use local synthetic HTTP/DNS/redirect fixtures and mocked SDK transport; do not
scan real private networks or send real credentials. Test default deny, narrowly
allowed localhost service, revocation, redirect-to-private, mixed DNS results,
browser subrequests, hostile metadata, endpoint mismatch, and refresh.

Document the actual enforcement mechanism and unresolved risks. A passing URL
parser test is not evidence of browser-level or connection-level enforcement.
