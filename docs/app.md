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
- **Tools**, in groups: **Team board** (read the board and the team's history; create, assign, close, start tasks), **Files and git** (read, search and write in the repos connected on This laptop; branch, commit, push and open pull requests, below), **Terminal** (run shell commands; always asks first), **Browser** (read pages; show a page in the browser panel), **Memory** (`remember`, `forget`, `recall`; below).
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

## Git, like Claude Code
Agents ship work the way Claude Code does: `git_branch`, edit, `git_commit`, `git_push`, `open_pr` (plus `git_status` and `git_pull`).
- **Your own sign-in.** They use this laptop's git and its GitHub sign-in (Git Credential Manager, part of Git for Windows), and the GitHub CLI for pull requests when it's signed in; otherwise GitHub's new pull request page opens with the title and description filled in, for you to click Create. Super Agents keeps no GitHub token.
- **Rules.** A commit takes only the files it names (whatever else is staged stays yours) and never lands on the default branch; a push never forces and never goes to the default branch; a pull only fast-forwards. Pushes and pull requests always ask, in every mode; branches, commits and pulls follow the mode. In a connected repo, the commit hook adds the task to agents' commits too.
- **Team projects** (This laptop): the lead links the team's GitHub repos; a teammate clicks **Get the project**, picks a folder, and the app clones it with their own sign-in and connects it. The panel also says whether git, a credential helper and the GitHub CLI are here.

## Skills
Skills use Claude Code's format: a folder with `SKILL.md` (frontmatter `name` and `description`, then instructions) and any files it refers to. An agent sees each of its skills' names and descriptions and reads a skill in full (`load_skill`) when the task calls for it; an "always on" skill is in every message.

**Karpathy's guidelines** (`karpathy-guidelines`: think before coding, simplicity first, surgical changes, goal-driven execution) ship with the app and are on for every new agent; switch them off per agent. Source and licence: `app/superagents/skills/karpathy-guidelines/SOURCE.md`.

Make your own on **Agents → Skills**, customise a built-in one (your copy keeps its files; delete it to go back), or import skills you already have for Claude Code (`~/.claude/skills`, copied, never changed). Yours live in `~/.teamloop/skills`.

## Connectors (MCP)
Connectors are MCP servers, as in Claude Desktop: a URL (streamable HTTP, with an optional `Authorization` header) or a command this laptop runs (stdio). Presets: GitHub (a personal access token), Context7 (library docs, no account), Filesystem and Memory (Node.js). Give a connector to an agent and its tools appear as `mcp__<connector>__<tool>`. Test shows the tools a server offers. Settings, including tokens, stay in `~/.teamloop/connectors.json` and go only to the server they belong to.

## Memory
Agents carry what they learn across chats, sessions and projects (`runtime/memory.py`; **Agents → Memory** shows it all).
- **Notes:** short, lasting facts: a preference, a decision, how a project works. You add them there, or an agent saves one with `remember` when you tell it something worth keeping ("remember that releases need a passing demo check"). Every agent gets the shared notes and its own in every message (the newest, up to about 3,000 characters), and `forget` drops one that's out of date. If you ask an agent to remember something and it answers without saving it, the loop asks it once to call `remember`. Notes that look like a secret are refused. In `~/.teamloop/memory/notes.json`.
- **Recall:** `recall` searches what happened before: the notes, earlier Super Agents chats, and your own Claude Code and Codex sessions in **every project** on this laptop. It's how "how did we fix the stream drops last week?" gets answered from a session in another repo. Only the prompts you typed and the agents' replies are indexed, never tool output, thinking or injected context. Each hit says where it came from (tool, project, session title, date).
- **The index** is SQLite full-text search (FTS5, stemmed, ranked by bm25) in `~/.teamloop/memory/index.db`. It fills in the background, newest sessions first, and after that reads only what's new in each file. The first pass reads every session log on the laptop: on a laptop with 4.4 GB of them it took 36 s and made a 42 MB index; searches take milliseconds. Switch **Coding sessions** off on Agents → Memory to keep them out (notes and chats stay searchable).
- **What leaves the laptop:** the index never does. What a search finds goes to the model as a tool result, like any tool's output, with secrets hidden first.

## The side panel: files, terminal, browser
The buttons at the top right open a panel next to the chat (drag its edge to resize):
- **Files:** a tree of the connected repos and a viewer with syntax highlighting, Markdown preview and images. Read only; agents write through their tools, and an open file reloads when an agent writes it.
- **Terminal** (Ctrl+`): a real shell (PowerShell 7 if installed, else Windows PowerShell) in a pseudo-console, in your first connected repo. Tabs for more than one.
- **Browser:** the browser you share with your agents (below), live and sized to the panel. Click, scroll and type in it to use it yourself or to take over from an agent; "Open in its own window" shows a page in a plain Super Agents window.

**Expand** (the arrows next to the panel's close button) gives the panel the whole work area, for a terminal or a page at full width; picking a view in the sidebar puts it back. The sidebar on the left folds to icons with the button at its top or **Ctrl+B** (names show as tooltips) and stays folded next time.

## The agent browser
Agents use a real browser (`runtime/browser.py`): the installed Microsoft Edge (or Chrome), driven with Playwright, with its own profile in `~/.teamloop/browser`, apart from your own browser and its sign-ins. You watch it in the Browser panel as it works ("Agent S is using the browser", a ring where it clicks), and it's yours too: what you click and type there goes to the same page.
- **What agents read is text:** each step returns the page as numbered elements (`ref_12 button "Sign in" (submits a form)`, with values and states), its text, and its console errors and failed requests. Nemotron reads text, so screenshots (`browser_screenshot`) are proof for you, shown in the chat. Steps wait for the page to settle (500 ms without changes, at most 3 s on the network), so pages that render late are read whole.
- **Tools:** `browser_open` (a URL, or back, forward, reload), `browser_snapshot` (with `find` to search), `browser_click`, `browser_type`, `browser_select`, `browser_press`, `browser_scroll`, `browser_wait`, `browser_screenshot`, `browser_console`, `browser_eval` (always asks), `browser_batch` (several steps in one model call), and `dev_server`.
- **Dev servers:** `dev_server` starts a repo's dev command from `.superagents/launch.json` (`{"configurations": [{"name": "web", "command": "npm run dev", "port": 5173}]}`) or its `dev`/`start` script, waits for the port and gives the URL; servers stop with the app.
- **Checking its own work:** if a turn changed UI files and never looked at them in the browser, the loop asks once (start the dev server, open the page, read the console) before the agent may finish, as Claude Code's auto-verify does.
- **What asks you:** localhost, 127.0.0.1 and `*.localhost`/`*.test` are free. Other sites ask first: allow once (for this run of the app), or always for that site (Settings → Privacy lists them). On those sites, steps that submit or look risky (delete, pay, send, publish, sign out…) follow the mode. Passwords (except on localhost), card numbers and anything that looks like a secret are never typed by an agent: you take over. Downloads are blocked, and the app's own address can't be opened.
- Limits: copying text out of the live view and uploading files through it aren't supported yet.

## Settings
Click your name at the bottom of the sidebar → **Settings** (or **Ctrl+,**). One page for:
- **Account:** who you're signed in as, your role in the current team, and Sign out.
- **Appearance:** dark or light.
- **Privacy:** sharing from this laptop, letting agents search your coding sessions (Memory), and your rules for teammates' prompts into your sessions (Super Team). These are the same switches as on This laptop, Agents → Memory and Super Team → Sessions.
- **Keyboard shortcuts**, and **About** (version, licence, source code).

## Super Team
Teammates connected through Super Agents are a **Super Team**. Anyone in it, lead or member, can send a prompt into a teammate's live Claude Code or Codex session: ask the agent that has the context ("what's left on T-22?", "explain your diff"). Agents can do it too (`team_sessions`, `prompt_session`, `session_prompt`).
- **The owner's rules** (Super Team → Sessions → Your sessions): prompts from teammates are **off**, **ask me each time** (the default: a badge and a toast, then Allow or Deny), or **run automatically**. Runs are **read only** (the default) or **can edit files**. A **daily token limit per teammate**, or unlimited.
- **How it runs:** on the owner's laptop, by their Super Agents (it has to be open), with the tool's own CLI, in that session's repo. Claude Code runs `claude -p --resume <session> --fork-session` in `--restricted` mode: a copy of the session, so the one the owner is in isn't touched; no command or code tools; files only in that repo; the owner's allow-rules and MCP servers don't apply; read-only runs also deny edits. Codex runs `codex exec resume` in its read-only or workspace-write sandbox. The prompt goes in on stdin. A run stops when the teammate's tokens for the day run out (checked as each message arrives) or after 10 minutes.
- **Threads:** your prompts into a session form a thread (Super Team → Sessions → Prompt / Open thread), saved on the hub, so it reads the same tomorrow or on another laptop. A follow-up is answered as one: each run gets your last 3 exchanges in that session, while still starting from a fresh copy of the owner's live session, so it also sees their latest work.
- **When the owner's laptop is closed:** sessions stay listed for 14 days, and the list says since when their Super Agents has been offline. What you send waits and runs when it's back: straight away if their rules run prompts automatically, once they allow it if they ask each time. A prompt that hasn't run within 7 days expires instead of running late.
- **On record** (Super Team → Prompts): who asked what, into whose session, who allowed it (or that their rules did), what it used, and the answer. The lead sees the whole team's; a member sees what they sent or received. Usage shows prompts into sessions by person. Kept 30 days.
- **Files** (Super Team → Files): share files (up to 10, 25 MB each) with one teammate or everyone, with a note; agents can too (`share_files`, always asks). They're read on this laptop, refused if they look like secrets (a `.env`, a key file, or text with a token in it), and uploaded straight to the team's private storage through a short-lived link, never through the hub; they're kept 14 days. The person they're for gets a toast and saves them into a connected repo's `.superagents/inbox/<share>/` (each file checked against the sender's SHA-256, never overwriting, never run), which goes in the repo's `.git/info/exclude` so it can't be committed by accident. The record (who shared what with whom, who saved it) is the team's; between two teammates, the lead sees the record but not the files.
- **Branches:** code goes by git, not files. An agent hands the current, pushed branch to a teammate (`share_branch`, always asks); they click **Check it out** (or `take_share`), which fetches it and switches to it in their clone of that repo, if nothing there is uncommitted.

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
The hooks share summaries and facts only (see the README), now including each turn's token counts. Files leave only when you (or an agent you allow) share them in Super Team → Files. Chats with your agents are different: to answer, each message, the agent's instructions and skills, and what its tools read (file contents, command output, pages, what `recall` finds in your notes, chats and coding sessions) go to Nemotron through the hub's `/v1/llm`. The hub passes them on and doesn't store them; chats are kept on this laptop.

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
