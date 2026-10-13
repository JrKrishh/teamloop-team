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

## Message 2: once they say yes
> Thanks! Here's everything:
> 1. The lead opens the board: <HUB URL> (room: `<room>`, token: sent separately)
> 2. Each teammate runs:
>    ```
>    pipx install "git+https://github.com/JrKrishh/teamloop-team#subdirectory=connector"
>    teamloop login <INVITE>
>    cd your-repo && teamloop init
>    teamloop task T-1 "what you're working on"
>    ```
> 3. Code as usual. The board fills in by itself. If something breaks, `teamloop doctor` names the fix, and `teamloop pause` stops all sharing.
>
> **What leaves your laptop:** one-line summaries, file names, test pass/fail and commit ids. Never prompts, code, diffs or tool output.

## Message 3: after 2 days
> How did it go? Three quick questions:
> 1. One thing it got wrong?
> 2. Did you skip a status message or a check-in because of it? Roughly how many?
> 3. Would you keep it running? Why or why not?

## What to record (for the judges' "potential impact")
| Team | Size | Tools | Connected | Sessions tracked | Pings avoided (their estimate) | One thing wrong | Quote |
|---|---|---|---|---|---|---|---|

## Before sending Message 2, we need
- **A deployed hub URL** (docs/deploy.md: needs your Hugging Face account).
- **The repo public, or the testers added as collaborators.** `pipx install git+…` doesn't work on a private repo. Going public early also counts toward the OSS-repo rule.
- **A room per team** (`CCBRIDGE_ROOMS=teamA:<token>,teamB:<token>`) and an invite each (`teamloop invite`).
