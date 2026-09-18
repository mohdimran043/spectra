# Product

<!-- impeccable:product-schema 1 -->

> Interview substitution: this session is non-interactive (no user answer channel and no
> structured-question tool reachable from this agent), so the record below is derived from the
> explicit written brief, `docs/api.md`, `master-prompt.txt` sections 37–39, and the frozen
> Pydantic contracts in `packages/schemas/spectra_schemas/`. Every line that is an inference
> rather than a stated fact is marked **[assumed]**.

## Platform

web

## Stack

Next.js 14.2 App Router, TypeScript (strict), Tailwind CSS, TanStack Query, Zod, Radix UI
primitives, Recharts, `react-force-graph-2d`. Node 18.17.0 / npm 9.6.7, no pnpm.
`output: 'standalone'` is required by the Docker build. Stated in the brief, not chosen.

## Users

Enterprise investigators and intelligence analysts — fraud, incident response, trust & safety,
compliance. They arrive with a specific question about a specific entity (a transaction, an
incident, a customer) and must leave with an answer they can defend to someone else: an auditor,
a regulator, a customer, a court.

Three roles exist in the product and are switched via the `X-Spectra-Role` header:
`admin` (may manage sources, agents and models), `analyst` (may search, investigate, upload,
run SQL, view autopsy, export), `viewer` (may search and view autopsy only).

## Product Purpose

SPECTRA answers investigative questions across documents, images, video, audio, databases and a
knowledge graph at once, and shows its work. Success is not "the model produced fluent text" —
success is that every asserted fact carries an openable citation, that competing explanations
were tested rather than assumed, that contradictions were surfaced rather than smoothed over,
and that the system abstains out loud when the evidence does not support an answer.

## Positioning

Adversarial self-falsification is the mechanism a neighbouring RAG product cannot truthfully copy:
SPECTRA generates competing hypotheses, actively searches for the evidence that would *disprove*
each one (`disproof_probe`, `disproof_searched`), scores evidence on relevance *and* source
reliability with a stated reason, computes evidence diversity so three paragraphs of one PDF
never outrank a database record plus a PDF plus a video, and publishes a full Search Autopsy of
what it considered, used and rejected. When the evidence is thin it returns
`status: "insufficient_evidence"` instead of an answer.

## Operating Context

- The work happens at a desk, on a large display, usually alongside the enterprise application
  the records actually live in (deep links open `http://localhost:3001`). Sessions are long and
  the operator is comparing, not browsing.
- An investigation is a live process, not a request/response: `POST /api/investigations` returns
  a `stream_url` and the workspace subscribes to SSE, receiving `trace`, `hypotheses`,
  `evidence`, `status`, `complete` and `error` events with 15-second heartbeats and
  `Last-Event-ID` reconnection.
- Findings get re-opened. Cases persist, investigations can be continued, and a report can be
  exported as JSON or Markdown.
- The local deployment runs on a usable RTX 4090 (resolved 2026-09-18), so the GPU path is the
  normal path and degradation is the exception it was designed to be. Degradation states must still
  be first-class in the UI: the Compose stack has no GPU access yet (no NVIDIA Container Toolkit),
  and roles degrade for reasons unrelated to hardware — a disabled agent, an unreachable source, an
  exhausted budget.
- Media is seeked, not merely listed: a video result must play *from* `start_seconds`, an audio
  result from its segment start, a document result must open the exact rendered page.

## Capabilities and Constraints

Confirmed capabilities, from `docs/api.md` and the schema package:

- Unified and modality-scoped search (`document`, `image`, `video`, `audio`), image-to-anything
  search by upload or `image_asset_id`, and NL→SQL database query that always returns the exact
  generated SQL and params for inspection.
- Investigations with a live agent trace, hypotheses, an evidence ledger, a contradiction list,
  a timeline, claims, application deep links, an explanation of source selection, and a
  post-hoc Search Autopsy.
- Entity resolution with a full candidate list, winning method and explanation; a knowledge graph
  view; a source registry with health checks and sync; a model runtime dashboard with GPU
  telemetry and load/unload events; runtime agent enable/disable with no restart; six guided
  demo scenarios; an evaluation harness.

Constraints that are product truth, not preference:

- **The API contract is frozen.** `docs/api.md` plus `packages/schemas/spectra_schemas` are
  authoritative. Nothing may be invented at the boundary.
- **Action summaries only.** The trace exposes what an agent *did* (`input_summary`,
  `output_summary`, `latency_ms`, `status`). Model chain-of-thought is forbidden in the UI.
- **No fabricated data in the shipped app.** If the API is down, say so. Fixtures exist for
  tests only and are never imported by application code.
- Search snippets arrive with matches marked `«…»` and must be rendered as highlights.
- Confidence is both a label (`high | medium | low | insufficient`) and a number; both are shown.
- Reliability always carries a `reliability_reason`; showing the score without the reason is a
  contract failure.
- Errors arrive as `{error, reason, request_id, detail}` and must reach the user as the `reason`
  string, never as a generic failure.
- The frontend is the only consumer of `X-Spectra-Role`; changing it changes what the API
  returns, so the role switcher is a real control, not a cosmetic one.

Undecided product facts: authentication is a development header shim today and is explicitly
designed to be replaced by OAuth/OIDC; the frontend must not build affordances that assume the
shim is permanent.

## Brand Commitments

- Name: **SPECTRA**. Tagline in the Home spec: "AI Investigation Intelligence".
- The brief binds the register explicitly: *enterprise intelligence + investigation console +
  modern AI workspace*, and bans generic SaaS card grids, excessive gradients, childish AI
  visuals, oversized rounded rectangles, template dashboards, decorative charts and excessive
  animation.
- Dark *and* light must both work. Design tokens live on `:root` with a dark-mode override.

## Evidence on Hand

- `docs/api.md` — the frozen API contract (241 lines).
- `packages/schemas/spectra_schemas/*.py` — the authoritative Pydantic models the API serialises.
- `master-prompt.txt` §37–39 — the required information architecture and the Home/Search/
  Investigation/Trace layouts, quoted literally in the brief.
- **No backend is running and `services/api/spectra_api/routers/` is empty.** There is no real
  search corpus, no screenshot, no logo file and no brand asset of any kind. Nothing about
  latency, accuracy, customers or benchmarks may be fabricated to fill that gap.

## Product Principles

1. **Every fact is openable.** A claim the operator cannot click through to its exact page,
   frame, segment or row is not a finding, it is a rumour.
2. **Doubt is content, not failure.** Contradictions, disproof probes, rejected evidence and
   abstention get first-class presentation — never a collapsed footnote.
3. **Show the machinery.** Score breakdowns, generated SQL, source selection reasons, per-stage
   latency and the agent trace are part of the product, not developer debug output.
4. **Degradation is reported honestly.** No GPU, a disabled agent, an unreachable source and a
   down API each render as a specific, informative state that names the cause and the
   alternatives.
5. **Density is a feature.** This is a desk instrument. Fitting more true, scannable information
   into one screen beats whitespace for its own sake.

## Accessibility & Inclusion

WCAG AA contrast is required. Every interactive element must be reachable by keyboard with a
visible focus ring; semantic landmarks throughout; streaming trace updates announced via
`aria-live`; focus managed and trapped in the Evidence Explorer modal; full keyboard operation of
search tabs, the graph filters and the agent toggles.
