# The hosted hub: accounts, teams, invite links

> Since 0.3 the product is the **Super Agents** desktop app ([docs/app.md](app.md)); this hub is what it talks to. The website at `/` is the landing page with the waitlist, and `/join/<link>` the invite page (with the download); `/auth` and `/device` remain for `teamloop login` from a terminal. The app's GitHub sign-in also needs the redirect URL `http://127.0.0.1:*/**` in Supabase.

The hosted board at https://teamloop.vercel.app. People sign in with **GitHub or email and password**, create a team, and invite teammates with a link. Each laptop connects with `teamloop login`, which works like `gh auth login`: the terminal shows a code, the browser asks you to approve it, done.

The self-hosted hub (`teamloop hub`, room token and lead key) still works and is unchanged. The board page detects which one it is talking to (`GET /v1/config`).

## How it fits together
```
laptop: teamloop (hooks, MCP)  --Bearer tl_ token-->  Vercel: api/index.py -> cloud/cloud/app.py  --SQL-->  Supabase Postgres
browser / app window           --session cookie---->       (same function)                  --verify-->  Supabase Auth
```
- **Sign-in:** the board uses supabase-js for GitHub or email/password, then trades the Supabase access token for the hub's own HttpOnly session cookie (`POST /v1/session`; the hub checks it with Supabase's `/auth/v1/user`). The browser drops the Supabase tokens right after.
- **Data:** every table has row-level security on and no policies, so nothing is reachable through Supabase's public API. Only the hub's server-side connection reads and writes. Schema: [cloud/cloud/schema.sql](../cloud/cloud/schema.sql).
- **Teams:** whoever creates a team is its lead. Leads make invite links (7 days, up to 20 people), remove members (their laptop tokens stop working at once) and restore them.
- **`teamloop login`:** `POST /v1/device/start` gives a code; the person approves it on `/device?code=…` and picks a team; the CLI's poll gets a `tl_` token once. Only the token's hash is stored.
- **Agent S:** Vercel has no background workers, so the open board calls `POST /v1/refresh` after it renders. That re-estimates at most 2 stale tasks (quiet for 30 s), one refresh per team at a time. Reading the board never waits for the model.
- **The app's agents:** `POST /v1/llm?team=` runs one step of an agent's tool loop on the hub's Nemotron key (team members only; 150 steps per 10 minutes and 10M tokens per 24 hours for each person, then 403; 400 KB per request). The loop and its tools run on the laptop.
- **Model calls are for team members:** Ask (`POST /v1/ask`) and the digest (`GET /v1/digest`, `model` one of auto, lightning, super, ultra) need a team and share Ask's limit of 30 per 10 minutes; the signed-out demo board makes no model calls. A failed model call is logged.
- **Events are checked on the way in** (`hub.team.bad_shape`, shared with the self-hosted hub): `ts` is text, `facts` and `report` are objects, `facts.usage` counts are whole numbers, and so on, so one malformed event can't break a team's board. Decisions, task titles and share notes are cleaned like summaries (`hub.safety.sanitize`), since teammates' agents read them.
- **Turn summaries:** `POST /v1/summarize` (`{text, facts}`, a connector's `tl_` token; 120 per 10 minutes per person, within the daily allowance) writes a coding turn's one-line summary with Nemotron Lightning (no thinking: one call, about a second) from the agent's last message. The hub keeps neither; the connector sends the summary with the event. Its tokens count as `progress` in `agent_usage`.
- **Invite only:** `POST /v1/teams` is for people already in a team, or listed in `HUB_TEAM_CREATORS` (emails, comma-separated; `*` lets anyone in). Everyone else signs in and joins through a lead's invite link; without a team nothing reaches the model.
- **Team rules are enforced by each member's app:** the steps that need a lead's yes (`/v1/rules`, `/v1/approvals`) are checked in the member's Super Agents before it acts. The hub doesn't refuse a member's own board or share calls, so a modified client could skip them.
- **Waitlist:** `POST /v1/waitlist` (`{email, name?, team_size?, note?, source?}`; 5 per 10 minutes per visitor) is the landing page's form; one row per email in `waitlist`.
- **Usage:** each coding turn's token counts arrive on its `turn_end` event (`facts.usage`, counted on the laptop). Super Agents' own Nemotron calls (agent steps, answers, plans, progress, digests) go to `agent_usage`. `GET /v1/usage?team=&days=&tz=` sums both by day, tool, task, model and person; leads see everyone, members see themselves.
- **Limits:** 60 event batches per member per minute, 8 KB per event, 30-day retention (swept on writes), no live stream (the board polls every 15 s and skips hidden tabs).

- **Super Team:** `GET /v1/sessions` (teammates' sessions from the last 14 days, with each owner's rules, whether their app is online or since when it's been offline, and how many prompts are in each thread), `GET /v1/sessions/{session}/thread` (that session and the prompts into it you may see, oldest first), `PUT /v1/sessions/access` (your rules: `mode` off/ask/auto, `access` read/edit, `daily_tokens` or null), `POST /v1/prompts` (into a session), `GET /v1/prompts?box=all|in|out` and `/v1/prompts/{id}` (the record: the lead sees all, a member what they sent or received), `POST /v1/prompts/{id}/decide` (the owner), `/cancel` (the sender, before it runs). The owner's app uses `GET /v1/prompts/runnable` (which also marks it online), `POST …/claim` (with what's left of the sender's tokens today and the sender's last 3 answered exchanges in that session) and `POST …/finish`. A prompt still pending or approved after 7 days expires.
- **Files:** `POST /v1/shares` (`{to, note, files: [{name, size, sha256}]}` or `{to, note, repo, branch}`; returns a signed upload link per file), `POST /v1/shares/{id}/ready` (the sender's app, after uploading: each file's size is checked in storage), `GET /v1/shares` and `/v1/shares/{id}` (the lead sees all; a member what they sent, what's for them and what's for everyone), `GET /v1/shares/{id}/files/{n}` (a 5-minute download link, for the sender and the people it's for; who saved it goes on record), `DELETE /v1/shares/{id}` (the sender or the lead). 25 MB a file, 10 a share, 300 MB a team; files go after 14 days (on the next list, since there's no cron), records after 30. Storage: Supabase Storage's private `shares` bucket when `SUPABASE_SECRET_KEY` is set (the app uploads and downloads there directly, so Vercel's 4.5 MB body limit never applies); otherwise a folder on the hub (`HUB_BLOBS_DIR`, links at `/v1/blobs/<token>`), except on Vercel, where sharing then answers that it isn't set up.
- **Team projects:** `GET /v1/teams/{team}/repos` (the team's GitHub repos, for Get the project; anyone in the team), `POST` with `{url}` and `DELETE ?url=` (the lead; up to 20; any usual form of a GitHub URL is stored as `https://github.com/owner/repo`).
- **Deadlines:** `due` (YYYY-MM-DD) on `POST /v1/tasks` and `PATCH /v1/tasks/{task}` (`""` clears); the board and task detail return it.
- **Phone remote:**
  - `/remote/` serves the phone app, an installable web app with a service worker; it caches only its own files.
  - `GET /v1/config` says which relay phone and laptop use: `relay` is `"supabase"` when `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are set (Realtime Broadcast on a public channel named after a random 128-bit id). Otherwise it's `"hub"` for this hub's own `WS /v1/relay`, the part of Realtime's Phoenix protocol the remote uses (join, broadcast to the others on a channel, heartbeat; nothing kept). On Vercel without Supabase it's `null`, because Vercel's instances don't share the relay's rooms.
  - Every message is AES-256-GCM sealed end to end. The hub and Supabase only pass them on.
- **Planning twice:** `POST /v1/tasks` answers 409 when a task that isn't done already has the same title (case and spacing ignored), naming that task.
- **Titles:** a title set with `PATCH /v1/tasks/{task}` (a rename) beats the title the session gave the task. A task ID stored as a title doesn't count as a name.
- **Task detail timeline:** each event also carries its `session`, the agent's `report` (percent, done, next, doing; or what blocks it), and a turn's `summary` and `status`, so a client can group by session and show reports as rows.

### Migrations
`schema.sql` is the whole schema for a fresh database. A live one gets [cloud/cloud/migrations.sql](../cloud/cloud/migrations.sql), in order: `teamloop_cloud_v1` (applied), `teamloop_cloud_v2_tasks` (`tasks`), `teamloop_cloud_v3_usage` (`agent_usage`), `teamloop_cloud_v4_super_team` (`tasks.due`, `session_access`, `session_prompts`), `teamloop_cloud_v5_team_repos` (`team_repos`), `teamloop_cloud_v6_shares` (`shares`, and on Supabase the private `shares` bucket with a 25 MB limit), `teamloop_cloud_v7_team_rules` (`team_rules`, `decisions`, `approvals`), `teamloop_cloud_v8_waitlist` (`waitlist`). Each statement is safe to run twice. Production has v1 to v6 (14 Oct); how a release applies the rest: [release.md](release.md).

## One-time setup (Yang)
These four switch it on. They need your Supabase and GitHub accounts, and step 4 holds the database password, so they're yours.

1. **Supabase → Authentication → Sign In / Providers → Email:** turn **off** "Confirm email". (Supabase's built-in mailer only sends to members of your Supabase org, so teammates would never get the confirmation.)
2. **Supabase → Authentication → URL Configuration:** Site URL `https://teamloop.vercel.app`; add the redirect URL `https://teamloop.vercel.app/**`.
3. **GitHub sign-in:** create an OAuth App at https://github.com/settings/applications/new (GitHub → Settings → Developer settings → OAuth Apps → *New OAuth App*):
   - Application name: `TeamLoop`
   - Homepage URL: `https://teamloop.vercel.app`
   - Authorization callback URL: `https://ntsprbjtdnwhcrgxltem.supabase.co/auth/v1/callback`

   Register it, then *Generate a new client secret*. Paste the Client ID and the secret into **Supabase → Authentication → Sign In / Providers → GitHub** and enable it.
4. **Database URL for Vercel:** first set a database password you know: Supabase → *Project Settings* → *Database* → *Reset database password*. (The project was created through the API, so nobody knows its first password. Letters and digits only, or the URL needs `%`-encoding.) Then Supabase → *Connect* → *Transaction pooler* (port 6543), and replace `[YOUR-PASSWORD]` with it. From the repo folder:
   ```bash
   vercel env add DATABASE_URL production
   ```
   and paste it when asked. Redeploy (`vercel deploy --prod`). With `DATABASE_URL` set, the function serves the cloud hub; without it, it serves the old demo-only hub.

`SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are also Vercel env vars. Both are public (the browser needs them), so they're not secrets.

## Run it locally
```bash
uv pip install -e agent_s -e hub -e "cloud[dev]"
cd cloud && python -m pytest -q        # starts a throwaway Postgres (pgserver); or set TEST_DATABASE_URL
```
`.scratch/cloud_dev.py` (not committed) runs the app on :8811 against a local Postgres with Agent S faked, for UI checks.
