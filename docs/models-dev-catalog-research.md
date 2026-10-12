# models.dev As CaberOS's Catalog Source

Research date: 2026-10-09. Status: recommendation, not an implemented adapter.

## Recommendation

Use models.dev as the primary third-party metadata/pricing catalog instead of
using OpenRouter as a universal oracle. Keep configured-provider discovery for
live account/endpoint availability, user overrides for declared facts, and
LiteLLM for transport. OpenRouter's own discovery remains when the configured
provider is OpenRouter; this recommendation does not remove that provider.

Settled W11 decision: LiteLLM is execution-only. A bundled models.dev snapshot provides offline metadata/rates; application-data updates refresh daily. CaberOS performs cost assessment locally.

## Primary-Source Findings

- The project describes itself as community-contributed specifications, pricing,
  and capabilities, with a public JSON interface at `https://models.dev/api.json`.
  It also offers `models.json` for provider-agnostic metadata and `catalog.json`
  for combined provider/model data. [README][readme]
- Provider entries can inherit model-only facts using `base_model`, while
  provider-specific overrides win. Generated entries may carry
  `canonical_model_id`; that identity is attribution, not permission to replace
  the exact request ID or copy prices between providers. [README][readme]
- Documented fields include separate context/input/output limits, input/output
  modalities, reasoning, tool calling, structured output, and model dates.
  Not every optional field is present in every entry. [README][readme]
- Pricing fields are documented in USD per million tokens. Source definitions
  include input/output, reasoning, cache read/write, audio dimensions, and context
  tiers. Generated output can include both `tiers` and legacy
  `context_over_200k`; supported billing semantics still need CaberOS's explicit
  pricing recipes. [README][readme], [source schema][schema]
- The source also supports `reasoning_options`; adapters should preserve declared
  effort/budget/toggle controls rather than synthesize every possible effort from
  a single reasoning boolean. [source schema][schema]
- The repository's license is MIT, with copyright/license-notice retention when
  redistributing copies or substantial portions. Preserve attribution in any
  vendored catalog snapshot. [LICENSE][license]

## Direct Interface Checks

Public `api.json` was read without credentials. Explicit sample lookups were
`openai/gpt-4.1`, `anthropic/claude-sonnet-4-5`, and
`openrouter/openai/gpt-4.1` (provider key followed by exact provider model key).
The inspected entries expose provider-grouped models, cost, limit, and modalities;
only the sampled Anthropic entry included `reasoning_options`. This is sample
schema evidence, not a completeness guarantee or verification of the prices.

The published `model-schema.json` currently describes model-identifier enums,
not the complete provider/model payload validation contract. Consult the source
schema and validate a bounded internal projection; do not mistake that endpoint
for a validator of the full catalog JSON.

## CaberOS Integration Rules

1. Match a configured provider to an explicit catalog provider key and preserve
   its exact request model ID. A provider type or similar model name is not enough
   to map a custom proxy to official-provider prices. Explicit canonical mappings
   may enrich model facts, never silently transfer offering prices.
2. Field resolution: user declaration, applicable provider report, models.dev
   catalog entry, then an explicit unknown/labelled application policy; no
   LiteLLM metadata fallback. Missing fields stay unknown. models.dev data is
   catalog-documented, not provider-verified.
3. Catalog presence does not establish endpoint/account availability. Discovery
   failure remains unknown/stale rather than automatically unavailable.
4. Keep fetch time, upstream model update date, and known pricing-effective dates
   distinct. `last_updated` is not proof that a rate applied to a historical call.
5. Snapshot rates used for estimates. Preserve reported monetary amounts; leave
   unsupported dimensions or insufficient usage unresolved. Unknown historical
   calls cannot be turned into actual billing by multiplying by today's rates.
6. Load a vendored/cached validated snapshot locally; refresh asynchronously under
   the egress policy with bounded requests, schema checks, and last-known-good
   retention. The bundled snapshot is immutable; application data carries the
   mutable last-known-good cache. Refresh once per 24 hours and never silently
   reprice historical assessments. A models.dev outage must not stop the picker
   or agent execution.
7. Treat catalog `api`, `env`, `npm`, and transport hints as untrusted descriptive
   data, not configuration instructions. Do not replace configured endpoints,
   transmit credentials, install packages, or execute code from catalog fields.
8. Consumption requires plain JSON over HTTPS, not the upstream JavaScript SDK or
   a new user-installed Node runtime. LiteLLM remains the existing transport.

## Scope

This note records the source decision reflected in W11. No runtime behavior,
pricing rows, provider configuration, or deployed environment variables have
changed. Implementing the adapter, accounting, migrations, and tests is separate
work. Additional catalogs are not needed for the first implementation;
any future fallback must carry its own provenance and offering applicability.

[readme]: https://github.com/anomalyco/models.dev/blob/dev/README.md
[schema]: https://github.com/anomalyco/models.dev/blob/dev/packages/core/src/schema.ts
[license]: https://github.com/anomalyco/models.dev/blob/dev/LICENSE
