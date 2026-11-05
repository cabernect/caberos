# Search Services In Tools

Status: initial DDGS/Tavily slice implemented and fixture-tested; Exa/Brave API
adapters and broader integration remain pending. No live-provider verification
is claimed. This plan does not authorize provider requests, commits, or release
publication.

## Product Decision

Settings -> Tools -> Web Search owns backend selection, API-key entry, options,
connection testing, and readiness. Do not require a separate trip to Providers
or introduce a Search Providers section there. Providers remains the place for
chat/model connections.

Keep one agent-facing `web_search` capability. The operator chooses its backend;
the model cannot choose credentials, endpoints, or a more expensive service.
Existing grants, approvals, and syscall mediation remain mandatory.

## Scope And Current Evidence

- The preserved free implementation is DDGS with an ordered engine cascade, SafeSearch,
  and region. It returns the first nonempty engine result, not a merged ranking.
- DDGS's `brave` engine is not the official Brave Search API.
- A Tavily adapter is covered by scripted HTTP fixtures. Official-contract review
  and a consented live smoke test remain pending; fixtures alone do not establish
  provider compatibility. Exa and Brave Search API adapters remain unimplemented.
  Firecrawl and other services remain follow-up scope.
- Preserve DDGS as the free default and existing saved options across migration.
  Selecting a dedicated API does not silently fall back to DDGS or another API.
- Return search results, not provider-generated answers or fetched page content
  in this slice. Hits are trace evidence, not visited `WebSource` references.

## Configuration And Credential Contract

Configure connections in Tools, but reuse existing `Provider` rows for service
type, display name, and encrypted credentials. Bindings own validated nonsecret
options and revision. Service scope is derived from the provider type. Reuse the
platform's Fernet encryption/redaction primitives; do not put keys into plaintext
`ToolBinding.options`, Provider `extra_params`, browser storage, or prompts.

Do not create a separate tool-connection table or secret store. The existing
binding references `Provider.id`; service providers are filtered out of model
pickers/discovery and rejected by model dispatch. Support multiple named
connections inline without requiring a trip to the Providers tab.

- API-key entry is write-only. Reads expose `has_key`, never a key or masked key
  value that clients must resubmit. Omitted key means unchanged; replacement and
  removal are explicit operations. Mutation responses and audit errors redact it.
- Offer backend, connection name, masked key input, provider-specific options,
  Save, and Test connection inside Web Search. No model selector for search.
- Distinguish unconfigured, configured-but-untested, ready, and invalid.
  Saving validates locally; opening settings and Save make no provider requests.
  A passed test is historical evidence, not a promise of future quota/network health.
- Test connection is an explicit, bounded server-side request with a synthetic
  query. Explain remote egress and possible charges before dispatch; do not send
  workspace or conversation content. Rate-limit probes and redact responses.
- Removing a key/connection invalidates dependent bindings clearly. Do not erase
  historical receipts or silently pick another connection.
- Keep endpoints fixed to reviewed provider destinations for this slice. No
  arbitrary custom base URLs, client-supplied authorization headers, or redirect
  forwarding of secrets.

## Execution And Accounting

1. Resolve/freeze service, connection revision, and options before approval.
   Use shared server-side credential resolution, never model-supplied secrets.
2. Enforce query/result limits, provider-specific allowlisted options, total
   timeout, response byte limits, and safe outbound destination policy.
3. Normalize results to title, URL, and snippet, plus service/attempt provenance.
   Bound text and handle missing/invalid fields without fabricating content.
4. Authentication/quota/network/parse failures surface honestly. No automatic
   paid retries after ambiguous dispatch; retries must be explicit.
5. Record actual attempts and timing through existing syscall audit correlation.
   Search APIs are not LLM calls: do not fabricate model/token usage. Define a
   typed service-usage receipt integrated with observability/spend before shipping;
   record requests/credits and reported or estimated cost only with provenance.
   Unknown usage/cost stays unknown, not zero.
6. Keep intended DDGS internal engine fallback distinct from cross-service
   fallback. A configured API must never broaden egress via an implicit fallback.

## Implementation Units

1. Inspect official docs for each API; record auth, option, result, quota, and
   pricing/usage contracts with fixture payloads. No real probes without consent.
2. Reuse Provider storage/encryption and authenticated CRUD; add service scoping,
   explicit key replacement/removal, and binding revision/drift tests. This slice
   requires no schema migration. Speech in [W10](10-speech-input-output.md)
   reuses the same custody path.
3. Extend binding resolution and admission freezing for a keyed search service;
   keep authorization independent of configuration.
4. Implement Tavily, Exa, and Brave adapters with deterministic HTTP fixtures,
   normalized results, receipts, and failure/timeout/bounds tests.
5. Add inline credential/backend configuration and explicit test UI to Tools;
   verify keyboard, masked fields, empty/error states, desktop, and mobile.
6. Integrate audit/spend inspection, regression-test DDGS migration, and record
   browser evidence. Enable only complete supported adapters.

## Existing And Proposed File Targets

Existing: `backend/src/agentos/capabilities/bindings.py`,
`capabilities/tools/web.py`, `syscall/mediator.py`, `api/settings.py`,
`models/tool_binding.py`, encryption helpers, both DB backends, and observability
services; frontend `src/pages/ProvidersSettings.tsx` (`ToolsTab`),
`src/lib/api.ts`, `src/lib/types.ts`, and `src/pages/ToolsTab.test.tsx`.

Proposed extensions: provider service classification and search adapter modules.
Keep provider quirks out of the UI and mediator; inventory actual helpers before
choosing new module names.

## Acceptance

- Configure all three dedicated APIs entirely inside Tools, without visiting
  Providers; restart preserves encrypted connections and selected backend.
- Invalid/missing keys fail clearly; no secrets appear in GET responses, logs,
  audit payloads, tool results, exports, or unencrypted configuration.
- Saving does not probe; explicit testing does not send private query content.
- Agent grants and pending approvals remain authoritative during backend changes.
- DDGS defaults/order survive migration; official Brave API is labeled distinctly.
- Each adapter has success, empty, 401/403, 429, timeout, malformed/oversize,
  cancellation, and binding-drift fixtures. Unknown billing is never called free.
- Search hits do not create visited-source records. Wide/narrow browser tests
  exercise real configuration flows against scripted services.
