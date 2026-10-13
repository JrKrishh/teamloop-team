# Finding 5 outside teams (PLAN.md §20)

**The ask:** connect for 2 days, then tell us one thing it got wrong. **Deadline:** 5 names by Oct 15, at least 3 connected by Oct 24.

## Who to ask, in order
1. **neatHack teams you already know from the Discord.** They just shipped with AI agents, under time pressure, in teams.
2. **Nebius × NVIDIA hackathon teams** in the Devpost or Discord team-finding channels. They live this exact problem for the next 17 days.
3. **Friends or freelance contacts with 2–6 developers** who each use Claude Code, Codex or Cursor.
4. **Your own teams, past and present.** A lead and one teammate is enough.

**Skip:** solo developers (there's no team to see) and big companies (onboarding is too slow).

## Message 1: Discord or DM (short)
> Hey! We're building TeamLoop for the Nebius × NVIDIA hackathon. If your team codes with Claude Code or Codex, it shows the lead each task's live progress: what's done, what's next, what's blocked. Nobody types a status update. It reads your agent's session events and only shares short summaries; prompts and code never leave your laptop.
>
> Looking for 3–5 small teams to try it for 2 days. Setup is about 2 minutes per person. All we ask is one thing it got wrong. Interested?
>
> Demo board (sample team): https://teamloop.vercel.app

## Message 2: once they say yes
> Thanks! It's one Windows program (no Python needed). Releases: https://github.com/JrKrishh/teamloop-team/releases
>
> **Lead, once:**
> 1. Download `teamloop-0.1.1-windows-x64.zip`, unzip it, and run `install.ps1` in that folder (`powershell -ExecutionPolicy Bypass -File install.ps1`).
> 2. Run `teamloop hub`. It opens your board and prints a lead key and an invite. Data stays on your machine.
> 3. For teammates on other machines: `cloudflared tunnel --url http://localhost:8799`, then restart with `teamloop hub --public-url <the https URL it prints>`, and share the new invite.
>
> **Each teammate:**
> ```
> teamloop login <INVITE> --name <your name>
> cd your-repo
> teamloop init
> teamloop task T-1 "what you're working on"
> ```
> Then code as usual with Claude Code or Codex. The board fills in by itself. `teamloop doctor` names the fix if anything's off, and `teamloop pause` stops all sharing.
>
> **What leaves your laptop:** one-line summaries, file names, test pass/fail, commit ids. Never prompts, code, diffs or tool output. Mac/Linux: `pipx install "git+https://github.com/JrKrishh/teamloop-team#subdirectory=connector"` gives the same commands.

## Message 3: after 2 days
> How did it go? Three quick questions:
> 1. One thing it got wrong?
> 2. Did you skip a status message or a check-in because of it? Roughly how many?
> 3. Would you keep it running? Why or why not?

## What to record (for the judges' "potential impact")
| Team | Size | Tools | Connected | Sessions tracked | Pings avoided (their estimate) | One thing wrong | Quote |
|---|---|---|---|---|---|---|---|

## Ready to post
**X (279 characters, links counted as 23):**
> TeamLoop, for the @nebiusai x @NVIDIAAI hackathon: your team codes with Claude Code or Codex; the lead sees every task's live progress on one board. No status updates. Nemotron cites the evidence for each claim.
> Demo: https://teamloop.vercel.app
> Want to try it with your team? DM me.

**Discord (hackathon / builder channels):** Message 1 above, plus the release link.

