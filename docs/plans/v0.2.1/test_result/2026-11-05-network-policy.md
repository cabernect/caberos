# Network Policy Review And Enforcement

Date: 2026-11-05. Worktree: `feat/v0.2.1`, uncommitted.
Covers plan `07-network-security.md`. Fixtures are synthetic: DNS answers are
monkeypatched and HTTP traffic runs through `httpx.MockTransport`; no real
private network was scanned and no real credentials were sent.

## Status Correction

This is historical evidence for the initial fetch/navigation slice, not W7
completion or a completed security audit. W7 remains OPEN under the enhanced
host-protection plan. Statements below about MCP metadata destinations describe
the reviewed integration, not verified issuer/credential containment. Operator
configuration and browser OAuth consent do not close that trust boundary.

The initial host-only allowlist does not prove service-scoped consent or
revocation of live connections. Browser preflight does not protect subrequests
or rebinding. S01/S03 are partial; S02/S04 and new S05-S10 remain open/blocking
as recorded in the acceptance matrix. Preserve the test counts as historical
results, not proof of the expanded contracts.

## Follow-Up: Execution Inventory And Download Authority

The non-W7 feature work is now committed separately:

- `b72abae`: chat copy actions and latest-message scrolling.
- `82eecd4`: MCP setup and query-only capability discovery.
- `8308823`: search services and inline Provider configuration.

The existing staged plan rename was preserved. No push was performed. The
earlier suite counts do not establish verification of split commit snapshots
or later changes.

The initial W7 slices are now separate commits:

- `79b3595`: pinned web-fetch policy, settings, and shared classifier.
- `d46a346`: explicit browser navigation checks (not browser-wide containment).
- `08b6487`: no automatic Docker sandbox-image downloads.
- `d2e35b5`: Seatbelt file/temp confinement and synthetic readiness.

Current verification for the split commits is static only. Earlier fixture
results remain historical evidence; native/runtime follow-up is still pending.

### Source-Level Execution Inventory

This table describes inspected source, not a live isolation or exploit test.

| Path | Existing boundary | Gap against the enhanced W7 contract |
|---|---|---|
| Seatbelt | Workspace writes; minimal child environment; network denied by default | `_build_profile` allows all file reads and shared `/private/tmp` writes; not workspace-only confidentiality or private scratch |
| Bubblewrap | Read-only system mounts, workspace bind, private `/tmp`, namespaces, cleared inner environment | CPU/memory/process/output bounds and host-launcher environment still need verification |
| Docker | Workspace bind and default `--network none`; synchronous timeout kills owned container | No explicit CPU/memory/PID/capability/root-filesystem limits; background registry kills CLI rather than proving container termination |
| MXC | Explicit container environment and network policy; experimental trust surfaced | Windows-native isolation, resource limits, and descendant cleanup need platform evidence |
| Terminal registry | Run/agent/session ownership; bounded spooled output; process-group cleanup | Backend-specific cleanup is needed for Docker; group termination is not proof of containment for escaped descendants |
| MCP stdio | Per-server command/env resolution and SDK-owned lifecycle | No CaberOS sandbox wrapper at the `stdio_client` launch; effective SDK environment/secret exposure needs separate verification |

Do not interpret this inventory as proof that all paths are vulnerable or that
all listed controls are effective. In particular, Seatbelt's read permission is
visible in source, but no real personal file was read to demonstrate it.

### Implemented Follow-Up: No Implicit Docker Image Downloads

`sandbox/docker.py` now checks daemon availability and local image presence only.
A missing or uninspectable `alpine:3.20` reports unavailable with an explicit
operator-run install command. The probe does not execute `docker pull`.

Both synchronous and background argv use `docker run --pull=never`, including
when network access is explicitly requested. If an image disappears after a
successful probe, the execution must fail rather than download a replacement.
This does not harden image provenance, the Docker daemon endpoint, container
resource limits, or background-container cleanup.

`tests/test_sandbox_docker.py` contains 11 tests after this change, including
missing-image refusal, inspection failure, cached readiness, no-pull argv for
both launch paths, explicit-network behavior, and existing timeout cleanup.
These tests use mocked subprocess calls; even a passing run would not establish
live container enforcement.

### Validation And Blocker

Static checks run from the repository root:

```bash
./backend/.venv/bin/ruff check --no-cache backend/src/agentos/sandbox/docker.py backend/tests/test_sandbox_docker.py
./backend/.venv/bin/ruff format --check --no-cache backend/src/agentos/sandbox/docker.py backend/tests/test_sandbox_docker.py
git diff --check
```

Results: Ruff passed; both files already formatted; whitespace check passed.
Both files parse with `ast.parse`; 11 test functions were counted without
executing them.

Runtime tests: NOT RUN. A trusted, source-free test-runner setup check failed
to install a 1 GiB `RLIMIT_AS` memory limit on this macOS environment
(`ValueError: current limit exceeds maximum limit`). The target test process
was not launched. No Docker executable is available on PATH. Tests were not
re-run outside the required enforced isolation as a workaround.

Next validation requires an isolated runner with enforced network, filesystem,
environment, CPU/memory/process/output/disk/time bounds. Run the Docker unit
tests there, followed by an offline daemon test with a preloaded synthetic
image: prove missing-image refusal, no registry contact on either launch path,
and failure without download after image removal. Image removal is destructive
and requires separate approval for the exact disposable image; do not remove
an operator's existing images.

### Subsequent Patch: Seatbelt Read And Temp Confinement

`sandbox/seatbelt.py` now builds a default-deny SBPL profile with explicit
workspace read/write/exec grants and fixed Apple runtime/developer-tool read/exec
roots. There is no unrestricted `file-read*` or `process-exec*` grant.
The system allowlist deliberately excludes broad `/System` (which contains
`/System/Volumes/Data`) and `/usr` (which contains `/usr/local`) grants.
Path metadata lookup remains allowed globally; this is not a claim of hiding
all path existence or file-size metadata.

Shared `/private/tmp` and `/dev/dtracehelper` write grants are removed. HOME,
TMPDIR, TMP, and TEMP point to the workspace, using the same environment helper
for synchronous and background terminals. No host environment variables are
inherited. Temp files remain shared with peers explicitly sharing the workspace,
not isolated by run. Existing secrets inside a granted workspace are not filtered
by this policy.

Machine root, home/ancestor roots, runtime-overlapping workspaces, and workspace
names containing control characters are refused. Quotes/backslashes in supported
workspace names are escaped in the profile. Homebrew and arbitrary personal
applications are not added implicitly to preserve compatibility.

Seatbelt availability now runs a bounded, cached synthetic self-check: create
an owned temporary workspace and dummy sibling, prove child workspace read/write,
and require sibling read/write to fail with its bytes unchanged. An unsupported
profile or failed self-check reports unavailable without restoring permissive
rules. Auto may then select another existing sandbox under its established
selection policy; it does not select unsandboxed host execution. This check
does not establish containment for every traffic/process class.

`tests/test_sandbox_seatbelt.py` adds 14 test functions (some parameterized):
profile grants/default deny, narrow network opt-in, path escaping/rejection,
clean environment/temp settings, sync/background parity, and fail-closed cached
readiness. Three native test functions cover workspace/temp operation, direct
and symlinked sibling-secret denial, and outside-temp overwrite denial. Native
tests require macOS plus `CABEROS_TEST_SEATBELT_LIVE=1` in an isolated runner.
All canaries are synthetic; no real operator secrets are test inputs.

Static validation: Ruff check passed, both new/edited files are formatted,
`ast.parse` succeeded, and `git diff --check` passed. No target test code or
native Seatbelt probes were executed in this follow-up. The isolated-runner
memory-limit blocker remains; these tests are written, NOT passed. The changed
profile's toolchain compatibility and SBPL behavior still need native evidence.

Next priorities are isolated native verification, bounded command output and
backend-specific termination. Browser egress, service-scoped network exceptions,
MCP transport enforcement, and resource limits remain blockers; W7 and S05/S09
are still OPEN.

### Subsequent Patch: Background Resource Lifecycle

Background launch planning is now side-effect-free. The terminal registry saves
the backend/resource identity in a `starting` row before resource activation;
the production shared write-lock commits on clean exit. Docker then explicitly
creates an owned, labeled container before attaching. This avoids a late
container creation racing the death of a `docker run` client.

Close, run cancellation, natural client exit, and gateway shutdown use the
captured backend/launch rather than current settings or model-supplied identity.
Cleanup checks the generated resource-name shape and ownership label before
force-removing that exact container; it never requests volume removal or broad
container cleanup. A failed inspect requires a separate successful absence
query, not an assumption that the container disappeared.

SQLite and Postgres additive patches preserve backend/resource metadata.
Restart reconciliation retries recorded `starting`, `running`, and `orphaned`
Docker resources. Unconfirmed cleanup stays `orphaned` and retryable, including
when the local CLI has already exited successfully. Concurrent close/monitor
paths serialize cleanup; cancellation does not manufacture a closed state.
Legacy local interrupted rows remain unknown with respect to descendant
termination. Daemon requests whose completion is unknown still require repeated
reconciliation; this is not a lease-expiry guarantee.

Written tests cover durable admission before activation, ownership mismatch,
invalid cleanup identities, inspect/daemon failure, retry, concurrent close,
cancel/shutdown, natural client exit, and restart outcomes. Ruff and formatting
checks pass on the changed Python files. Runtime/DB/daemon tests remain NOT RUN;
the isolated-runner blocker has not been bypassed. No real containers were
created, stopped, or removed by this work.

### Subsequent Patches: Limits, Stateless Fetch, Cached OAuth

`d8d2a43` adds Docker resource/privilege flags to the shared foreground and
background command builder: non-root UID/GID, dropped capabilities,
no-new-privileges, read-only image, 64 PIDs, one CPU, 256 MiB memory/no extra
swap, 256 file descriptors, 64 MiB per-file limits, and a 32 MiB private noexec
temp mount. Aggregate workspace disk usage and background wall-clock bounds
are still open. A flag assertion is not proof that the daemon enforces it.

`77a23dd` adds a total fetch deadline across DNS/redirects/streaming, clears
cookies before each hop (pinned IPs must not become cross-origin cookie keys),
and refuses credential/custom headers in generic fetching. Identity-only
responses prevent decompression from allocating an unbounded decoded chunk
before the body cap. Compatibility: servers ignoring `Accept-Encoding: identity`
now fail explicitly. Wildcard/empty/oversized grants are rejected rather than
rewritten or truncated; invalid entries do not echo embedded credentials.
Host grants still span schemes/ports and require the planned service-scoped
replacement.

The installed MCP SDK is 2.3.0. Source review shows fresh discovery validates
resource/issuer relationships and stamped client credentials, and its transport
redirect helpers constrain origins. CaberOS's cached metadata restoration bypassed
those fresh-discovery checks before refresh. The follow-up restores resource,
issuer, and client-binding validation, leaves initialization incomplete on
failure/retry, and clears in-memory tokens without deleting stored credentials.
Bound cross-origin authorization servers remain supported through their PRM
relationship. Legacy unstamped clients retain the SDK's existing behavior.
Authorization URLs are no longer logged by CaberOS's redirect handler.

Written synthetic tests require invalid cached bindings to fail before the
first HTTP request, including a repeated attempt on the same provider. They
also cover bound cross-origin issuers and the SDK's legacy root-slash rule.
They are NOT RUN. This does not constrain metadata-advertised endpoint origins,
private-network destinations, or MCP subprocess authority; S04/S05 remain open.

Static follow-up evidence, observed at `2026-11-05T06:57:48Z`:
macOS 27.0, Python 3.12.11, Ruff 0.16.0. From the repository root:

```sh
./backend/.venv/bin/ruff check --no-cache backend/src/agentos/netpolicy.py backend/src/agentos/api/settings.py backend/src/agentos/sandbox/docker.py backend/tests/test_netpolicy.py backend/tests/test_network_settings.py backend/tests/test_sandbox_docker.py
./backend/.venv/bin/ruff format --check --no-cache backend/src/agentos/netpolicy.py backend/src/agentos/api/settings.py backend/src/agentos/sandbox/docker.py backend/tests/test_netpolicy.py backend/tests/test_network_settings.py backend/tests/test_sandbox_docker.py
./backend/.venv/bin/ruff check --no-cache backend/src/agentos/mcp/oauth.py backend/tests/test_mcp_oauth_security.py
./backend/.venv/bin/ruff format --check --no-cache backend/src/agentos/mcp/oauth.py backend/tests/test_mcp_oauth_security.py
./backend/.venv/bin/python -I -S -c 'import ast, pathlib, sys; paths = sys.argv[1:]; [ast.parse(pathlib.Path(p).read_text(), filename=p) for p in paths]; print(f"Parsed {len(paths)} files without importing target code.")' backend/src/agentos/mcp/oauth.py backend/tests/test_mcp_oauth_security.py
git diff --check
```

All commands exit 0. Formatting reports six and two files respectively; AST
parsing reports two files. Runtime tests executed in this follow-up: zero.
These results do not supersede the earlier isolated-runner blocker.

Docker Desktop installation was proposed for isolated Linux verification;
operator approval is still pending. No download, Homebrew change, elevated
setup, native security-test execution, or live probe was performed. Even with
Docker, native Seatbelt verification still requires an isolated macOS runner.
W7 remains OPEN; browser-wide enforcement, service-scoped audited grants,
MCP process/transport isolation, remaining resource/cleanup guarantees, and
integrated platform evidence are not finished.

## Outbound Request Map

| Path | Before | Now |
|---|---|---|
| `web_fetch` (agent URL) | plain `httpx.get`, redirects followed unchecked | full policy: parse → resolve+check → pinned dial → per-hop revalidation |
| `browser_open` / `browser_act` navigate | raw `Page.navigate` (any scheme/destination) | http(s)+public check before navigate; `about:blank` exempt |
| `web_search` (DDGS fallback) | fixed DuckDuckGo host | unchanged |
| Search services (Tavily/Exa/Brave/Firecrawl Cloud) | fixed API origins, key in `Authorization` header, no redirect follow, `trust_env=False` | unchanged |
| Firecrawl self-hosted | operator URL + `allow_private_network` consent + pinned dial | unchanged, classifier deduplicated onto shared module |
| MCP servers | operator-configured endpoints (explicit authority; local servers are intended) | unchanged — see findings |
| MCP OAuth discovery/refresh | MCP SDK 2.3.0 transport | unchanged — see findings |
| Model/embedding calls | operator-configured providers | unchanged |

## Enforcement Mechanism (`agentos/netpolicy.py`)

- **Classifier** `addr_allowed`: global unicast always allowed; loopback and
  RFC1918/ULA only via explicit exception; link-local, CGNAT, multicast,
  reserved, unspecified, and cloud-metadata addresses (`169.254.169.254`,
  `fd00:ec2::254`) never admitted — including under an exception.
  IPv4-mapped IPv6 literals are unwrapped before classification.
- **URL gate** `validate_fetch_url`: `http`/`https` only, no userinfo, no
  backslashes, bounded length/port. `file:`, `javascript:`, `data:` never
  reach the network or Chrome.
- **Connect-time resolution** `_resolve_checked`: one `getaddrinfo`, *every*
  answer must be permitted (mixed public/private answers fail the name).
  The validated IP is dialed directly with the original `Host` header and
  `sni_hostname` — DNS is checked at the dial target, not trusted from a
  preflight lookup.
- **Redirect loop** `policy_fetch`: `follow_redirects=False`, up to 5 hops,
  each `Location` re-parsed and re-resolved before connecting. Bodies are
  streamed with a 5 MB cap. `trust_env=False` — proxy env vars cannot
  reroute enforcement.
- **Browser navigation** (`cdp.py navigate`): same URL gate + resolution at
  every agent-driven navigation (initial open and `act` navigations).

## Operator Configuration

`web_private_allowlist` — exact hostnames/IP literals granted private-network
access for general fetch+navigation. `PUT /api/settings/network` (bare
hostnames only — URLs/ports/credentials rejected), persisted via
`app-settings.json`, env-pin `AGENTOS_WEB_PRIVATE_ALLOWLIST` wins and locks
the UI. Settings → "Private-network access" exposes the list.
Revocation is deleting the entry; classification returns to default-deny.

## MCP Discovery Findings

- MCP endpoints are **operator-configured explicit authority** — private
  addresses are legitimate there (local stdio/HTTP servers are a supported
  workflow). No blanket ban applied; none is correct.
- OAuth discovery/registration/token calls run inside the MCP SDK 2.3.0
  client (`OAuthClientProvider`). Authorization endpoints come from the
  server's own RFC 9728/8414 metadata; tokens go only to the discovered
  token endpoint inside the flow. The loopback callback is a local
  listener, not egress.
- **Residual (documented, not closed):** a hostile operator-added server
  could advertise malicious authorization-server metadata. Mitigations are
  operator-only server configuration and the OAuth consent step happening
  in the user's own browser — not an SDK-level issuer-consistency
  reimplementation.

## Browser Residual Risks (documented, not claimed covered)

- Chrome resolves DNS itself at request time → a TOCTOU window exists
  between our pre-navigation check and Chrome's lookup (rebinding inside
  the browser is not closed).
- Subresources, frames, WebSockets, downloads, and script-driven
  navigations are **not** destination-checked; the Fetch interception
  domain leash only exists for persistent-profile sessions and only covers
  `Document` requests.
- In-page redirect hops during browsing are not re-validated for
  non-scoped sessions.

## Evidence

- `tests/test_netpolicy.py` — 46 tests: classification matrix
  (public/loopback/private/link-local/CGNAT/multicast/IPv4-mapped/IMDS),
  URL rejection set (schemes, creds, ports, whitespace, backslash),
  mixed-answer DNS, allowlist grant + metadata-address denial under grant,
  redirect follow/re-validate/loop cap, 5 MB body cap, web_fetch-level
  block + landed-URL reporting.
- `tests/test_network_settings.py` — 4 tests: defaults, normalize+persist,
  URL-shaped entry rejection, env-pin 409.
- `tests/test_browser.py` — loopback fixtures granted via the same
  allowlist seam; all prior behavior preserved (`about:blank` nav, domain
  leash, profile scoping).
- `tests/test_search_providers.py`, `test_tools_new.py`,
  `test_capability_effects.py` — no regression (168 tests in touched area).

Acceptance rows: **S01** covered (connection-aware policy tests);
**S03** covered (exact-host exception + revocation = default-deny);
**S02** partially covered — agent-driven navigation enforced, subresource
coverage documented above rather than claimed;
**S04** review findings recorded above — no credential-path changes.
