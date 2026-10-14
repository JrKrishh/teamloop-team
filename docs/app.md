# Super Agents: the desktop app

Super Agents is the product: one Windows app where you sign in, chat with your agents (Agent S and the ones you make) about your team's work and your code, see the board, manage the team and set up this laptop. The website (teamloop.vercel.app) is the landing page and the download. The connector (hooks, MCP server, CLI) and the cloud hub are the parts underneath; TeamLoop is the name of that team hub.

```
SuperAgents.exe ─ window (WebView2) ─ UI (app/superagents/ui) ─┐ same origin, per-launch key
                └ local server on 127.0.0.1:<random port> ─────┘
                    ├─ the agent loop (runtime/): tools, skills, MCP connectors, modes, chats in ~/.teamloop/chats
                    │     └─ each model step: the hub's POST /v1/llm → Nemotron on Nebius Token Factory
                    ├─ Supabase Auth: GitHub (system browser, PKCE) or email/password
                    ├─ the hub (teamloop.vercel.app/v1/*) with the person's session token
                    └─ this laptop: teamloop init / pause / send, ~/.teamloop/config.json, the terminal (ConPTY)
teamloop.exe ─ hooks and MCP server, run by Claude Code and Codex; sends to the hub with this laptop's tl_ token
```

## Agents
Agent S is built in; add more on **Agents** (a reviewer, a release manager, a researcher). Each agent has its own:
- **Instructions**: its behaviour (role, tone, what to check, what never to do), added to every message.
- **Default model and mode**, applied when you pick it in the composer.
- **Tools**, in groups: **Team board** (read the board and the team's history; create, assign, close, start tasks), **Files** (read, search and write in the repos connected on This laptop), **Terminal** (run shell commands; always asks first), **Browser** (read pages; show a page in the browser panel).
- **Skills** and **Connectors** (below).

Agents live in `~/.teamloop/agents.json`. Agent S's instructions are editable; it can't be deleted.

## How a turn runs
The loop runs on this laptop (`runtime/loop.py`), like Claude Code's: the model gets the agent's instructions, its skills and its tools, calls tools, sees the results and answers. Each model step goes through the hub's `POST /v1/llm` (the hub holds the Nebius key; signed-in people only, rate limited), so the app needs no key of its own. The window follows the turn as it happens: tool cards with their state, then the answer in Markdown. Claims about what the team did come from `team_ask`, which answers with cited events (Show evidence).

**Modes** (Shift+Tab cycles them), as in Claude Code:
- **Manual**: reads run; every change (tasks, file writes, connector actions) waits for Allow or Deny.
- **Auto**: changes run and show Undo where it can be exact (a created or closed task).
- **Plan**: reads run; changes are queued as steps, and nothing runs until Run plan. If the model writes its plan in prose without queuing every step, the loop asks it once to queue the missing steps.
- Shell commands (`run_command`) **always** ask, in every mode. A connector's tool counts as a read only when its server marks it `readOnlyHint`.

**Model:** Auto uses Nemotron Super for chats (Ultra for the digest); or pin Lightning, Super or Ultra.

**Import (+):** files (specs, task lists, notes; up to 5, 200 KB each) or a public repo's open GitHub issues, added to the message.

## Skills
Skills use Claude Code's format: a folder with `SKILL.md` (frontmatter `name` and `description`, then instructions) and any files it refers to. An agent sees each of its skills' names and descriptions and reads a skill in full (`load_skill`) when the task calls for it; an "always on" skill is in every message.

**Karpathy's guidelines** (`karpathy-guidelines`: think before coding, simplicity first, surgical changes, goal-driven execution) ship with the app and are on for every new agent; switch them off per agent. Source and licence: `app/superagents/skills/karpathy-guidelines/SOURCE.md`.

Make your own on **Agents → Skills**, customise a built-in one (your copy keeps its files; delete it to go back), or import skills you already have for Claude Code (`~/.claude/skills`, copied, never changed). Yours live in `~/.teamloop/skills`.

## Connectors (MCP)
Connectors are MCP servers, as in Claude Desktop: a URL (streamable HTTP, with an optional `Authorization` header) or a command this laptop runs (stdio). Presets: GitHub (a personal access token), Context7 (library docs, no account), Filesystem and Memory (Node.js). Give a connector to an agent and its tools appear as `mcp__<connector>__<tool>`. Test shows the tools a server offers. Settings, including tokens, stay in `~/.teamloop/connectors.json` and go only to the server they belong to.

## The side panel: files, terminal, browser
The buttons at the top right open a panel next to the chat (drag its edge to resize):
- **Files:** a tree of the connected repos and a viewer with syntax highlighting, Markdown preview and images. Read only; agents write through their tools, and an open file reloads when an agent writes it.
- **Terminal** (Ctrl+`): a real shell (PowerShell 7 if installed, else Windows PowerShell) in a pseudo-console, in your first connected repo. Tabs for more than one.
- **Browser:** shows a page (a dev server on localhost, docs, a page an agent opens) inside the app. Sites that refuse to be framed open in their own Super Agents window.

## Super Team
Teammates connected through Super Agents are a **Super Team**. Anyone in it, lead or member, can send a prompt into a teammate's live Claude Code or Codex session: ask the agent that has the context ("what's left on T-22?", "explain your diff"). Agents can do it too (`team_sessions`, `prompt_session`, `session_prompt`).
- **The owner's rules** (Super Team → Sessions → Your sessions): prompts from teammates are **off**, **ask me each time** (the default: a badge and a toast, then Allow or Deny), or **run automatically**. Runs are **read only** (the default) or **can edit files**. A **daily token limit per teammate**, or unlimited.
- **How it runs:** on the owner's laptop, by their Super Agents (it has to be open), with the tool's own CLI, in that session's repo. Claude Code runs `claude -p --resume <session> --fork-session` in `--restricted` mode: a copy of the session, so the one the owner is in isn't touched; no command or code tools; files only in that repo; the owner's allow-rules and MCP servers don't apply; read-only runs also deny edits. Codex runs `codex exec resume` in its read-only or workspace-write sandbox. The prompt goes in on stdin. A run stops when the teammate's tokens for the day run out (checked as each message arrives) or after 10 minutes.
- **On record** (Super Team → Prompts): who asked what, into whose session, who allowed it (or that their rules did), what it used, and the answer. The lead sees the whole team's; a member sees what they sent or received. Usage shows prompts into sessions by person. Kept 30 days.

**Lead tools.** Agent S plans with **deadlines** (`create_task` with `due`, `set_deadline`; or the date in a task's drawer), assigns, and **reviews code**: `git_diff` for a connected repo or branch, `github_pr` for a pull request (the GitHub connector's token for private repos), or a prompt into the author's session. The bundled `code-review` skill gives the checklist and the report format. Manual, Plan and Auto apply to all of it as usual. Board cards show due dates (amber when close, red when late).

## Team usage
A counter for the team's AI. The chip at the top shows today's tokens; **Team → Usage** has today, 7 or 30 days: totals for the coding agents (Claude Code, Codex) and Super Agents itself, a chart per day, and tables by task, by person and by model. Board cards and task drawers show each task's tokens, and each answer shows what it used. Agents can read it too (`team_usage`), so "which task cost the most this week?" works in chat.
- **Counted on the laptop:** at the end of each turn the hook reads the coding agent's own log (Claude Code's transcript and its subagents' files; Codex's running totals) from where it left off, and adds the numbers to the turn's event. Only numbers leave: tokens and the model's name, never text or file paths.
- **Tokens** = fresh input + cache writes + output. Cache reads are shown apart: agents re-read their cached context on every call, so they're far larger without being new work.
- **Who sees what:** everyone sees the team's totals and per-task numbers (the task is the unit). Per-person rows go to the lead and to that person, listed by name, never ranked.
- Pausing sharing pauses this too. Kept 30 days, like events.

## Signing in
- **GitHub:** the app opens your normal browser (where you're already signed in to GitHub) on Supabase's authorize page with a PKCE challenge. GitHub sends you back to `http://127.0.0.1:<port>/auth/callback` on this laptop; the app trades the code for a Supabase session, then for the hub's own session (`POST /v1/app/session`), kept in `~/.teamloop/app.json`. Same pattern as `gh auth login` (RFC 8252).
- **Email and password:** the app calls Supabase directly; no browser.
- Signing out also disconnects this laptop, so nothing more is sent under your name. If someone else signs in on the same laptop, the previous person's connection is removed first.

## This laptop
- Picking a team connects the laptop: the hub makes a `tl_` connector token for you and that team (`POST /v1/teams/{team}/connector`), saved where the hooks and the MCP server read it.
- "Connect a repo" runs `teamloop init` on the folder you pick: Claude Code and Codex hooks in personal files kept out of git, the MCP server, the commit-trailer hook.
- The sharing switch is `teamloop pause` / `resume`.

## What leaves the laptop
The hooks share summaries and facts only (see the README), now including each turn's token counts. Chats with your agents are different: to answer, each message, the agent's instructions and skills, and what its tools read (file contents, command output, pages) go to Nemotron through the hub's `/v1/llm`. The hub passes them on and doesn't store them; chats are kept on this laptop.

## Security of the local server
It listens on 127.0.0.1 only, on a new random port each launch. Every `/api` call must carry the key the window got in its URL fragment, and the Host header must be `127.0.0.1:<port>` or `localhost:<port>`. A web page can't send that header without a CORS preflight, which the server never answers, and DNS rebinding fails the Host check. The UI may only reach an allowlist of hub paths.
- The terminal's WebSocket checks the key (in its query), the Host and the Origin.
- File tools and the file viewer reach only the repos connected on This laptop (paths are resolved first, so `..` can't climb out).
- The browser frame is sandboxed without top navigation and can't load the app's own address.

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
The bundle holds two programs sharing one folder: `SuperAgents.exe` (no console; the app) and `teamloop.exe` (console; hooks, MCP, CLI). `Install Super Agents.cmd` copies it to `%LOCALAPPDATA%\TeamLoop`, makes the shortcuts and opens the app. Brand assets and the logo animation: `brand/` (`build_icons.py` renders the `.ico`). Third-party scripts in the UI are vendored with their licences in `app/superagents/ui/vendor/`.

Known limit: on Windows 10 with "Show accent colour on title bars" switched on, Windows paints the title bar in that colour; otherwise it matches the app.
