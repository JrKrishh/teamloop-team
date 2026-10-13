# Super Agents: the desktop app

Super Agents is the product: one Windows app where you sign in, chat with Agent S about your team's work, see the board, manage the team and set up this laptop. The website (teamloop.vercel.app) is the landing page and the download. The connector (hooks, MCP server, CLI) and the cloud hub are the parts underneath; TeamLoop is the name of that team hub.

```
SuperAgents.exe ─ window (WebView2) ─ UI (app/superagents/ui) ─┐ same origin, per-launch key
                └ local server on 127.0.0.1:<random port> ─────┘
                    ├─ Supabase Auth: GitHub (system browser, PKCE) or email/password
                    ├─ the hub (teamloop.vercel.app/v1/*) with the person's session token
                    └─ this laptop: teamloop init / pause / send, ~/.teamloop/config.json
teamloop.exe ─ hooks and MCP server, run by Claude Code and Codex; sends to the hub with this laptop's tl_ token
```

## Agent S: import, modes and models
The composer works like Claude Code's:
- **Import (+):** files (specs, task lists, notes; text, Markdown, CSV, JSON, code; up to 5, 200 KB each) or a public repo's open GitHub issues. Agent S reads them next to the team's session timeline.
- **Mode** (Shift+Tab cycles): Agent S answers, and when you ask it to plan or change the board it proposes changes: create, assign, close or start tasks. **Manual** asks before each change; **Plan** writes numbered steps and changes nothing until you press Run plan; **Auto** applies them and shows each with Undo.
- **Model:** **Auto** uses Nemotron Super for answers and Nemotron Ultra for plans and imports; or pin **Lightning** (fastest), **Super** or **Ultra**.

Agent S only proposes; the app applies (`POST /v1/agent` returns the answer, plan and checked actions; the app calls `/v1/tasks` and, for "start", this laptop's `teamloop task`). Proposals are checked in code: tasks must exist or be new, owners must be members, at most 12. Claims about the team's work still need cited events. Planned tasks show on the board as **to do** until a session reports on them; then they show live progress.

## Signing in
- **GitHub:** the app opens your normal browser (where you're already signed in to GitHub) on Supabase's authorize page with a PKCE challenge. GitHub sends you back to `http://127.0.0.1:<port>/auth/callback` on this laptop; the app trades the code for a Supabase session, then for the hub's own session (`POST /v1/app/session`), kept in `~/.teamloop/app.json`. Same pattern as `gh auth login` (RFC 8252).
- **Email and password:** the app calls Supabase directly; no browser.
- Signing out also disconnects this laptop, so nothing more is sent under your name. If someone else signs in on the same laptop, the previous person's connection is removed first.

## This laptop
- Picking a team connects the laptop: the hub makes a `tl_` connector token for you and that team (`POST /v1/teams/{team}/connector`), saved where the hooks and the MCP server read it.
- "Connect a repo" runs `teamloop init` on the folder you pick: Claude Code and Codex hooks in personal files kept out of git, the MCP server, the commit-trailer hook.
- The sharing switch is `teamloop pause` / `resume`.

## Security of the local server
It listens on 127.0.0.1 only, on a new random port each launch. Every `/api` call must carry the key the window got in its URL fragment, and the Host header must be `127.0.0.1:<port>` or `localhost:<port>`. A web page can't send that header without a CORS preflight, which the server never answers, and DNS rebinding fails the Host check. The UI may only reach an allowlist of hub paths.

## One-time setup for GitHub sign-in in the app (Yang)
Supabase → Authentication → URL Configuration → Redirect URLs: add `http://127.0.0.1:*/**`. The `*` matches the port, which changes every launch.

## Build and run
```bash
uv pip install -e connector -e agent_s -e hub -e "app[dev]"
python -m superagents                 # the app window
python -m superagents --serve         # just the local server; prints the URL (development)
cd app && python -m pytest -q
pyinstaller packaging/teamloop.spec --distpath dist --workpath build/pyi --noconfirm
```
The bundle holds two programs sharing one folder: `SuperAgents.exe` (no console; the app) and `teamloop.exe` (console; hooks, MCP, CLI). `Install Super Agents.cmd` copies it to `%LOCALAPPDATA%\TeamLoop`, makes the shortcuts and opens the app. Brand assets and the logo animation: `brand/` (`build_icons.py` renders the `.ico`).

Known limit: on Windows 10 with "Show accent colour on title bars" switched on, Windows paints the title bar in that colour; otherwise it matches the app.
