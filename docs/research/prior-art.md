# TeamLoop: Prior Art (as of 12 Oct 2026)

## Verdict

1. The edges of this space are crowded, but no product does the exact combination: live, per-task progress from developers' **local** Claude Code / Codex / Cursor sessions, shown to a lead, shared as summaries rather than transcripts.
2. The closest product is **Entire** (Thomas Dohmke, $60M seed). It captures sessions from 8+ agents, offers `entire recap --view team`, and writes LLM "Dispatches" status summaries. It is commit-anchored (after the fact), though, and pushes full redacted transcripts to the git remote.
3. **GitHub** (Agents tab, session status in Issues/Projects) and **Linear** (agent sessions on issues) already give leads live, task-linked progress, but only for agents *they* run in the cloud.
4. Vendor analytics (Anthropic, Cursor, OpenAI) and engineering analytics (Swarmia, GitKraken, Factory) are single-vendor or daily aggregates. AgentMon Start (5 Oct 2026) is cross-tool with a team view, but tracks cost and security, not progress.
5. The gap is real but thin: one feature from Entire or GitHub could close it, and the vibe-kanban shutdown shows free dev-tool usage rarely turns into revenue.

## Comparison

| Product | What it does | Team / lead view | Cross-tool | Live? | Privacy model | OSS / price |
|---|---|---|---|---|---|---|
| **Entire** (CLI + entire.io) | Checkpoints link sessions to commits; `recap` (you/team); Dispatches = LLM status summaries across repos; entire-graph = local code graph | Yes: orgs, team recap, Dispatches | Yes: Claude Code, Codex, Cursor, Copilot CLI, Droid, OpenCode, Antigravity, Pi | No, captured at commit (`entire status` is local) | Redacted full transcripts pushed via git; readable by anyone with repo access. Can keep local | CLI MIT (~5.2k stars). Price not published |
| **GitHub** Agent HQ / Agents tab | Copilot, Claude, Codex cloud agents; repo Agents tab lists all sessions; Issues/Projects show status (Mar 2026); `/chronicle` standups (individual, Jun 2026) | Yes, per repo | Partial: Claude/Codex only *as GitHub cloud agents*; local Claude Code / Cursor not covered | Yes | Full logs on GitHub; local Copilot sessions private unless shared | Proprietary. Copilot Pro+/Enterprise (Feb 2026 preview) |
| **Linear** agents / Coding Sessions | Delegate issues to Codex, Cursor, Linear Agent (Claude Code/Codex). Agents post activities and plans to the issue | Yes (multiplayer) | Yes, but only agents integrated via Linear's Agent API, running in cloud sandboxes | Yes | Activity lives in Linear | Proprietary. Plan for Coding Sessions unverified |
| **Claude Code analytics** (Anthropic) | DAU, sessions, accept rate, PRs/lines "with CC", leaderboard, OTel export | Admins | No | No (~24h, daily) | Aggregates only | Team/Enterprise. Analytics API Enterprise-only |
| **Cursor** analytics + shared transcripts | AI share of committed code, leaderboard, cloud-agent counts. Manual team-shared transcripts | Admins | No | No (aggregates) | On-device classification, aggregate counts | Teams/Enterprise. Admin/Analytics APIs Enterprise |
| **OpenAI Codex** analytics | Adoption by surface (CLI/IDE/cloud), per-user ranking, Analytics/Compliance APIs | Admins | No | No (lag up to 12h per docs snapshot) | Aggregates. Compliance API logs | ChatGPT Business/Enterprise. API on request |
| **AgentMon Start** (Codenotary, 5 Oct 2026) | Reads local session logs of 16+ agents. Traces, spend, security alerts | Yes (opt-in org sync, viewer role) | Yes | Near-live (60s alerts). No progress summaries | Local SQLite. Org sync previewed, "pseudonymous" | Proprietary. From $15/user/mo, 3 devices free for 6 months |
| **Datadog Agent Console** (preview) | Usage/cost for Claude Code, Cursor, Copilot | Yes | Yes | Metrics | Telemetry | Datadog customers |
| **MintMCP Agent Monitor** | Prompts, commands, file access, MCP calls, guardrails, SIEM export | Yes | Yes (Claude Code, Cursor, Codex, Copilot) | Yes (security) | Captures prompts (governance, not privacy-first) | Proprietary. Price unverified |
| **Swarmia** / GitKraken Insights / Factory Analytics / Jellyfish / LinearB | AI adoption, AI-assisted PR tagging, cost/ROI. Factory "Agent Effectiveness" links Droid sessions to issues/PRs | Yes | Swarmia: Copilot, Cursor, Claude Code, Codex. Others vary (Jellyfish/LinearB detail unverified) | No (daily) | Aggregates | Paid |
| **vibe-kanban** (Bloop) | Kanban + worktrees for 10+ agents | Removed: Bloop shut down 10 Apr 2026, cloud/org features ended | Yes | Yes (own machine) | Local | Apache-2.0, ~28k stars. Community-maintained |
| **Claude Squad / Conductor / Crystal→Nimbalyst / Terragon** | Run parallel agents in worktrees | No (single user) | Claude Squad: Claude/Codex/Gemini/Aider. Conductor: Claude Code/Codex/Cursor (Mac) | Yes (own machine) | Local | Squad AGPL-3.0. Conductor free app. Crystal discontinued Feb 2026. Terragon shut down (date unverified) |
| **Devin / Devin Desktop** (ex-Windsurf) | Agent Command Center board of local + cloud sessions | Individual board. Org-wide session visibility unverified | No | Yes | Cognition cloud / VPC | Proprietary |
| **Amp** | Agent threads shared with the workspace by default | Yes | No | Yes | Full threads shared | Proprietary |
| **Langfuse** (Claude Code plugin) / AgentOps / neatlogs | LLM tracing. Langfuse Stop-hook uploads Claude Code transcripts per developer | Dashboards, no progress view | Langfuse: Claude Code only | Near-live | Full transcripts uploaded | Langfuse OSS core. neatlogs/AgentOps target agent apps, not coding sessions (AgentOps unverified) |
| Small OSS (ai-team-sync, AI Team OS, AgentPulse, ccboard) | Session locks, task walls, local dashboards | Some (experimental) | Partial | Yes | Local | MIT etc. Negligible traction |

Not relevant: **Graphite** (bought by Cursor Dec 2025; code review, no session tracking). **Sweep** (JetBrains assistant; releases stalled since Feb 2026, third-party source).

## Gap: where TeamLoop can win

- **Live, per-task progress before a commit or PR exists.** Nobody answers "how far is X on task Y?" from a local session. Entire waits for commits; GitHub and Linear see only agents they host; analytics lag 12–24h.
- **The task as the unit.** Entire proves cross-agent hooks are workable (it publishes an Agent Integration Protocol) but has no concept of an assigned task, blocker or "awaiting input".
- **Privacy-first summaries.** Others share full transcripts (Entire, Amp, Langfuse, GitHub logs, MintMCP) or only aggregates. TeamLoop: summarize on the developer's machine, developer previews before sending, raw transcripts never leave.
- **Small teams on free plans.** Codex, Cursor and Claude analytics APIs are Enterprise-gated; Copilot team metrics exclude teams under 5 seats.
- **Reuse before building:** ingest Entire checkpoints and Claude Code OTel instead of writing every hook (fit unverified).

## Threats

1. **Entire ships a live, per-person Dispatch.** It already has orgs, team recap, MCP, 8+ agent integrations and $60M. Highest risk.
2. **GitHub opens the Agents tab to third-party local sessions.** Copilot local-session sync exists; extending it puts the lead view where PRs and CI already live.
3. **Linear/Jira own the task.** Leads already look there, and Linear's Agent API lets any agent post progress. TeamLoop may fit better as a Linear integration than a separate dashboard.
4. **Existing collectors** (AgentMon, MintMCP, Datadog) can add LLM summaries as a small feature.
5. **Fragile hooks.** Cursor, Codex and Gemini hook formats differ and change, so each tool is ongoing maintenance.
6. **Adoption.** Every teammate must install it and accept tracking ("bossware"). Useless with one user.
7. **Monetization.** vibe-kanban (~28k stars) shut down its company because free users did not convert; Terragon and Crystal also ended.

## Sources

- Entire: https://github.com/entireio/cli · https://docs.entire.io/guides/dispatches/overview.md · https://docs.entire.io/cli-reference/recap.md · https://docs.entire.io/guides/sessions/list-sessions.md · https://docs.entire.io/security.md · https://pkg.go.dev/github.com/entireio/entire-graph · https://entire.io · https://sdtimes.com/softwaredev/startup-entire-launches-distributed-git-network-for-the-agent-era/ (Jul 2026)
- GitHub: https://github.blog/changelog/2026-01-26-introducing-the-agents-tab-in-your-repository/ · https://docs.github.com/en/copilot/how-tos/copilot-on-github/use-copilot-agents/manage-and-track-agents · https://github.blog/changelog/2026-03-26-agent-activity-in-github-issues-and-projects/ · https://github.blog/changelog/2026-06-02-gain-insights-across-your-agent-sessions-with-chronicle/ · https://github.blog/changelog/2026-02-04-claude-and-codex-are-now-available-in-public-preview-on-github/ · https://github.blog/ai-and-ml/github-copilot/how-to-orchestrate-agents-using-mission-control/ (Dec 2025) · https://github.blog/changelog/2026-05-14-team-level-copilot-usage-metrics-now-available-via-api/
- Linear: https://linear.app/coding-sessions · https://linear.app/developers/agent-interaction · https://linear.app/integrations/codex
- Anthropic: https://code.claude.com/docs/en/analytics
- Cursor: https://cursor.com/docs/account/teams/analytics · https://cursor.com/help/ai-features/shared-transcripts · https://cursor.com/docs/cloud-agent
- OpenAI: https://developers.openai.com/codex/enterprise/governance.md (now redirects to https://learn.chatgpt.com/docs/enterprise/governance)
- AgentMon Start: https://codenotary.com/blog/agentmon-start-ai-agent-monitoring-for-developers-and-teams
- Datadog: https://docs.datadoghq.com/ai_agents_console/setup/
- MintMCP: https://www.mintmcp.com/blog/claude-code-monitoring
- Swarmia: https://www.swarmia.com/product/ai-impact/ · GitKraken: https://www.gitkraken.com/blog/preview-launch-the-agent-impact-leaderboard-and-the-business-impact-roi-dashboard · Factory: https://www.factory.ai/news/agent-effectiveness
- vibe-kanban: https://github.com/BloopAI/vibe-kanban · https://www.vibekanban.com/blog/shutdown
- Claude Squad: https://github.com/smtg-ai/claude-squad · Conductor: https://www.conductor.build · Crystal: https://github.com/stravu/crystal · Terragon: https://www.terragonlabs.com
- Devin (third-party): https://apidog.com/blog/whats-new-in-devin-2026/ · Amp: https://ampcode.com/docs/collaborate/thread-sharing
- Langfuse: https://langfuse.com/integrations/developer-tools/claude-code · neatlogs: https://github.com/NeatLogs/neatlogs
- Small OSS: https://github.com/pvestal/ai-team-sync · https://github.com/CronusL-1141/AI-company
- Graphite: https://techcrunch.com/2025/12/19/cursor-continues-acquisition-spree-with-graphite-deal · Sweep (third-party): https://rywalker.com/research/sweep
