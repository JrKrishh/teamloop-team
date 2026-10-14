# Multiplayer agents in Super Agents

Super Agents is multiplayer by design, and local-first: each person's agents run on their own laptop with their own
sign-ins, and the team shares what they do (progress with evidence, prompts into each other's sessions, files and
branches) through the hub. This page maps a generic "multiplayer agent system" plan (cloud rooms, durable workers, a
shared sandbox, CRDT canvases, 12 weeks) onto what Super Agents has, what was built from it, and what's parked and why.

## Where each part of the plan stands

| The plan | In Super Agents | Status |
|---|---|---|
| An append-only event log, and the state compiled from it | The hub keeps every laptop's coding-session events; the board, Agent S's progress estimates and its cited answers are built from them | Have it |
| An agent that keeps working when the person who prompted it walks away | Turns run on the laptop that has the code; the phone follows a turn, answers its questions, switches its mode and stops it | Have it, on the laptop by design |
| A shared cloud sandbox every participant works in | | Won't build: code leaving the laptops breaks the product's promise, and cloud workers cost money |
| Mid-flight steering | Switch Manual, Auto or Plan while it runs (T-49); type a note while it works, at the desk or on the phone, and it's read before the next step (T-52) | Built |
| Hard interrupt | Stop, at the desk or on the phone | Have it; no rollback (in Manual, changes wait for a yes anyway) |
| A team prompt queue | On the desktop, a note sent just as an answer finishes goes as the next message | Partly; a visible queue when someone asks for it |
| A human backchannel, "promote to agent context" | | Parked: teams already talk in Slack or Teams |
| A private vault with taint tracking | Prompts, code, diffs and tool output stay on each laptop; only one-line summaries and facts reach the team | Have it, by design |
| Session state with pinned decisions | Memory notes (per laptop, for one agent or all); plan mode | Next: team-wide decisions on the hub, in every agent's prompt with who decided |
| Institutional memory | `team_ask` answers from the team's events with citations; recall over earlier chats and coding sessions | Have it |
| An agent identity, permissions as an intersection | Each laptop's tools run with that person's own sign-ins; a teammate's prompt into your session runs by your rules (read only, or edits in that repo), never shell commands | Have the essentials |
| Role-routed approvals | A step waits for whoever runs the agent, at the desk or on the phone; a teammate's prompt into your session waits for your yes | Have it for sessions; routing a step to the lead is parked |
| A CRDT canvas with presence cursors | | Parked |
| Speculative forking of a session | | Parked |
| A catch-up briefing for whoever joins | Today's digest; each task's timeline of what each session reported | Partly |

## Why local-first

The plan moves the agent loop and its tools into a cloud sandbox so every participant sees the same runtime. Super
Agents keeps the loop where the code is and shares outcomes instead: what each agent did, with evidence, and a yes or a
note from whoever is responsible. That keeps code on the laptops, costs nothing to run, and still lets a lead see and
steer the team's agents.
