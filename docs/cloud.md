# TeamLoop cloud: accounts, teams, invite links

> Since 0.3 the product is the **Super Agents** desktop app ([docs/app.md](app.md)); this hub is what it talks to. The website at `/` is the landing page and `/join/<link>` the invite page; `/auth` and `/device` remain for `teamloop login` from a terminal. The app's GitHub sign-in also needs the redirect URL `http://127.0.0.1:*/**` in Supabase.

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
- **Limits:** 60 event batches per member per minute, 8 KB per event, 30-day retention (swept on writes), no live stream (the board polls every 15 s and skips hidden tabs).

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
