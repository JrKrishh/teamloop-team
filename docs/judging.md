# Trying Super Agents (judges)

Super Agents is a Windows desktop app (Windows 10 or 11) with an Android companion. Sign-in details are in the
submission's testing instructions on Devpost.

1. Download `SuperAgents-Setup.exe` from the [latest release](https://github.com/JrKrishh/teamloop-team/releases/latest)
   and open it. It isn't code-signed yet, so Windows may say it protected your PC: choose **More info → Run anyway**.
   It installs for your Windows user, no admin needed.
2. Under **or with email**, sign in with the email and password from Devpost.
3. You're a lead in **Acme Web (demo)**, a team of three whose coding sessions are already on the board:
   - **Board:** Agent S's progress on each task from the developers' Claude Code and Codex sessions, every claim citing
     the events behind it (open a task for its timeline). T-22 is blocked, and the evidence is Ravi's own session.
   - **Chat:** ask Agent S "What's blocked right now?" or "Plan T-24 with owners and deadlines" (Plan mode queues the
     changes; nothing runs until Run plan). Every answer runs on NVIDIA Nemotron through Nebius Token Factory.
   - **Super Team:** Asha's agent waits for a lead's yes to push (the team's rules), the team's pinned decisions, and
     prompts teammates sent into each other's coding sessions, on the record.
4. To see your own work: **This laptop → Connect a folder** with a git repo, then use Claude Code or Codex in it as
   usual. Each turn shows up on the board within seconds.
5. Optional, Android: install `SuperAgents-android.apk` from the same release and pair it from the desktop's
   **Settings → Phone**. Questions from running agents reach the phone; swipe right to allow.

No Windows machine? The video shows each of these flows in the real app.

## Keeping the demo ready (maintainers)
1. Create the judges' account in the app (**New here? Create an account**, email and password) and sign in once.
2. Seed the demo team with both accounts as leads, against the hosted hub's database:
   `DATABASE_URL=... python scripts/seed_demo_team.py --lead <your email> --judge <judges' email>`
3. Run it again on 30 Nov: its times are relative to when it runs, so the demo looks current during judging (1–15 Dec).
4. The daily keep-alive (`.github/workflows/keepalive.yml`) keeps the free database from pausing; a red run means the
   hub is down.
