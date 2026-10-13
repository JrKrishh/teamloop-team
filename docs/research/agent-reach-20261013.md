# Agent S's reach: browser, computer use, git and file sharing (research and plan, 13 Oct 2026)

Yang asked for five things:
- file sharing in Super Team;
- teammates on GitHub, with the project in a local folder, committing and pushing like Claude Code;
- Agent S that acts better than the Grok, Muse and dots bots;
- a browser better than other coding tools';
- computer use better than Claude Code's and Codex's.

This page has:
- what Agent S can do today;
- what the competition does (four research passes on 13 Oct, sources at the end);
- two probes run on this laptop;
- the ranked plan.

## 1. Where Agent S stands today
| Area | Today (`runtime/tools.py`) | Missing |
|---|---|---|
| Browser | `fetch_url` reads a page's text; `open_in_browser` shows a page in the panel's iframe | Any interaction: clicking, typing, screenshots, console, network, a verify loop |
| Computer use | None | Everything: seeing windows, acting in apps |
| Git | `git_diff` and `github_pr` read diffs | Commit, branch, push and PRs (today only through `run_command`, which asks every time); getting the project onto a teammate's laptop |
| Super Team | Prompts into sessions by the owner's rules, saved threads, on record | Sharing files; proof of work the team can search |
| Safety for actions | Manual / Auto / Plan approvals | A reviewer model for risky actions (all three hosted bots have one); a kill key; grants per site and per app |
| Routines | None | Scheduled or replayable runs (all three hosted bots have schedules) |

**Model constraint:** Nemotron Super and Ultra are text-only. Anything the agent controls has to be readable as text first: an element tree. Images are a fallback.

## 2. The competition
**The three hosted agents** are always-on and each runs on its own cloud computer:
- **Grok Bot** (SpaceXAI, built by Cursor; 11 Aug 2026);
- **Muse** (Meta; 8 Sep 2026);
- **dots** (OpenAI, GPT-6 Astra; 29 Sep 2026).

**What they have:**
- a cloud browser, terminal and files;
- connectors to thousands of apps;
- schedules;
- memory;
- Slack and Teams presence;
- coding handed to a cloud coding agent that returns a PR;
- a **separate reviewer model** that approves risky actions (Grok's Auto Review, Muse's Sentinel, the checks in dots);
- team bots: Grok Team Bots, in public beta since 28 Sep.

**What they lack:**
- **None acts on your own screen.** Cursor staff on Grok Bot, 8 Oct: it "can't see your screen or click and type in your apps yet".
- None reaches teammates' local Claude Code or Codex sessions.
- Cloud IPs get blocked as bots.
- Logins are shared across a user's bots.
- Memory and quotas are opaque. dots doesn't let you view or delete memories.

**Coding tools (the bar for browser and computer use):**
- **Claude Code**
  - Desktop browser pane: dev servers from `launch.json`, auto-verify after edits, an accessibility tree with `ref_N` handles, console, network and JS eval, `browser_batch`.
  - Claude in Chrome for your signed-in browser.
  - Computer use (Windows since about April): screenshots, per-app grants with tiers, Esc to stop. On Windows it takes over the screen; background mode is macOS only.
- **Codex** (now inside the ChatGPT app)
  - An in-app browser the agent drives, 2x faster since June through CDP and DOM snapshots.
  - Windows computer use since 29 May, foreground only. An open "FrameArrived timed out" capture bug has 46 reports.
  - Record & Replay into skills (macOS).
- **Cursor:** browser logs go to files the agent searches, and clicks are by DOM, with pixels only as a fallback. Its cloud agents attach videos to PRs.
- **Antigravity** made the browser an explicit command because agents couldn't tell when to use it.
- **Copilot** posts screenshots in its PRs.

**Benchmarks** (human baseline in brackets):
| Benchmark | Best |
|---|---|
| OSWorld-Verified [72.4%] | GPT-5.4 75.0% (Mar); Claude Fable 5 86.0% and Qwen3.8-Max 86.1% (Aug, self-reported) |
| Windows Agent Arena [74.5%] | 57.5% (CUA-Skill); Simular Agent S3 56.6% |
| WebArena [78.2%] | 74.3% |

**Gaps nobody fills well:**
- Windows control that doesn't take over the screen.
- Evidence of Windows quality.
- Deterministic replay of a successful run.
- Knowing when a single-page app is ready.
- Long tasks: under 50% on OSWorld 2.0.
- Verification history the team can search, tied to commits.
- Independent evals.

**What this means:**
- Generic computer use against Claude and GPT is a race Nemotron can't win: those models now beat humans on OSWorld-Verified.
- Windows, team context and the person's own machine are open.

## 3. Probes on this laptop
**Browser.** Playwright driving the installed Edge (`.scratch/probe_browser.py`):
| Step | Result |
|---|---|
| Launch | 0.3 s |
| Map of numbered elements (23 on the landing page) | 8 ms, 630 characters |
| ARIA snapshot | 99 ms, 3 KB |
| Screenshot | 143 KB |

The element map is about 200 times smaller than the screenshot, and it's text Nemotron can read.

**Desktop.** Windows UI Automation through `uiautomation` 2.0.29 (`.scratch/probe_uia.py`):
| Window | Elements | Time |
|---|---|---|
| A real app window | 389 (210 named, 11 control types) | 434 ms |
| Small windows | — | 10–50 ms |
| The taskbar | 33 | 222 ms |

**Hardware:** a GTX 1050 Ti with 4 GB of VRAM and 32 GB of RAM. Only vision models of about 4B parameters or smaller run on the GPU.

## 4. The plan, ranked (build order = rank)
### 1. Git like Claude Code, and "Get the project" (about 1.5 days)
**Tools:**
- `git_status`
- `git_branch`: create or switch.
- `git_commit`: named files only; a change, so Manual asks.
- `git_push`: always asks; never the default branch, never `--force`.
- `open_pr`: `gh pr create` when `gh auth status` passes within 10 s; otherwise GitHub's `compare/BASE...BRANCH?quick_pull=1` page, so the person clicks Create.
- `git_pull`

**Auth:**
- The laptop's own git and Git Credential Manager (bundled with Git for Windows). Super Agents holds no GitHub token.
- This laptop shows git, GitHub sign-in and `gh` status.
- Fallback: a GitHub App with the device flow. D10 already prefers a GitHub App.

**Team repos:**
- The lead links the team's GitHub repos.
- A teammate clicks **Get the project**, picks a folder, and the app clones and connects it.
- The existing commit trailer links commits to tasks.

**Verify:** tests against a local bare remote, including refusal of the default branch and `--force`; then a real push and PR to a scratch repo.

### 2. The agent browser (about 3–4 days)
**Engine:**
- Playwright for Python drives the installed Edge (no download) with its own profile in `~/.teamloop/browser`, apart from your real browser's logins.
- Never attach to the app's own WebView2: its debug port would expose the app's key to any local process.

**What the agent sees** (text first):
- numbered elements (role, name, `ref_N`);
- page text;
- console errors;
- failed requests;
- a screenshot only to check, or when asked.

Large output goes to files, not the model's context. In one test that was 27k tokens instead of 114k.

**What it can do:**
- open, back, forward;
- click, type, select, press keys, scroll and hover by ref;
- `wait_for`: text, URL, network quiet, or DOM settled. The last one fixes the single-page-app "never finishes loading" problem.
- `browser_batch`: several steps per model call. Model calls take about 10 s and dominate the time.
- run JavaScript (always asks).

**Live view:** the Browser panel shows the agent's browser through CDP screencast, with "Agent S is driving" and Stop. You can take over.

**Dev servers and auto-verify:**
- Start the project's dev script in a managed terminal (`.superagents/launch.json`), wait for the port, open it.
- After UI edits: open the page, check console and network, take a screenshot.

**Proof on the board:**
- Each verification run is saved: steps, console summary and screenshots.
- Its summary goes on the task card and the commit, so the team can search proof of work. Nobody does this.

**Safety:**
- localhost is free; other sites ask Allow once / Always / Deny.
- Submitting a form counts as a change.
- Passwords, cards, 2FA and CAPTCHAs go back to the person.
- Downloads ask.
- Page text is data, never instructions.

**Verify:** 8 browser tasks on local apps with real Nemotron, measuring success, steps, seconds and tokens.

### 3. File sharing in Super Team (about 2 days)
**Sharing:** share a file, or a few, with a teammate or the team from chat, the Files panel, or an agent (`share_file`, a change).

**Hub:**
- A private Supabase Storage bucket. The hub issues a signed upload URL (valid 2 h) and signed download URLs valid 5 minutes.
- Bytes never pass through Vercel, which caps request bodies at 4.5 MB.
- Needs `SUPABASE_SECRET_KEY` on Vercel. Yang adds it.

**Receiving:**
- A toast, plus a Files tab in Super Team.
- **Save** writes only into `<repo>/.superagents/inbox/<share>/`, which is listed in `.git/info/exclude`.
- File names are cleaned (so `..\.git\hooks\pre-commit` can't get through) and nothing is overwritten.
- The agent moves files into place and commits only with approval.
- Shared files are untrusted input for agents.

**Limits:**
- 25 MB per file; shares expire after 14 days and are deleted through the Storage API.
- Free tier: 1 GB stored and 5 GB of downloads a month. Downloads are the real limit.

**Privacy (D2):** this is the first feature that sends file contents off the laptop.
- Each share is an explicit action.
- It's on the record: who shared what with whom.
- A secret scan runs before upload.
- The README's privacy section changes in the same PR.

**Code goes by git, not files:** **Hand off a branch** pushes it, and the teammate's agent checks it out in a worktree.

**Verify:** tests for the signed-URL flow and for path traversal; a walkthrough with two app instances.

### 4. Windows computer use without taking over the screen (about 4–5 days)
**What the agent sees:**
- the target window's UI Automation tree as text: role, name, value, state and ref;
- cached, and trimmed to what's visible.

**How it acts,** fewest side effects first:
1. The app's own API or command line. UFO² showed this adds 6–8 points and cuts up to 58% of steps.
2. UIA patterns: Invoke, Value, Toggle, Select, Expand, Scroll. These work **without moving the mouse or stealing focus**, which is the gap Claude Code and Codex leave on Windows.
3. Keyboard and mouse input, only when there's no pattern.
4. Vision when the tree is empty (canvas apps, games, remote desktops):
   1. Qwen3.8-27B on Nebius serverless: Apache-2.0, $0.45/$3.00 per million tokens, about $1 per 1,000 screenshots (estimate).
   2. `qwen3.5:4b` on Ollama, which fits this 4 GB GPU.
   3. Nemotron 3 Nano Omni, free on OpenRouter but rate-limited.

**Library:**
- `uiautomation` (Apache-2.0) in-process, as already probed. Borrow UFO²'s ideas (MIT); don't embed it, because it pins old dependencies.
- Windows-MCP (MIT) could run as a connector instead, but it sends telemetry by default and ships PowerShell and Registry tools.

**Safety:**
- Per-app grants with tiers:
  - browsers: use the agent browser instead;
  - terminals and IDEs: click only;
  - settings, security apps, password managers and banking: never.
- It never types credentials. It can't approve UAC prompts (UIA can't drive elevated windows).
- An overlay shows which app is under control; a global key stops everything.
- Every action is logged with before and after thumbnails.
- The reviewer (5) checks risky actions.

**Replay:** a successful run saves as a routine (UIA steps plus checks) that reruns with no model calls. It re-plans only when an element is missing.

**Verify:**
- 6–8 desktop tasks, measuring success, steps and seconds.
- The same tasks in Claude Code's computer use on this laptop, for a side-by-side.

### 5. Guardrails and evals (about 1.5 days, alongside 2 and 4)
**Reviewer:** before a risky action (submit, send, delete, push, or input outside the granted app), Nemotron Lightning sees the action and its context and answers allow, ask or block. All three hosted bots and Claude have something like this.

**Deterministic guards:**
- the same action three times in a row stops the run;
- "done" without a check gets asked once, like the remember nudge.

**Evals:**
- 20 fixed tasks: 8 browser, 6 desktop, 6 team or git.
- Run with real Nemotron; publish success, steps, seconds and tokens.
- Run the same tasks in Claude Code.
- No "better than" claim without these numbers.

### Later (after 30 Oct)
- Scheduled routines, built on replay.
- Using the person's own signed-in browser through an extension.
- A separate Windows desktop for fully background computer use.
- The GitHub App with the device flow.

## 5. Timeline to 30 Oct
| Dates | Work |
|---|---|
| 14–15 Oct | 1 (git, Get the project) |
| 16–19 Oct | 2 (browser), browser evals, the reviewer |
| 20–21 Oct | 3 (files) |
| 22–26 Oct | 4 (desktop), desktop evals |
| 27–30 Oct | Freeze: eval numbers, demo video, submission |

Production has to be shipped this week (#21→#27, migrations v2–v4, hub deploy), or the demo runs against a hub without these features.

If time runs short, cut 4 down to reading the UIA tree and acting by name: no vision, no replay.

## 6. Flags
1. **The name.** "Agent S" is Simular's open-source computer-use agent (Agent S3: 72.6% on OSWorld, 56.6% on Windows Agent Arena; Apache-2.0, which grants no trademark rights). Shipping computer use under the same name invites confusion. Rename before 4 ships.
2. **Hackathon model rule (D6).** The vision fallback, Qwen3.8 on Nebius, isn't an NVIDIA model. Nemotron stays the brain for every step. If the rules turn out to be NVIDIA-only, use Nemotron 3 Nano Omni; it was removed from Nebius serverless on 31 Aug.
3. **Safety.** Desktop control is the riskiest feature the app will have. The rules in 4 are not optional.
4. **Free tiers.**
   - Supabase pauses a project after 7 idle days, and the download allowance is 5 GB a month.
   - Vercel Hobby is non-commercial.
   - Nebius rotates its vision models: keep model IDs in config.
5. **Sources.** Competitor facts come from vendor docs and week-old reviews. Several top benchmark scores are self-reported.

## Proposed decisions (into PLAN.md once agreed)
- **D22:** the agent browser is Playwright plus the installed Edge with its own profile, text first (refs), with a live view. Never the app's WebView2.
- **D23:** Windows computer use is UIA first, with no screen takeover. Vision is only a fallback (Qwen3.8-27B on Nebius → Ollama 4B). Strict grants, a reviewer and a kill key.
- **D24:** git runs through the laptop's git, Git Credential Manager and `gh`. No GitHub token in the app.
- **D25:** files are shared through private Supabase Storage with signed URLs, saved only into `.superagents/inbox/`. Each share is explicit and on record; 25 MB, 14 days.
- **D26:** rename "Agent S" before computer use ships.

## Sources (accessed 13 Oct 2026)
**Hosted bots**
- [AIMultiple, 30 Sep](https://aimultiple.com/always-on-agents)
- [Grok Bot docs](https://docs.x.ai/grok-bot/overview), [FAQ](https://docs.x.ai/grok-bot/faq), [security](https://docs.x.ai/grok-bot/security)
- [Cursor forum, 8 Oct](https://forum.cursor.com/t/local-computer-use-for-grok-bots/174043)
- [Meta Muse, 8 Sep](https://about.fb.com/news/2026/09/introducing-muse-personal-ai-agent/)
- [dots review, 30 Sep](https://www.eesel.ai/blog/openai-dots-review)

**Coding tools**
- [Claude Code desktop](https://code.claude.com/docs/en/desktop), [computer use](https://code.claude.com/docs/en/computer-use), [Chrome](https://code.claude.com/docs/en/chrome)
- [Codex browser](https://learn.chatgpt.com/docs/browser), [computer use](https://learn.chatgpt.com/docs/computer-use), [changelog](https://learn.chatgpt.com/docs/changelog)
- [Cursor 3.0](https://cursor.com/changelog/3-0)
- [Antigravity 2.0](https://antigravity.google/blog/introducing-google-antigravity-2)
- [Playwright MCP vs CLI tokens](https://bug0.com/blog/playwright-cli-vs-playwright-mcp-ai-browser-testing-2026)

**Benchmarks**
- [OSWorld board](https://presenc.ai/research/osworld-computer-use-leaderboard-2026)
- [Windows Agent Arena](https://arxiv.org/abs/2409.08264)
- [CUA-Skill](https://arxiv.org/abs/2601.21123)
- [Agent S](https://github.com/simular-ai/Agent-S)

**Building blocks**
- [UFO²](https://arxiv.org/html/2504.14603v2)
- [Windows-MCP](https://github.com/CursorTouch/Windows-MCP)
- [uiautomation](https://pypi.org/project/uiautomation/)
- [Playwright WebView2](https://playwright.dev/python/docs/webview2)
- [Qwen3.8-27B on Nebius](https://tokenfactory.nebius.com/models/catalog/image2text/Qwen%2FQwen3.8-27B)
- [Nebius deprecations](https://docs.tokenfactory.nebius.com/august-2026-deprecation-notice.md)

**Files and git**
- [Supabase pricing](https://supabase.com/pricing), [file limits](https://supabase.com/docs/guides/storage/uploads/file-limits), [signed upload URLs](https://supabase.com/docs/reference/python/storage-from-createsigneduploadurl)
- [Vercel limits](https://vercel.com/docs/functions/limitations)
- [Git Credential Manager](https://github.com/git-ecosystem/git-credential-manager/blob/main/docs/install.md)
- [PR query parameters](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/using-query-parameters-to-create-a-pull-request)
- [GitHub App user tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app)
