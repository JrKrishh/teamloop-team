# Hub API v1: events in, the board out

What the connector sends (`connector/teamloop/send.py`) and how a hub answers. Both hubs take the same events and give the
same board shapes; they differ in sign-in. This page's auth is the **self-hosted hub's** (`hub/`). The hosted hub (`cloud/`)
signs people in with accounts, gives each laptop a `tl_` token through `teamloop login`, and has many more endpoints: see
[cloud.md](cloud.md).

## Auth on the self-hosted hub (ccbridge's, unchanged)
1. `POST /v1/join` with `Authorization: Bearer <room token>` and body `{room, display_name, identity_key}`. The first join under a name binds it to that identity key.
2. Every call after that sends `Authorization: Bearer <room token>`, `X-CCBridge-Room` and `X-CCBridge-Session`. A 401 means join again.

`teamloop login <invite>` (ccbridge invite format) stores `{url, room, token, name, identity_key}` in `~/.teamloop/config.json`. The hub sets `member` from the session and ignores the body's value.

The lead's browser uses `POST /v1/board/login {room, token}` instead. It sets an HttpOnly cookie, because EventSource can't send headers.

## POST /v1/events
```json
{"events": [ { ...event... }, ... ]}
```
- **Response:** `200 {"accepted": n, "duplicates": m}`. Any non-2xx means the connector keeps the batch and retries with backoff, starting at 5 s and capped at 5 min.
- **Idempotent on `event.id`.** Retries after a timeout resend the same ids.
- **Limits:** at most 50 events per batch. Suggested body cap: 256 KB.
- **Defence in depth:** return 400 for any event that has a `local` key. The connector never sends one, so a 400 here means a bug.
- **Shape:** 422 for an event the readers can't use (`hub.team.bad_shape`): no 32-hex `id` or lowercase `kind`, a `ts` that isn't text, `facts` or `report` that aren't objects, a `self_report` without `report`, a `pr`/`review`/`check` without `facts`, `facts.cmd` without a `kind`, `facts.usage` counts that aren't whole numbers, or `report.done`/`next` that aren't lists of text. 413 for an event over 8 KB.

## Event
| field | always | notes |
|---|---|---|
| `v` | yes | 1 |
| `id` | yes | uuid hex; dedupe key |
| `ts` | yes | UTC with ms, `2026-10-13T10:31:02.123Z` |
| `tool` | yes | `claude_code`, `codex`, `mcp` (agent self-reports), `cli` (`teamloop task`); later `cursor` |
| `session` | | the tool's session id; `null` for `mcp`/`cli` (join those by member + time) |
| `kind` | yes | see below |
| `member` | yes | added by the connector from its config |
| `repo`, `branch`, `task` | | `task` is like `T-14`, resolved from `$TEAMLOOP_TASK`, then `git config teamloop.task`, then the branch name |
| `facts` | yes | structured only (below) |
| `report` | | only on `self_report` / `blocked`: text the agent wrote for the team, redacted, at most 5 × 160 chars |
| `summary`, `status`, `summary_model` | | only on `turn_end` / `subagent_end`; `status` ∈ `progress, blocked, done, question` |
| `summary_error` | | the summarizer failed; the event is still sent |

## Kinds
| kind | facts / report |
|---|---|
| `session_start` | `{source}`: `startup`, `resume`, `clear` |
| `tool` | `{tool, ok, ms?, file?, files?, exit?, cmd?: {kind: test/git/install/build/other, ok, passed?, failed?}}`. `ok` can be **null**: Codex reports no exit status for shell commands, so only test counts decide those |
| `turn_end`, `subagent_end` | `{}`, plus `summary`/`status` |
| `waiting_input` | `{type}`: the agent is waiting on its human |
| `session_end` | `{reason}`. **Orphans happen:** `claude mcp …` CLI calls fire SessionEnd with no start, so ignore an end for an unknown session. |
| `task_start` | `{title?}` |
| `self_report` | `report: {percent, done[], doing, next[]}`, labelled "agent's own estimate" on the board |
| `blocked` | `report: {reason, needs: person/decision/access/info}` |

## Implemented in hub/team.py (13 Oct)
- `POST /v1/events`: idempotent; refuses `local` (400); peer text goes through ccbridge `sanitize()`.
- `GET /v1/board` (cookie or session): tasks with title, members, tools, status (blocked if the last `blocked` is newer than the last progress), the latest Agent S snapshot, and recent lines.
- `POST /v1/ask {question}`: Agent S Q&A with citations, or 503 when the model is down.
- **Agent S worker:** re-estimates a task once its events go quiet for `HUB_DEBOUNCE` seconds (default 30); after a failure it waits 60 s.

## Roles (13 Oct)
| Role | How | Can |
|---|---|---|
| lead | board sign-in with the room's lead key (`HUB_LEAD_KEYS`), or with the room token when no lead key is set | everything a member can, plus `DELETE /v1/members/{name}` (revoke: the identity key stops working, sessions end, events are refused, history stays), `POST /v1/members/{name}/restore`, `GET /v1/settings` |
| member | board sign-in with the room token, or a connector session | board, `/v1/tasks/{task}`, `/v1/team`, stream, ask, digest. Teammates see each other's work by design |
| viewer | public demo room (`HUB_DEMO_ROOM`) | read only |

`GET /v1/me` returns `{room, role, name, demo}`. The role is signed into the cookie (`room|role|expires|hmac`), so a forged role fails verification.

