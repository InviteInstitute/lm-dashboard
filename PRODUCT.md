# Learner Modeling Dashboard

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Researchers observing a room of students coding in VEX. They need to identify
students who merit attention, inspect their activity, select students for
interviews, and record observations during a session.

## Product Purpose

Show a room's coding activity on one live board, so researchers can see who to
watch and keep a record of the session. A researcher goes from an alert to the
activity behind it, then to a note or an interview, and exports the session for
later research.

## Positioning

The dashboard mirrors Reflecks/VEX activity and works out signals from the changes
between code runs and from session episodes. The triggers are five fixed rules over
what a student did. A researcher decides what an alert means.

## Operating Context

- Each researcher's browser keeps its own board, with no login (a Cloudflare
  Turnstile check keeps bots off the API). Boards have separate rosters, notes,
  picks, dismissals, and controls, backed by a shared student mirror.
- Track students by ID, observe their activity, mark presence and interview picks,
  inspect student details, and attach notes to students or alerts.
- The live board updates through a server-sent event stream with polling fallback.
  Production polling is gated by board activity and can be paused between sessions.
- Export the board's research records and tracked students' data as CSV snapshots
  in a ZIP file. Reset prepares the board for a fresh research session.
- The existing application uses React/Vite, a FastAPI API, PostgreSQL, and an
  ingestion daemon, with Docker Compose for local and hosted operation.

## Capabilities and Constraints

- Student cards expose run history, code-change distances, episode timelines,
  activity counts, status, presence, and interview selection.
- Preserve the documented trigger terminology: Wheel-spinning, Resilience,
  Inactive, Explorer, and Step-by-Step. Trigger types can be enabled or disabled.
  The numeric thresholds can change.
- Student details include a readable program, a playground prompt, expanded
  timelines, trigger history, and notes. The prompt is context for an LLM. The
  activity rules don't use one.
- Identity-switch notifications expose handle casing and class-code changes that
  may affect interpretation of activity.
- Production is a read-only data source. Researcher actions write to the local
  dashboard store and must not write back to Reflecks.
- Board isolation must be preserved. Reset clears the board's research session
  inputs and dismissals while retaining roster and presence and leaving the shared
  student mirror intact. A backup comes first.
- Researcher inputs must not fail silently. Preserve visible failed-save feedback,
  retries, and recoverable input through the outbox.
- Protect access to the dashboard and research data. Do not commit student
  telemetry, exports, or credentials to the repository.

## Brand Commitments

The product name is Learner Modeling Dashboard, associated with the INVITE
Institute. Existing identity assets include `frontend/public/logo_INVITE.png` and
`docs/images/logo.png`. Preserve factual institutional attribution.

## Evidence on Hand

- `README.md`: product overview and operation.
- `docs/guides/using-the-dashboard.md`: researcher workflows and terminology.
- `docs/concepts/architecture.md`: system architecture, source-data boundaries, and
  isolation.
- `frontend/src/CohortDashboard.jsx` and `app/main.py`: the interface and behavior
  to trust when the docs differ.

## Product Principles

1. Ground interpretations in inspectable student activity and understandable rules.
2. Support timely researcher decisions without replacing researcher judgment.
3. Treat researcher observations as valuable records: save visibly and recover
   failed inputs.
4. Preserve board isolation and the read-only boundary around production data.
5. Keep operation straightforward and session data available for later analysis.

## Open Decisions

There is no accessibility standard, second audience or outcome claim yet. Agree
on one before work depends on it.
