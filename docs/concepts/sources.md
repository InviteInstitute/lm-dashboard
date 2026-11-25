---
description: Where student activity comes from, Reflecks or a ZANY study, and how the daemon reads each.
---

# Reflecks And ZANY

Each board listens to one source. Reflecks is the classroom default, and a ZANY study is for the
research team. Both carry VEXcode VR's log format, so after the daemon reads them, the rest of the
pipeline treats their events the same.

| | Reflecks (VEXcode VR) | ZANY (class code) |
|---|---|---|
| Where the logs live | the Reflecks production server | ATLAS-invite's log store, a Postgres database on the INVITE server |
| How the daemon reads them | the REST API `GET /api/rabbitmq/vex_logs/`, with a token login | SQL on table `log_record`, as the read-only role `lmdash_reader` |
| Student key | the student ID, lowercased | `zany:<study>:<participant ID>`, lowercased |
| Duplicate key | `vex_log.source_event_id` | `vex_log.zany_seq` |
| Who can see it | anyone with the dashboard | a browser unlocked with the research login |

## Reflecks

The daemon pages through Reflecks with its cursor, as the [write path](write-path.md#polling-production)
explains. `VEX_PROD_API_BASE` sets the server, and `PROD_USERNAME` and `PROD_PASSWORD` the login.

## ZANY

ZANY sends its learner logs to ATLAS-invite (zany.inviteai.org). ATLAS keeps only the records a
participant's consent allows. The dashboard reads ATLAS's store read-only, within about a second of
ATLAS storing a record. It needs `ZANY_LOG_DSN`, and without it the ZANY source is off. On the
INVITE server that setting is in `/etc/lm-dashboard/zany.env`, and compose mounts the host's
Postgres socket read-only so the containers can reach the store.

The daemon polls the store every tick, as it polls Reflecks, and keeps a second cursor named `zany`
at the newest `stored_at` it has seen. Each drain reads again the rows stored in the 5 seconds
before the cursor, because ATLAS stamps a row before its transaction commits, so a row can appear
after a newer one. Rows it already has are skipped by `zany_seq`.

A poll can't see a deleted row, so ATLAS also sends a `zany_forgotten` notification when it deletes
a participant's records, for example when a researcher deletes or resets them. The daemon listens
for it while it sleeps between ticks. When one arrives, it drops everything it made from that
participant and backfills them again from what the store still has. When the daemon starts, it
does the same for every ZANY student, so nothing ATLAS deleted while the daemon was down survives.
The roster, presence, picks and notes stay, since they are the researchers' own.

## The Research Login

ZANY's logs are for the research team, so a browser has to unlock them. The research login is the
same one as ATLAS's research pages. The API signs in to ATLAS with what the person typed, asks
ATLAS whether the account is a researcher, and signs out again. It stores nothing. On success it
sets a signed `zany_unlocked` cookie for 12 hours.

Five wrong tries from one address lock unlocking for ten minutes. A board set to a ZANY study
answers `403 zany_locked` on every route except `/api/source/` and `/api/zany/*` until its browser
is unlocked.

## Switching A Board's Source

**Listening to**, beside the Students heading, sets the board's source with
[`POST /api/source/`](../reference/api.md#post-apisource). The roster is kept per source, so a
board that switches from ZANY back to Reflecks shows its Reflecks students again. On a ZANY board,
an ID you type is a participant ID in that study, and **Track everyone in** adds every participant
with records.
