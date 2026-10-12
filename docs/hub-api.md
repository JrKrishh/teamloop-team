# Hub API v1 (draft)

Drafted by Yang's agent from what the connector sends today. **Sourabh owns the hub, so change anything.** The connector side is `connector/teamloop/send.py`.

## Auth
`Authorization: Bearer <member token>`. The token is issued when a member joins, ccbridge style (team token + identity key → member). `teamloop login <invite>` stores `{hub, token, member}` in `~/.teamloop/config.json`.

## POST /v1/events
```json
{"events": [ { ...event... }, ... ]}
```
- **Response:** `200 {"accepted": n, "duplicates": m}`. Any non-2xx means the connector keeps the batch and retries with backoff, starting at 5 s and capped at 5 min.
- **Idempotent on `event.id`.** Retries after a timeout resend the same ids.
- **Limits:** at most 50 events per batch. Suggested body cap: 256 KB.
- **Defence in depth:** return 400 for any event that has a `local` key. The connector never sends one, so a 400 here means a bug.

## Event
| field | always | notes |
|---|---|---|
| `v` | yes | 1 |
| `id` | yes | uuid hex; dedupe key |
| `ts` | yes | UTC with ms, `2026-10-13T10:31:02.123Z` |
| `tool` | yes | `claude_code`, `mcp` (agent self-reports), `cli` (`teamloop task`); later `codex`, `cursor` |
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
| `tool` | `{tool, ok, ms, file?, exit?, cmd?: {kind: test/git/install/build/other, ok, passed?, failed?}}` |
| `turn_end`, `subagent_end` | `{}`, plus `summary`/`status` |
| `waiting_input` | `{type}`: the agent is waiting on its human |
| `session_end` | `{reason}`. **Orphans happen:** `claude mcp …` CLI calls fire SessionEnd with no start, so ignore an end for an unknown session. |
| `task_start` | `{title?}` |
| `self_report` | `report: {percent, done[], doing, next[]}`, labelled "agent's own estimate" on the board |
| `blocked` | `report: {reason, needs: person/decision/access/info}` |

## Next (hub side)
- `GET /v1/stream`: SSE for the board.
- `GET /v1/board`: snapshot of teams, tasks, sessions and progress.
- **Session liveness:** a session is active if an event arrived in the last 5 min, and waiting if its last event is `waiting_input`.
