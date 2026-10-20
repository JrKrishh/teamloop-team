# Super Agents: the desktop app

Super Agents is the product: one Windows app where you sign in, chat with your agents (Agent S and the ones you make) about your team's work and your code, see the board, manage the team and set up this laptop. The website (teamloop.vercel.app) is the landing page with the waitlist; invited people download the app from their invite link. The connector (hooks, MCP server, CLI) and the cloud hub are the parts underneath; TeamLoop is the name of that team hub.

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
- **Tools**, in groups: **Team board** (read the board and the team's history; create, assign, close, start tasks), **Files and git** (read, search and write in the repos connected on This laptop; branch, commit, push and open pull requests, below), **Terminal** (run shell commands; always asks first), **Browser** (the agent browser and dev servers; below), **Memory** (`remember`, `forget`, `recall`; below), **Desktop** (Windows apps through their own controls; off until you turn it on; below).
- **Skills** and **Connectors** (below).
- **Hood**: its colour. Every agent is the mascot in its own hood, on the desktop and the phone (the editor shows it as you pick); it breathes, blinks, glances about and ponders while it thinks, and on the hello screen and in the editor its eyes follow your pointer.

Agents live in `~/.teamloop/agents.json`. Agent S's instructions are editable; it can't be deleted.

## How a turn runs
The loop runs on this laptop (`runtime/loop.py`), like Claude Code's: the model gets the agent's instructions, its skills and its tools, calls tools, sees the results and answers. Each model step goes through the hub's `POST /v1/llm` (the hub holds the Nebius key; signed-in people only, rate limited), so the app needs no key of its own. The window follows the turn as it happens: the steps (tools, commands and what the agent says along the way) fold into one line that says what they did ("Read 3 files, ran a command") and what's running now, and open with a click into a timeline, as on the phone: a dot for how each step went (green done, red failed, hollow not run), what it did and its target, its output on a click. Anything waiting for you (an approval, a planned change) stays in view, the one card in the answer. Then the answer in Markdown.

While it works, type a note and press Enter (the round button turns from Stop to Send once there's text), at the desk or on the phone: it's read before the next step, nothing stops or starts over, and the note shows in the answer. One that arrives as it writes its answer still gets answered; once the answer is done, the desktop sends it as the next message. How this fits the multiplayer picture: [multiplayer.md](multiplayer.md).

A turn works until the job is done, as Claude Code's do: there is no small step limit (200 steps is a runaway guard; at it, the agent says what it did and what's left instead of stopping mid-sentence). Its context stays small however long it runs: the newest six tool results go to the model whole and older ones are cut to their first 400 characters; past 110 messages the oldest steps fold into one line each. Tool definitions were most of every step (about 5,400 of 7,000 input tokens), so a step sends only the team, memory, skills and terminal tools; files, browser, desktop and each connector come with `more_tools` (or the first call to one of their tools) and stay for the rest of the answer. That halved a simple step (7,014 to 3,629 tokens). So each step stays quick, and inside the hub's limits (200 messages, 400k characters). A call that returns the same thing three times is named a loop to the model; when the hub's rate limit is hit, the step waits and tries again instead of failing the turn. Claims about what the team did come from `team_ask`, which answers with cited events (Show evidence).

**Modes** (Shift+Tab cycles them), as in Claude Code:
- **Manual**: reads run; every change (tasks, file writes, connector actions) waits for Allow or Deny.
- **Auto**: changes run and show Undo where it can be exact (a created or closed task).
- **Plan**: reads run; changes are queued as steps, and nothing runs until Run plan. If the model writes its plan in prose without queuing every step, the loop asks it once to queue the missing steps.
- Shell commands (`run_command`) **always** ask, in every mode. A connector's tool counts as a read only when its server marks it `readOnlyHint`.
- **Switching while an answer runs** (desktop or phone) changes that answer too (`POST /api/turns/{id}/mode`): its next steps work the new way and the model is told. What waits for a yes moves on: a change runs at once in Auto (shell commands still ask), and anything is queued in Plan.

**Model:** Auto uses Nemotron Super for chats (Ultra for the digest); or pin Lightning, Super or Ultra.

**Effort:** how hard the model thinks before each step (Token Factory's `reasoning_effort`): Low, Medium (the default), High or Max. Higher thinks longer and gets more room (1800, 4000, 6000 or 8000 tokens a step); in a test, Low got a scheduling question wrong that Medium and up got right. Remembered like the model; a hub from before effort caps a step at 4000 tokens, and the app falls back to that.

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

**Expand** (the arrows next to the panel's close button) gives the panel the whole work area, for a terminal or a page at full width; picking a view in the sidebar puts it back. The sidebar on the left folds to icons with the button at its top or **Ctrl+B** (names show as tooltips) and stays folded next time. Its chats are as in the Android app: the latest three under **Recent**, then **Projects**, a folder per project (the repo the agent worked in, General for the rest) that opens in place and stays as you left it.

## The agent browser
Agents use a real browser (`runtime/browser.py`): the installed Microsoft Edge (or Chrome), driven with Playwright, with its own profile in `~/.teamloop/browser`, apart from your own browser and its sign-ins. You watch it in the Browser panel as it works ("Agent S is using the browser", a ring where it clicks), and it's yours too: what you click and type there goes to the same page.
- **What agents read is text:** each step returns the page as numbered elements (`ref_12 button "Sign in" (submits a form)`, with values and states), its text, and its console errors and failed requests. Nemotron reads text, so screenshots (`browser_screenshot`) are proof for you, shown in the chat. Steps wait for the page to settle (500 ms without changes, at most 3 s on the network), so pages that render late are read whole.
- **Tools:** `browser_open` (a URL, or back, forward, reload), `browser_snapshot` (with `find` to search), `browser_click`, `browser_type`, `browser_select`, `browser_press`, `browser_scroll`, `browser_wait`, `browser_screenshot`, `browser_console`, `browser_eval` (always asks), `browser_batch` (several steps in one model call), and `dev_server`.
- **Dev servers:** `dev_server` starts a repo's dev command from `.superagents/launch.json` (`{"configurations": [{"name": "web", "command": "npm run dev", "port": 5173}]}`) or its `dev`/`start` script, waits for the port and gives the URL; servers stop with the app.
- **Checking its own work:** if a turn changed UI files and never looked at them in the browser, the loop asks once (start the dev server, open the page, read the console) before the agent may finish, as Claude Code's auto-verify does.
- **What asks you:** localhost, 127.0.0.1 and `*.localhost`/`*.test` are free. Other sites ask first: allow once (for this run of the app), or always for that site (Settings → Privacy lists them). On those sites, steps that submit or look risky (delete, pay, send, publish, sign out…) follow the mode. Passwords (except on localhost), card numbers and anything that looks like a secret are never typed by an agent: you take over. Downloads are blocked, and the app's own address can't be opened.
- Limits: copying text out of the live view and uploading files through it aren't supported yet.

## Desktop control (Windows)
Agents can use Windows apps on this laptop (`runtime/desktop.py`) once you turn **Desktop** on for them (Agents → the agent → Tools; it's off by default, for every agent).
- **Through the apps' own controls.** Windows UI Automation gives each window as a tree of controls. An agent reads it as text (numbered elements with role, name, value and state, plus the window's text) and presses buttons, fills fields, ticks boxes, picks options and scrolls through the controls themselves: no mouse, no keyboard, no focus, so you keep working while it fills in another window. Menus and dialogs it opens are followed, a message box in front is called out first, and an element the window rebuilt while the agent was thinking is found again.
- **Keys and the mouse** only when a control can't be reached any other way, asked for explicitly (`mouse=true`, `keys=true`, `desktop_press`); they bring the window forward for a moment.
- **What asks you:** each app the first time (once, or always: Settings → Privacy lists them); opening an app, always; presses that look risky (delete, send, pay, submit…) and keys follow the mode. Agents see the titles of open windows only for apps you've allowed.
- **Never:** Windows Settings and Security, sign-in and admin prompts, the registry, Task Manager, password managers, Super Agents itself. Browsers go to the agent browser; terminals and editors are click only (typing a command is `run_command`'s job, and it asks). Passwords, card numbers and anything that looks like a secret are never typed.
- **Seeing it and stopping it:** a red frame around the window an agent is using, with a caption; **Ctrl+Alt+Esc** stops desktop actions for 30 seconds.
- **Tools:** `desktop_windows`, `desktop_snapshot`, `desktop_click`, `desktop_type`, `desktop_select`, `desktop_scroll`, `desktop_press`, `desktop_open`, `desktop_screenshot` (proof for you, in the chat), `desktop_batch`.
- Not yet: apps with no controls to read (games, canvases, remote desktops) need a vision model, which isn't wired in; elevated (administrator) windows are out of reach by design.

## Settings
Click your name at the bottom of the sidebar → **Settings** (or **Ctrl+,**). One page for:
- **Account:** who you're signed in as, your role in the current team, and Sign out.
- **Appearance:** dark or light.
- **Privacy:** sharing from this laptop, letting agents search your coding sessions (Memory), and your rules for teammates' prompts into your sessions (Super Team). These are the same switches as on This laptop, Agents → Memory and Super Team → Sessions.
- **Phone:** remote control from your phone (below).
- **Keyboard shortcuts**, and **About** (version, licence, source code).

## Phone remote

Your agents keep running on the laptop; the phone drives them, like Claude Code's Remote Control (`app/superagents/remote.py`). Two ways in, one design: the **Android app** (`android/`, native, an APK of under 3 MB) and the **web app** (`cloud/cloud/site/remote/`, added to the home screen; for iPhones and browsers).
- **Needs you:**
  - every question a running turn waits on, from the phone or the desk, as a card with the command or change itself;
  - **swipe right for yes, left for no**, or tap; the tab shows how many wait;
  - below them, what each agent is working on now;
  - a question from a turn started at the desk arrives within seconds, so you can walk away and answer from your pocket.
- **Chats:**
  - search, a few one-tap questions ("What's blocked right now?"), and your chats: in the Android app (and the desktop sidebar) the latest three, then a folder per project (the repo the agent worked in, General for the rest), each opening in place; in the web app, by day;
  - in a chat: start or continue one with any agent and mode (one tap picks both); watch a turn live with its steps folded as on the laptop; approve or deny; run or discard a plan; stop a turn. Answers show as on Claude: tables (sideways scrolling when wide), headings, lists, quotes, and code blocks with a Copy button.
- **Board:** the team's tasks, active first, with Agent S's estimate next to what the coding agent claims and what blocks each one. Tap a task to ask Agent S about it.
- **The Android app adds:**
  - **sign-in** with the desktop's account: GitHub (in a browser tab that comes back to the app; Supabase must allow `superagents://auth/callback`) or email; a new email account's confirmation link comes back to the app the same way (PKCE), so open it on the phone. A new phone is offered it first and can skip it: the pairing code is what connects a phone. The session token is sealed with a key in Android Keystore. The laptop shows who each phone is signed in as.
  - **a theme switch:** the sun or moon beside Settings flips light and dark; Settings → Theme also has System (the default), which follows the phone. The status bar's icons follow the app's theme;
  - **model and effort** in a chat's "Who, and how" sheet, starting from what the desktop is set to; picking an agent applies its default model;
  - **questions in the background:** each one arrives as a notification with **Deny** and **Run it** (or **Approve**) on it, so you answer without opening the app. Run it asks for the phone to be unlocked, and the lock screen shows only "Agent S needs you". An answer posts "Agent S answered".
  - **answers that get there:** a tap on Allow buzzes and spins at once. If the line died quietly (a phone back from sleep), the app connects again and says it once more (a yes said twice is still one yes); back on a network, it reconnects at once rather than after the wait between tries. If it still can't reach the laptop, the card says so and both buttons work again.
  - a quiet "Connected to …'s laptop" notification while it holds the line; Settings → Stay connected in the background turns that off;
  - a QR scanner for pairing (Google's code scanner, so no camera permission);
  - a fingerprint or face lock (on opening, and after a minute away);
  - the mascot: it drops in at startup, waves on Connect, celebrates a pairing and sleeps when the laptop is away. While a turn runs it acts out the step (reading, running a command, writing, searching), hops in when a question arrives and droops when a turn fails; idle, it looks around now and then, and giggles when tapped. Each agent wears its own hood colour. Its eyes dart and its head turns after them, a breath moves it from its base, and going from one step to the next eases over instead of jumping;
  - haptics on yes and no, and Android's back button.
- **Pairing:** Settings → Phone. Turn it on (it's off by default), press **Pair a phone** and scan the code: with the Android app's scanner, or with the phone's camera for the web app. No app store. A code nobody scans expires in 10 minutes.
- **End-to-end encrypted:**
  - **The key:** the code carries a channel id and a 256-bit key in the link's fragment, which browsers never send to a server.
  - **The seal:** every message is sealed with AES-256-GCM under that key, with the channel bound in. The relay sees only noise: Supabase Realtime in production, the hub's own socket in development.
  - **Replays and reflections:** messages older than two minutes, or seen before, are dropped, and neither side accepts its own messages back.
  - **On the phone:** the web app keeps the key in IndexedDB as a WebCrypto key that can't be exported, so the page can use it but no script can read it back. The Android app keeps it in Android Keystore, which won't hand it out either.
- **What the phone can't do:** anything the chat window can't. It goes through the same local API and the same modes and approvals. It can't browse files or open a terminal.
- **Unpair** deletes the key on the laptop, and the phone is cut off at once. On the phone, "Forget this laptop" deletes its copy.
- **Reliability:**
  - The laptop never skips an event it couldn't send.
  - The phone shows events in order, asks again for any gap, and catches up on a running turn after it lost the connection.
  - Turning the switch off, or closing the app, ends remote control.
- **Not yet:**
  - **Push from the hub**, for when the Android app isn't holding the line (Stay connected in the background off, or Android stopped it) or the web app is closed. It needs a Firebase project (free); Web Push on iPhone works only for a home-screen app.
  - **An iPhone app** (Apple's developer account is $99 a year); iPhones use the web app.

## The board

Nobody updates it by hand: status and progress come from the teammates' coding sessions.
- **Read top-down by what needs a lead.** Active tasks are cards, blocked first, then in review, then in progress. The plan (to do, nearest deadline first) and what's done are one line each, with Done folded. The counts at the top filter the board.
- **Each card puts Agent S's estimate from the sessions next to what the coding agent claims** ("95% · Claude Code says 100%"). When the claim runs 15 points or more ahead of the evidence, the card says so. Below that: what blocks the task, what's happening now, and what's next.
- **A task's drawer** has:
  - both lines over time;
  - the facts: status, people, deadline, pull request, AI usage;
  - what happened, by day and coding session. The agent's reports read as Done, Now and Next rows, turn summaries as text, and routine steps (commands, edits, starts and ends) fold into one line per session.
- **The title renames in place:** click it. A task with no name says "No title yet" rather than showing its ID twice.
- **The same title can't be planned twice** while the first task is open. The hub answers with the existing task, so asking an agent twice doesn't double the board.

## Super Team
Teammates connected through Super Agents are a **Super Team**. Anyone in it, lead or member, can send a prompt into a teammate's live Claude Code or Codex session: ask the agent that has the context ("what's left on T-22?", "explain your diff"). Agents can do it too (`team_sessions`, `prompt_session`, `session_prompt`).
- **The owner's rules** (Super Team → Sessions → Your sessions): prompts from teammates are **off**, **ask me each time** (the default: a badge and a toast, then Allow or Deny), or **run automatically**. Runs are **read only** (the default) or **can edit files**. A **daily token limit per teammate**, or unlimited.
- **How it runs:** on the owner's laptop, by their Super Agents (it has to be open), with the tool's own CLI, in that session's repo. Claude Code runs `claude -p --resume <session> --fork-session` in `--restricted` mode: a copy of the session, so the one the owner is in isn't touched; no command or code tools; files only in that repo; the owner's allow-rules and MCP servers don't apply; read-only runs also deny edits. Codex runs `codex exec resume` in its read-only or workspace-write sandbox. The prompt goes in on stdin. A run stops when the teammate's tokens for the day run out (checked as each message arrives) or after 10 minutes.
- **Threads:** your prompts into a session form a thread (Super Team → Sessions → Prompt / Open thread), saved on the hub, so it reads the same tomorrow or on another laptop. A follow-up is answered as one: each run gets your last 3 exchanges in that session, while still starting from a fresh copy of the owner's live session, so it also sees their latest work.
- **When the owner's laptop is closed:** sessions stay listed for 14 days, and the list says since when their Super Agents has been offline. What you send waits and runs when it's back: straight away if their rules run prompts automatically, once they allow it if they ask each time. A prompt that hasn't run within 7 days expires instead of running late.
- **Notes between agents:** when a change affects a teammate's work, a coding agent leaves a note with the connector's `message_teammate` tool ("I renamed /v1/session; rebase before you touch login"), and so can the app's agents and people (the task drawer's Notes, or the task sheet on the phone): to one teammate, to everyone else on the task, or to the team. The connector fetches notes every 15 s; a live Claude Code or Codex session gets each one once at its next step (both take the same hook output), framed as a teammate's information that authorizes nothing; Cursor sessions read them with `read_messages`. Each person turns notes into their sessions on or off (Super Team → Sessions → Your sessions). Secrets are taken out before a note leaves the laptop, and the hub cleans it like other peer text; kept 14 days.
- **Inbox** (Super Team → Inbox): every note to you or to everyone, and the ones you sent, newest first by task; write to a teammate or the whole team, or Reply in place. Unread notes put a badge on Super Team and the Inbox tab, and a new one shows a toast; opening the Inbox marks them read. On the phone they're at the top of Needs you, with a badge, a notification while the app is in the background, Reply and Mark read. How far you've read lives on the hub, so reading on one clears the other.
- **Shared workspace:** when a teammate's agent pushes, your laptop works out from its own checkout which of those commits you don't have yet, without reading any code. Your live sessions get a note at their next step ("Asha's agent pushed 2 commits to main in acme-web (T-19), touching src/auth/session.py, which you changed too: pull before you go on"), an agent asks `team_changes` for the commits, files, line counts and the why (their session's summary) in a few dozen lines instead of exploring the code, and This laptop shows "2 commits from Asha's agent you don't have · Pull" per repo (fast-forward only). Only agents' commits count; what's shared is subject lines, file names and line counts, never code.
- **Who's in which file:** when your session edits a file another person's session edited in the last half hour, or a file of a task someone else claimed (starting a task claims it when nobody owns it), the connector's next poll brings a warning and your session reads it at its next step, once: "src/cart.py is part of T-31, which Asha claimed and has been editing. Check with Asha before changing it."
- **Handoffs:** hand a task to a teammate from its drawer (Hand off) or ask an agent to (`handoff`, always asks; coding agents have the connector's `handoff` tool). The branch must be committed and pushed. They own the task from then on, their sessions get your note, and in Super Team → Files they **Take over**: the branch is checked out and a brief goes beside the code in `.superagents/handoff/<task>.md` (out of git): your note, where Agent S says the task stands, and the latest turns. **Continue in Claude Code** or **Codex** opens the app's terminal in that repo and starts the agent with a first prompt that only names the brief, so nothing a teammate wrote reaches the command line; **Open in Cursor** opens the repo and copies that prompt.
- **On record** (Super Team → Prompts): who asked what, into whose session, who allowed it (or that their rules did), what it used, and the answer. The lead sees the whole team's; a member sees what they sent or received. Usage shows prompts into sessions by person. Kept 30 days.
- **Files** (Super Team → Files): share files (up to 10, 25 MB each) with one teammate or everyone, with a note; agents can too (`share_files`, always asks). They're read on this laptop, refused if they look like secrets (a `.env`, a key file, or text with a token in it), and uploaded straight to the team's private storage through a short-lived link, never through the hub; they're kept 14 days. The person they're for gets a toast and saves them into a connected repo's `.superagents/inbox/<share>/` (each file checked against the sender's SHA-256, never overwriting, never run), which goes in the repo's `.git/info/exclude` so it can't be committed by accident. The record (who shared what with whom, who saved it) is the team's; between two teammates, the lead sees the record but not the files.
- **Branches:** code goes by git, not files. An agent hands the current, pushed branch to a teammate (`share_branch`, always asks); they click **Check it out** (or `take_share`), which fetches it and switches to it in their clone of that repo, if nothing there is uncommitted.
- **Rules** (Super Team → Rules), the team's for every agent in it:
  - **Decisions every agent follows:** anyone in the team pins one ("Deploys go out on Fridays only"), and it's in every teammate's agents' instructions with who decided; an agent asks before going against one. In a chat, "pin that" pins one too (`pin_decision`, a change). The author or a lead removes it; up to 40.
  - **Steps that need a lead's yes:** a lead picks which steps of a member's agent wait for a lead instead of the member: pushing to GitHub, opening pull requests, sharing with the team, changing the board, shell commands. When a member's agent reaches one, the step waits (its card says for whom) and the request goes to the hub; a lead gets a badge and a toast, finds it in Super Team → Prompts under Waiting for you, and on a paired phone in Needs you or as a notification with Deny and Approve. Their yes runs the step; their no (with a note) tells the agent to stop and say so. The member can still cancel it; their own yes doesn't count. A lead's own agents ask the lead as always. Unanswered, a request drops after a day. In Plan mode the step is queued, and Run plan asks the lead. What a lead sees: a line for the step (no file contents), and the command, pull request text or note it would send.

**Lead tools.** Agent S plans with **deadlines** (`create_task` with `due`, `set_deadline`; or the date in a task's drawer), assigns, and **reviews code**: `git_diff` for a connected repo or branch, `github_pr` for a pull request (the GitHub connector's token for private repos), or a prompt into the author's session. The bundled `code-review` skill gives the checklist and the report format. Manual, Plan and Auto apply to all of it as usual. The board shows due dates (amber when close, red when late).

## Team usage
A counter for the team's AI. The chip at the top shows today's tokens; **Team → Usage** has today, 7 or 30 days: totals for the coding agents (Claude Code, Codex) and Super Agents itself, a chart per day, and tables by task, by person and by model. The board and task drawers show each task's tokens, and each answer shows what it used. Agents can read it too (`team_usage`), so "which task cost the most this week?" works in chat.
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
- **Connect from GitHub** lists the repos this laptop's GitHub sign-in can open (the GitHub CLI when it's signed in, else the token Git Credential Manager keeps for github.com, used only to ask GitHub's API), newest first; **Get** clones one into a folder you pick and connects it.
- "Connect a folder" runs `teamloop init` on the folder you pick: Claude Code and Codex hooks in personal files kept out of git, the MCP server, the commit-trailer hook.
- The sharing switch is `teamloop pause` / `resume`.

## What leaves the laptop
The hooks share summaries and facts only (see the README), now including each turn's token counts. Nemotron writes each summary on the hub (`/v1/summarize`) from the turn's last agent message, which the hub doesn't keep; `TEAMLOOP_SUMMARIZER=ollama` writes it on the laptop instead. Files leave only when you (or an agent you allow) share them in Super Team → Files. Chats with your agents are different: to answer, each message, the agent's instructions and skills, and what its tools read (file contents, command output, pages, what `recall` finds in your notes, chats and coding sessions) go to Nemotron through the hub's `/v1/llm`. The hub passes them on and doesn't store them; chats are kept on this laptop.

## Security of the local server
It listens on 127.0.0.1 only, on a new random port each launch. Every `/api` call must carry the key the window got in its URL fragment, and the Host header must be `127.0.0.1:<port>` or `localhost:<port>`. A web page can't send that header without a CORS preflight, which the server never answers, and DNS rebinding fails the Host check. The UI may only reach an allowlist of hub paths.
- The terminal's WebSocket checks the key (in its query), the Host and the Origin.
- File tools and the file viewer reach only the repos connected on This laptop (paths are resolved first, so `..` can't climb out).
- The browser frame is sandboxed without top navigation and can't load the app's own address.

## One-time setup for GitHub sign-in in the app (Yang)
Supabase → Authentication → URL Configuration → Redirect URLs: add `http://127.0.0.1:*/**` (the desktop app; the `*` matches the port, which changes every launch) and `superagents://auth/callback` (the Android app, for GitHub and for email confirmation links). Supabase sends any return address that isn't on this list to the Site URL instead, so a sign-in from the app would end on the website.

## Build and run
```bash
uv pip install -e connector -e agent_s -e hub -e "app[dev]"
python -m superagents                 # the app window
python -m superagents --serve         # just the local server; prints the URL (development)
cd app && python -m pytest -q
pyinstaller packaging/teamloop.spec --distpath dist --workpath build/pyi --noconfirm
```
The bundle holds two programs sharing one folder: `SuperAgents.exe` (no console; the app) and `teamloop.exe` (console; hooks, MCP, CLI). `packaging/SuperAgents.iss` (Inno Setup: `iscc /DVersion=0.3.0 packaging\SuperAgents.iss`) turns it into `dist/SuperAgents-Setup.exe`, one click like Claude's and Codex's installers: per user with no admin, into `%LOCALAPPDATA%\TeamLoop` (connected repos' hooks point there), `teamloop` on the user's PATH, Start-menu and desktop shortcuts, a running copy closed first, the app opened at the end, and an uninstaller in Settings → Apps that leaves `~/.teamloop`. It warns if the PC lacks Microsoft Edge WebView2, which draws the window. CI builds it on every pull request and installs, opens and uninstalls it on a clean machine (`packaging/check_installer.py`). One copy of the app runs per person: opening it again brings the open window forward (a mutex, then `POST /api/window/show` to the open copy, found through `~/.teamloop/window.json`), since two copies would both answer the phone and both run teammates' prompts. Brand assets and the logo animation: `brand/` (`build_icons.py` renders the `.ico`). Third-party scripts in the UI are vendored with their licences in `app/superagents/ui/vendor/`.

The app draws its own title bar, as Claude's and Codex's do (`app/superagents/frame.py`): Windows' own bar can't be restyled, and Windows 10 paints it in the accent colour when "Show accent colour on title bars" is on. The native frame stays (resize edges, snap, the shadow, the animations); a window subclass takes away only its caption (WM_NCCALCSIZE), and WebView2's non-client region support makes the page's `app-region: drag` areas the caption: drag, snap, double-click to maximise, the window menu on right-click. The page's minimise, maximise and close buttons call `/api/window/*`. If WebView2 can't do drag regions, Windows' bar comes back, so the window can always be moved.
