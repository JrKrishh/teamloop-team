# TeamLoop cloud: accounts, teams, invite links

The hosted board at https://teamloop.vercel.app. People sign in with **Google or email and password**, create a team, and invite teammates with a link. Each laptop connects with `teamloop login`, which works like `gh auth login`: the terminal shows a code, the browser asks you to approve it, done.

The self-hosted hub (`teamloop hub`, room token and lead key) still works and is unchanged. The board page detects which one it is talking to (`GET /v1/config`).

## How it fits together
```
laptop: teamloop (hooks, MCP)  --Bearer tl_ token-->  Vercel: api/index.py -> cloud/cloud/app.py  --SQL-->  Supabase Postgres
browser / app window           --session cookie---->       (same function)                  --verify-->  Supabase Auth
```
- **Sign-in:** the board uses supabase-js for Google or email/password, then trades the Supabase access token for the hub's own HttpOnly session cookie (`POST /v1/session`; the hub checks it with Supabase's `/auth/v1/user`). The browser drops the Supabase tokens right after.
- **Data:** every table has row-level security on and no policies, so nothing is reachable through Supabase's public API. Only the hub's server-side connection reads and writes. Schema: [cloud/cloud/schema.sql](../cloud/cloud/schema.sql).
- **Teams:** whoever creates a team is its lead. Leads make invite links (7 days, up to 20 people), remove members (their laptop tokens stop working at once) and restore them.
- **`teamloop login`:** `POST /v1/device/start` gives a code; the person approves it on `/device?code=…` and picks a team; the CLI's poll gets a `tl_` token once. Only the token's hash is stored.
- **Agent S:** Vercel has no background workers, so the open board calls `POST /v1/refresh` after it renders. That re-estimates at most 2 stale tasks (quiet for 30 s), one refresh per team at a time. Reading the board never waits for the model.
- **Limits:** 60 event batches per member per minute, 8 KB per event, 30-day retention (swept on writes), no live stream (the board polls every 15 s and skips hidden tabs).

## One-time setup (Yang)
The code is deployed; these four switch it on. Steps 2 and 3 need your Google and Supabase accounts, and step 4 holds the database password, so they're yours.

1. **Supabase → Authentication → Sign In / Providers → Email:** turn **off** "Confirm email". (Supabase's built-in mailer only sends to members of your Supabase org, so teammates would never get the confirmation.)
2. **Supabase → Authentication → URL Configuration:** Site URL `https://teamloop.vercel.app`; add the redirect URL `https://teamloop.vercel.app/**`.
3. **Google sign-in:** in Google Cloud Console → APIs & Services → Credentials → *Create credentials* → *OAuth client ID* → *Web application*. Authorized redirect URI: `https://ntsprbjtdnwhcrgxltem.supabase.co/auth/v1/callback`. (If asked, set up the consent screen first: External, app name TeamLoop, then *Publish app* so anyone can sign in.) Paste the client ID and secret into **Supabase → Authentication → Sign In / Providers → Google** and enable it.
4. **Database URL for Vercel:** Supabase → *Connect* → *Transaction pooler* (port 6543), with your database password filled in. Then, from the repo folder:
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
