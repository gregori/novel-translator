When the user invokes AI-DLC, read and follow
`.aidlc/aidlc-rules/aws-aidlc-rules/core-workflow.md` to start the workflow.

Project requirements and product scope are defined in `REQUIREMENTS.md`.
Treat `REQUIREMENTS.md` as the authoritative source for product requirements:
baseline CLI v1 scope, translation/publication separation, technical
constraints, and the translation bible model.

`WEB_VERSION_PLAN.md` governs only post-v1 evolution — the web interface and
its implementation phases. It supersedes `REQUIREMENTS.md` solely on the
historical v1 exclusion of a web interface; any other conflict resolves in
favor of `REQUIREMENTS.md`. Follow `WEB_VERSION_PLAN.md` to implement new
web-era features.

This file is agent-facing instruction and stays in English; product
documentation stays in Portuguese, as `REQUIREMENTS.md` requires.

**Always** be brief and use less tokens on communication.

Python code **must** pass the quality gates listed in
"Mandatory review after work".

## Lessons learned from phases 1–4

### Phase 1 — Application layer and immutable artifacts

- Keep Typer, FastAPI, HTML, filesystem details, and database implementations
  outside application use cases. Inputs and results must be typed.
- Define persistence ports in the application layer, domain models in
  `domain`, and concrete adapters in `infrastructure`; never create an
  application/infrastructure import cycle.
- Resolve and verify revision parents inside the application. Callers may
  select an artifact by ID, but must never provide trusted hashes or assembled
  provenance objects.
- Treat source, generated drafts, revisions, approvals, and exports as
  hash-addressed facts. Verify the persisted bytes before using an artifact.
- Normalize text line endings to `\n` at the application boundary before
  hashing or persistence. Browser multipart forms may submit CRLF, while
  filesystem reads use universal newline handling.
- Operations spanning SQLite and the workspace must be retry-safe. Use a
  deterministic artifact identity, detect a prior successful write, and finish
  incomplete cleanup without creating duplicates.
- Before changing an exported symbol or constructor, inspect all references
  and migrate every CLI, web, and test caller in one clean cutover.

### Phase 2 — Catalog and friendly resolution

- Never select a run or source silently when multiple valid candidates exist.
  Present stable ordinal choices and require an explicit selection.
- Build dashboard/catalog projections from one run index. Avoid re-indexing the
  complete workspace once per novel or chapter.
- Aggregate chapter state must include active working copies, but aggregate
  state must never stand in for an artifact-specific fact such as approval.
- Corrupt, incomplete, foreign, orphaned, or editorially unreadable entries
  must degrade independently and remain reported as typed issues.
- Keep complete run IDs and hashes out of the everyday flow, while exposing
  them in an explicit technical-details surface for audit work.

### Phase 3 — Web review room and concurrency

- The server is authoritative across devices. Every save request must carry
  both `working_copy_id` and the optimistic `version`; discard and
  revision-freeze requests carry `working_copy_id` and are rejected on
  identity mismatch alone.
- A stale working-copy identity is a conflict even when its version matches a
  replacement copy. Never resolve active state by run ID alone.
- On `409`, preserve both contents and suspend autosave until the reviewer
  explicitly chooses a version. Never adopt the server version implicitly.
- Distinguish an HTTP rejection from a network failure. “Offline” is reserved
  for transport errors; rejected or stale saves must tell the reviewer to
  reload and must stop repeated autosaves.
- Read source, draft, revisions, metadata, and working copy independently. A
  missing source must not hide a valid draft.
- Scope local recovery data by working-copy identity and clear it after a
  successful save, discard, or revision freeze.
- Blocking workspace and SQLite work belongs in synchronous FastAPI routes so
  Starlette executes it in its thread pool; do not block the async event loop.
- Alembic migrations for in-memory SQLite must use the same live engine
  connection as application sessions. Ignore SQLite database, WAL, and SHM
  runtime artifacts.
- Keep routes cohesive and small, presentation models outside orchestration,
  Markdown HTML-disabled, and technical timestamps timezone-labelled.
- Preserve bytes when round-tripping text through HTML: parsers drop a newline
  immediately after a `pre` or `textarea` start tag, so emit a guard newline
  there or restore the text from an attribute value.
- Regression tests must assert the rendered behavior, not unrelated page
  prefixes or implementation text. Exercise real multipart forms, CRLF,
  multiple runs, stale tabs, partial cross-store failures, and exact artifact
  approvals.

### Phase 4 — Remote operation on k3s

- Single replica plus `strategy: Recreate` wherever SQLite/filelocks back
  the app; RollingUpdate silently doubles writers on every rollout.
- Remote shell steps need `set -o pipefail`; a trailing cleanup command
  masks mid-script failures as success.
- Single-quote every `--from-literal` carrying secrets; double quotes let
  the remote bash expand `$` inside hashes and tokens.
- `kubectl run --overrides` merge-patches: the override container must
  reuse the generated name with explicit `command`/`stdin`, or the
  payload never runs and exits 0. Prefer sleeper + `cp` + `exec` for
  PVC transfers; guard scale-to-zero scripts with `trap EXIT` restore.
- Render one declarative rollout (image tag in the manifest), never
  apply `:latest` plus imperative `set image`.
- `iptables` is blind to native nftables on k3s nodes; `nft list ruleset`
  is the source of truth for port delivery.
- cert-manager HTTP-01 self-check fails on NAT hairpin; fix with a
  CoreDNS NodeHosts entry to Traefik's ClusterIP (in-cluster only).
- Traefik basic-auth values must be `user:hash` lines; a bare hash drops
  the whole router as 404 — debug Traefik logs, not the app.
- Runbooks must say where each command runs (node vs local machine).
- Template regression tests parse attributes; substring assertions on
  `hidden` fail for unrelated reasons.

### Phase 5 — Queue and session gate

- Queue status changes across processes must be guarded `UPDATE`s
  (`WHERE status IN (...)`, `rowcount` checked): check-then-act over
  two connections silently loses cancels and resurrects settled jobs.
- Two containers migrating one SQLite file need a cross-process
  filelock around Alembic, or both `CREATE TABLE` at pod start.
- Behind a TLS-terminating proxy, trust proxy headers
  (`forwarded_allow_ips`) or `Secure` cookies and IP throttles
  silently break (peer is always the proxy).
- Listings must not materialize large payload columns: defer
  `source_text`-sized fields and project summaries for polls/scans.

## Self-learning

- After each defect or review finding, extract the reusable invariant, add a
  behavior-level regression when the bug is plausibly repeatable, and update
  this file when the lesson applies beyond one call site. Green tests are not
  proof that an untested browser, persistence, concurrency, or failure boundary
  is correct.

## Mandatory review after work

- Every completed phase or task must be followed by an independent,
  adversarial review before it is declared done.
- Review the requested behavior, all changed call sites, architecture,
  cohesion/coupling, file size, failure paths, concurrency, integrity,
  security, mobile behavior when applicable, and test quality.
- Resolve all review findings that affect correctness or acceptance criteria,
  then rerun the relevant scenario and the full required quality gates.
- When the change touches the web editor, verify mobile and concurrent-tab
  flows in a real browser before declaring it done.
- Python changes are complete only after `ruff check`, `ruff format --check`,
  `pytest`, and `pyright` pass.
