# Learner Modeling Dashboard

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Researchers observing a room of students coding in VEX. They need to identify
students who merit attention, inspect their activity, select students for
interviews, and record observations during a session.

## Product Purpose

Make ongoing student coding activity understandable on one live board so
researchers can decide where to direct their attention and retain a useful session
record. Success means moving from an activity signal to the underlying evidence,
an observation or interview, and an export for subsequent research.

## Positioning

The dashboard mirrors Reflecks/VEX activity and derives interpretable signals from
changes between code runs and session episodes. Its five activity triggers are
rules over observed activity, not a black-box assessment of a student's ability or
understanding. Researcher judgment remains central to interpreting those signals.

## Operating Context

- Researchers sign in and maintain a browser-specific board. Boards have separate
  rosters, notes, picks, dismissals, and controls, backed by a shared student mirror.
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
  Numeric thresholds are implementation settings, not immutable product promises.
- Student details include a readable program, a playground prompt, expanded
  timelines, trigger history, and notes. A prompt is context for an LLM, not evidence
  that the dashboard's activity rules use an LLM.
- Identity-switch notifications expose handle casing and class-code changes that
  may affect interpretation of activity.
- Production is a read-only data source. Researcher actions write to the local
  dashboard store and must not write back to Reflecks.
- Board isolation must be preserved. Reset clears the board's research session
  inputs and dismissals while retaining roster and presence and leaving the shared
  student mirror intact; a backup precedes the reset.
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
- `docs/DESIGN.md`: system architecture, source-data boundaries, and isolation.
  This is an engineering document, not a visual design specification.
- `frontend/src/CohortDashboard.jsx` and `app/main.py`: incumbent interface and
  behavior when documentation details differ.
- No outcome benchmarks or testimonials were confirmed during initialization;
  future work must not invent them.

## Product Principles

1. Ground interpretations in inspectable student activity and understandable rules.
2. Support timely researcher decisions without replacing researcher judgment.
3. Treat researcher observations as valuable records: save visibly and recover
   failed inputs.
4. Preserve board isolation and the read-only boundary around production data.
5. Keep operation straightforward and session data available for later analysis.

## Open Decisions

No product-specific accessibility standard, additional audience, or new outcome
claim was established during initialization. Confirm these if future work depends
on them.
