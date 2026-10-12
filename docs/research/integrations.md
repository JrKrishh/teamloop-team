# TeamLoop integration surfaces

Researched 12 Oct 2026 from official docs and source repos. Field names are quoted from sources; **unverified** = not confirmed from a primary source.

Needs key: **(a)** session start/end, **(b)** tool calls / edits / shell / tests, **(c)** summary, **(d)** agent self-reports via MCP, **(e)** commit → task id.

---

## 1. Claude Code

**Hooks.** Config lives under `hooks → <Event> → [{matcher, hooks:[handler]}]` in `~/.claude/settings.json`, `.claude/settings.json` or `.claude/settings.local.json`, plus plugin `hooks/hooks.json`. Handler types are `command`, `http` (the JSON input is POSTed as the request body), `mcp_tool`, `prompt` and `agent`. Default timeout is 600 s for command, http and mcp_tool. `SessionEnd` gets a total budget of only 1.5 s, which you can raise with a per-hook `timeout` or with `CLAUDE_CODE_SESSIONEND_HOOKS_TIMEOUT_MS`. Non-2xx is a non-blocking error.

Every event receives these common fields: `session_id`, `prompt_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`. Subagent events also carry `agent_id` and `agent_type`.

| Event | Event-specific fields | TeamLoop use |
|---|---|---|
| `SessionStart` | `source` (`startup`/`resume`/`clear`/`compact`/`fork`), `model`, `session_title` | (a) open session |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response`, `tool_use_id`, `duration_ms` | (b) Edits: `Write`/`Edit` `tool_input.file_path`. Shell: `Bash` `tool_input.command`. Test runs: TeamLoop classifies the command |
| `PostToolUseFailure` | `tool_name`, `tool_input`, `error`, `is_interrupt` | (b) failed commands/tests |
| `Notification` | `message`, `notification_type`, `title` | "waiting on human" signal |
| `Stop` | `stop_hook_active`, `last_assistant_message` | (c) turn summary. The docs say to use this field rather than read the transcript |
| `SubagentStop` | `agent_transcript_path`, `last_assistant_message` | (c) |
| `PostCompact` | `trigger`, `compact_summary` | (c) model-written summary at no extra cost |
| `SessionEnd` | `reason` (`clear`/`resume`/`logout`/`prompt_input_exit`/`other`) | (a) close session |

33 events exist in total; the rest aren't needed for v1.

```json
{ "hooks": {
  "SessionStart": [{ "hooks": [{ "type": "http", "url": "https://<teamloop-host>/hooks/claude", "timeout": 5,
      "headers": { "Authorization": "Bearer $TEAMLOOP_TOKEN" }, "allowedEnvVars": ["TEAMLOOP_TOKEN"] }]}],
  "PostToolUse":  [{ "matcher": "Write|Edit|Bash", "hooks": [ /* same handler */ ]}],
  "Stop":         [{ "hooks": [ /* same */ ]}],
  "SessionEnd":   [{ "hooks": [ /* same */ ]}]
}}
```

**MCP:** `stdio`/`http` (SSE deprecated). Shared config in `.mcp.json` (committed) or `~/.claude.json`; `${VAR}` expands in `url`/`headers`.

```json
{ "mcpServers": { "teamloop": { "type": "http", "url": "https://<teamloop-host>/mcp",
  "headers": { "Authorization": "Bearer ${TEAMLOOP_TOKEN}" } } } }
```

An `mcp_tool` hook (`server`, `tool`, `input` with `${tool_input.file_path}` templating) can call TeamLoop's MCP tool deterministically, with no model involvement.

**Transcripts** live at `~/.claude/projects/<project>/<session-id>.jsonl`. They are kept for 30 days by default (`cleanupPeriodDays`). The docs say the format is internal and changes between versions, so **don't parse it**.

**OpenTelemetry.** Set `CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_LOGS_EXPORTER=otlp`, `OTEL_EXPORTER_OTLP_PROTOCOL`, `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`. Event `claude_code.tool_result` (`tool_name`, `success`, `duration_ms`); metrics `claude_code.commit.count`, `claude_code.pull_request.count`.

---

## 2. OpenAI Codex (CLI + IDE extension)

**Hooks** (on by default). 12 events: `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`.

Hooks can live in `~/.codex/hooks.json`, `~/.codex/config.toml`, `<repo>/.codex/hooks.json` or `<repo>/.codex/config.toml`. Handler types are `command` and `mcp_tool` (`server`, `tool`, `input`). `prompt` and `agent` handlers are parsed but skipped. **There is no `http` handler.** Default timeout is 600 s; `SessionEnd` and `Interrupt` default to 1 s, with a maximum of 3 s. Non-managed hooks need user trust via `/hooks` (hash-bound).

Common fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `model`. Turn-scoped events also carry `turn_id`.

| Event | Event-specific fields | TeamLoop use |
|---|---|---|
| `SessionStart` | `source` (`startup`/`resume`/`clear`/`compact`), `permission_mode` | (a) |
| `PostToolUse` | `tool_name`, `tool_use_id`, `tool_input`, `tool_response` | (b). The docs use matcher `^Bash$`; the per-tool `tool_input` keys are **unverified** |
| `Stop` | `stop_hook_active`, `last_assistant_message` | (c) |
| `SessionEnd` | `reason` (currently always `other`) | (a) |

```toml
[[hooks.Stop]]
[[hooks.Stop.hooks]]
type = "command"
command = "teamloop-hook codex"
timeout = 10
```

**Legacy `notify`.** Configure it as `notify = ["teamloop-hook", "codex-notify"]`. Codex appends a single JSON argument whose fields are `type` = `agent-turn-complete`, `thread-id`, `turn-id`, `cwd`, `client` (optional), `input-messages` and `last-assistant-message`. The source marks `notify` as legacy and slated for removal, so use `Stop` instead.

**MCP** (stdio + Streamable HTTP; config shared by CLI, IDE extension and desktop app; project `.codex/config.toml` loads only if trusted):

```toml
[mcp_servers.teamloop]
url = "https://<teamloop-host>/mcp"
bearer_token_env_var = "TEAMLOOP_TOKEN"
```

**Rollouts** are written to `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<timestamp>-<thread_id>.jsonl` (`CODEX_HOME` defaults to `~/.codex`). Each line has the shape `{timestamp, type, payload}`, with `type` set to `session_meta`, `response_item`, `turn_context`, `event_msg`, `compacted`, and others. The source also has a `.zst` compression path for rollouts.

**OpenTelemetry.** Use `[otel] exporter = { otlp-http = { endpoint, protocol, headers } }` or `otlp-grpc`, plus `log_user_prompt` (default false). Events are `codex.conversation_starts`, `codex.user_prompt`, `codex.tool_decision`, `codex.tool_result` and `codex.api_request`. Attribute names are **unverified**.

---

## 3. Cursor

**Hooks** are configured in `<project>/.cursor/hooks.json` or `~/.cursor/hooks.json`, with Enterprise and Team levels above those. The file shape is `{"version": 1, "hooks": {"<event>": [{"command", "timeout", "matcher"}]}}`. The default timeout is **unverified**.

Common fields: `conversation_id`, `generation_id`, `model`, `hook_event_name`, `cursor_version`, `workspace_roots`, `user_email`, `transcript_path`.

| Event | Event-specific fields | TeamLoop use |
|---|---|---|
| `sessionStart` | `session_id`, `is_background_agent`, `composer_mode` | (a) |
| `sessionEnd` | `session_id`, `reason`, `duration_ms`, `final_status`, `error_message` | (a) |
| `afterFileEdit` | `file_path`, `edits[]` (`old_string`, `new_string`) | (b) edits |
| `afterShellExecution` | `command`, `output`, `duration`, `sandbox` | (b) shell/tests |
| `postToolUse` | `tool_name`, `tool_input`, `tool_output`, `tool_use_id`, `duration` | (b) |
| `afterAgentResponse` | `text` | (c) |
| `subagentStop` | `summary`, `modified_files`, `tool_call_count` | (c) |

CLI (`agent`) hook coverage **unverified**; forum reports say shell hooks only.

**MCP** config lives in `.cursor/mcp.json` or `~/.cursor/mcp.json` under `mcpServers` → `{url, headers}`, with `${env:NAME}` interpolation. The CLI uses the same config (confirmed in the docs).

**Rules.** `.cursor/rules/*.mdc` files take frontmatter `description`, `globs` and `alwaysApply`. `AGENTS.md` is also supported. Use these to tell the agent to call `report_progress`.

**Cloud Agents API** (`https://api.cursor.com`, v1 beta): `POST /v1/agents`, `GET /v1/agents/{id}/runs/{runId}` (`status`, `result`). Webhooks exist only on v0: `statusChange` on `ERROR`/`FINISHED`, signed `X-Webhook-Signature: sha256=<hex>`, payload `id`, `status`, `target.branchName`, `target.prUrl`, `summary`. Plan requirements **unverified**.

---

## 4. Gemini CLI (brief)

**Hooks** go under `"hooks"` in `.gemini/settings.json` or `~/.gemini/settings.json`. `timeout` is in ms, default 60000. Events are `SessionStart`, `SessionEnd`, `BeforeAgent`, `AfterAgent`, `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `BeforeTool`, `AfterTool`, `PreCompress` and `Notification`.

Common fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`. Event-specific fields:
- `AfterTool`: `tool_name`, `tool_input`, `tool_response`
- `AfterAgent`: `prompt`, `prompt_response`
- `SessionEnd`: `reason`

**MCP** goes under `mcpServers` in the same settings file. `httpUrl` means Streamable HTTP and `url` means SSE.

**Telemetry:** `telemetry.enabled`, `telemetry.otlpEndpoint`; events `gemini_cli.tool_call`, `gemini_cli.file_operation`.

---

## 5. Git: tagging commits with a task id

Use **`prepare-commit-msg`**. Git does not suppress it with `--no-verify`, whereas `commit-msg` can be bypassed. Its arguments are the message file, the source (`message`/`template`/`merge`/`squash`/`commit`) and a SHA.

```sh
#!/bin/sh
# .githooks/prepare-commit-msg
case "$2" in merge|squash) exit 0;; esac
TASK="${TEAMLOOP_TASK:-$(git config --get teamloop.task)}"
[ -z "$TASK" ] && TASK=$(git rev-parse --abbrev-ref HEAD | grep -oE '[A-Z]+-[0-9]+' | head -1)
[ -n "$TASK" ] && git interpret-trailers --in-place --if-exists=doNothing \
  --trailer "TeamLoop-Task: $TASK" "$1"
exit 0
```

- **Install:** `git config core.hooksPath .githooks`. This replaces `.git/hooks` and will conflict with Entire/husky, so chain into them instead.
- **Manual tagging:** `git commit --trailer "TeamLoop-Task: T-12"` (confirmed in Git 2.50).
- **Reading it back:** `git log --format='%h %(trailers:key=TeamLoop-Task,valueonly)'`. On the server, parse the `push` payload's `commits[].message`.

**Entire.** Entire adds the trailer `Entire-Checkpoint: <id>`. The id is either a legacy 12-hex value or a 26-char ULID. It links to metadata stored on the `entire/checkpoints/v1` branch, which is pushed with `git push`. The source comment says the trailer survives amend and rebase. Entire also defines `Entire-Session` and `Entire-Agent`.

The CLI has handlers for `prepare-commit-msg`, `commit-msg`, `post-commit`, `post-rewrite` and `pre-push`. Which of these `entire enable` actually installs is **unverified**; the docs only name `post-commit`. TeamLoop should append its own trailer and never rewrite foreign ones.

---

## 6. GitHub

**Recommendation: a GitHub App.**
- One auto-created webhook covers every installed repo; repo webhooks need admin rights per repo and cap at 20 per event.
- Repo/org webhooks get only `completed` for `check_suite` and `created`/`completed` for `check_run`.
- Installation tokens: 5,000 req/h, +50 per repo over 20 and per user over 20, max 12,500.
- Pricing: no fee found in docs (**unverified**).

| Event | App permission (read) | Actions | Fields used | TeamLoop use |
|---|---|---|---|---|
| `pull_request` | Pull requests | `opened`, `synchronize`, `reopened`, `ready_for_review`, `closed` | `number`, `state`, `draft`, `merged`, `merged_at`, `head.ref`, `head.sha`, `base.ref`, `html_url` | PR lifecycle; `head.ref` → branch → task |
| `pull_request_review` | Pull requests | `submitted`, `edited`, `dismissed` | `review.state` (`approved`/`changes_requested`/`commented`/`dismissed`), `review.user`, `review.commit_id` | Review state |
| `check_suite` | Checks | `completed` | `conclusion`, `head_branch`, `head_sha`, `pull_requests` | Overall CI |
| `check_run` | Checks | `completed` | `name`, `status`, `conclusion`, `head_sha`, `pull_requests` | Per-check CI |
| `workflow_run` | Actions | `completed` | `conclusion`, `head_branch`, `head_sha`, `pull_requests`, `html_url` | Actions CI |
| `push` | Contents | n/a | `ref`, `after`, `commits[]` (`id`, `message`; max 2048), `forced` | Trailer → task |
| `status` (optional) | Commit statuses | n/a | `state`, `sha`, `context`, `branches` | Non-Checks CI |

Pushes from forks have empty `pull_requests` and a null `head_branch`, so fall back to `head_sha`.

**Delivery rules:**
- Respond 2XX within 10 s.
- Payloads are capped at 25 MB.
- GitHub does **not** redeliver automatically. You can redeliver deliveries from the past 3 days via the REST API.
- Dedupe on `X-GitHub-Delivery`; a redelivery keeps the same value.

**Serverless receiver (Cloudflare Worker).** This uses Web Crypto, the same API as GitHub's JS example. The same function also verifies Cursor's `X-Webhook-Signature`.

```ts
export default { async fetch(req: Request, env: Env, ctx: ExecutionContext) {
  const body = await req.text();                                  // raw body, before JSON.parse
  if (!(await verify(env.GH_SECRET, body, req.headers.get("X-Hub-Signature-256") ?? "")))
    return new Response("bad signature", { status: 401 });
  ctx.waitUntil(env.QUEUE.send({ event: req.headers.get("X-GitHub-Event"),
    delivery: req.headers.get("X-GitHub-Delivery"), body }));
  return new Response(null, { status: 202 });
}};
async function verify(secret: string, body: string, header: string) {
  const hex = header.startsWith("sha256=") ? header.slice(7) : "";
  if (!/^[0-9a-f]{64}$/.test(hex)) return false;
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["verify"]);
  const sig = new Uint8Array(hex.match(/../g)!.map(h => parseInt(h, 16)));
  return crypto.subtle.verify("HMAC", key, sig, enc.encode(body));
}
```

---

## Lowest common denominator

| Capability | Claude Code | Codex | Cursor | Gemini |
|---|---|---|---|---|
| MCP client, stdio + Streamable HTTP | yes | yes | yes | yes |
| Session start/end hook | yes | yes | yes | yes |
| Post-tool hook (name/input/output) | yes | yes | yes | yes |
| Turn-end final text | `last_assistant_message` | `last_assistant_message` | `afterAgentResponse.text` | `prompt_response` |
| Native HTTP hook | **yes** | no | no | no |
| `mcp_tool` hook | yes | yes | no | **unverified** |
| OTel export | yes | yes | **unverified** | yes |
| Git hooks / trailers | identical | identical | identical | identical |

**Build in this order:**
1. **MCP server** (`report_progress`, `mark_blocked`) **+ `prepare-commit-msg` trailer.** These are the only parts that work identically everywhere; only the config file location differs.
2. **One `teamloop-hook` stdin→HTTPS shim** with a per-tool field map (table above). Three of the four tools have no native HTTP hook, so a command shim is the portable path.
3. **GitHub App** for PR, review and CI data, joined to tasks on `head.ref` and the trailer.
4. OTel only as optional enrichment. Never parse transcripts or rollouts.

**Flags:**
- MCP self-reporting depends on the model choosing to call the tool. Back it with rules/AGENTS.md and a deterministic `Stop` hook.
- End-of-session budgets are tiny: 1.5 s in Claude Code, 1 s in Codex. The shim must spool to local disk and send asynchronously.
- Codex and Cursor require a per-user hook trust step, which is onboarding friction.

---

## Sources

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/mcp
- https://code.claude.com/docs/en/monitoring-usage
- https://code.claude.com/docs/en/sessions.md
- https://learn.chatgpt.com/codex/hooks
- https://learn.chatgpt.com/docs/config-file/config-advanced
- https://learn.chatgpt.com/docs/extend/mcp?surface=cli
- https://github.com/openai/codex/blob/main/codex-rs/hooks/src/legacy_notify.rs
- https://github.com/openai/codex/blob/main/codex-rs/rollout/src/recorder.rs
- https://github.com/openai/codex/blob/main/codex-rs/history/src/rollout_payload.rs
- https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs
- https://cursor.com/docs/agent/hooks
- https://cursor.com/docs/context/mcp
- https://cursor.com/docs/cli/mcp
- https://cursor.com/docs/context/rules
- https://cursor.com/docs/cloud-agent/api/endpoints
- https://cursor.com/docs/cloud-agent/api/webhooks
- https://forum.cursor.com/t/cursor-cli-doesnt-send-all-events-defined-in-hooks/148316 (community, not official)
- https://geminicli.com/docs/hooks/
- https://geminicli.com/docs/hooks/reference/
- https://geminicli.com/docs/tools/mcp-server/
- https://geminicli.com/docs/cli/telemetry/
- https://git-scm.com/docs/githooks
- https://git-scm.com/docs/git-interpret-trailers
- https://git-scm.com/docs/pretty-formats
- https://docs.entire.io/guides/configuration/git-hooks
- https://github.com/entireio/cli/blob/main/cmd/entire/cli/trailers/trailers.go
- https://github.com/entireio/cli/blob/main/cmd/entire/cli/hooks_git_cmd.go
- https://docs.github.com/en/webhooks/webhook-events-and-payloads
- https://github.com/octokit/webhooks/tree/main/payload-schemas/api.github.com
- https://docs.github.com/en/webhooks/types-of-webhooks
- https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries
- https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks
- https://docs.github.com/en/webhooks/testing-and-troubleshooting-webhooks/redelivering-webhooks
- https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api
