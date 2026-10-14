# Phone remote: prior art and the choices (13 Oct 2026)

Yang asked for "a mobile app like Claude Remote Control" for Super Agents. This is what's out there, and why the
remote is built the way it is (decision D27 in PLAN.md).

## What others do

- **Claude Code Remote Control** (Feb 2026): https://code.claude.com/docs/en/remote-control
  - **Access and transport:** access comes from the claude.ai login, with a session URL or QR code. The laptop makes outbound HTTPS only.
  - **Not end-to-end encrypted:** it is TLS only, and the transcript and tool activity are stored on Anthropic's servers.
  - **The phone** sends messages and files, watches live, answers permission prompts and stops tasks, and gets push notifications.
  - **Open issues:**
    - silent drops with no reconnect: https://github.com/anthropics/claude-code/issues/34255;
    - sessions dying after about 20 minutes idle (#32982);
    - permission prompts not rendering on mobile (#35637);
    - answers from mobile lost (#28508).
- **Happy** (MIT): https://github.com/slopus/happy
  - The relay stores and forwards encrypted blobs.
  - Each session has its own AES-256-GCM key, shared through a QR key exchange.
  - Push goes through Expo; the notification text is plaintext, outside the encryption.
- **Codex in the ChatGPT app:** cloud workspaces, plus "Remote" to a ChatGPT desktop host paired by QR through a relay.
  https://learn.chatgpt.com/docs/remote-connections
- **Cursor:** Cloud Agents run on Cursor's machines, reached from the web or a phone; its remote control moves the loop to the cloud.
  https://cursor.com/docs/cloud-agent/mobile
- **GitHub Copilot CLI** `/remote on`: events go through GitHub, and the mobile app approves.
  https://docs.github.com/en/copilot/concepts/agents/copilot-cli/about-remote-control
- **HAPI** (AGPL), the closest web-app prior art: a hub on your machine, SSE to a web app, a WireGuard relay, Web Push.
  https://github.com/tiann/hapi

## The platform facts that shaped it

- **iPhone Web Push** works only for a web app added to the home screen (iOS 16.4+), and only after a tap. No web app keeps
  a socket open in the background, so the pattern is push to wake, then resync.
  https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/
- **Supabase Realtime Broadcast**, public channels:
  - Anyone with the publishable key can join any public channel. That's why the channels are random and the messages sealed.
    https://supabase.com/docs/guides/realtime/settings
  - Free tier: 200 connections, 2M messages a month, 100 a second, 256 KB each. https://supabase.com/docs/guides/realtime/limits
  - It speaks the Phoenix protocol (vsn 1.0.0 JSON): https://supabase.com/docs/guides/realtime/protocol
- **Vercel** has had WebSockets in beta since June 2026, but each connection lives on one instance and closes at the
  function's maximum duration, so in-memory rooms don't work there.
  https://vercel.com/kb/guide/do-vercel-serverless-functions-support-websocket-connections

## What Super Agents does, and where it's better

- **End-to-end encrypted.**
  - The QR code's fragment carries a 256-bit key, and every message is AES-256-GCM sealed with the channel bound in.
  - Neither Supabase nor the hub can read a command, a file or an answer.
  - On the phone the key is a non-exportable WebCrypto key.
  - Claude Code's Remote Control stores transcripts on Anthropic's servers.
- **It doesn't lose things.**
  - The laptop never skips an event it failed to send.
  - The phone shows events strictly in order, asks for any gap, and catches up on a running turn after it lost the connection.
  - These are the failure modes in Remote Control's open issues.
- **Approvals are the main thing.** A step waiting for you stays in view, outside the folded steps. A turn started at the
  desk shows on the phone as "Agent S needs you".
- **No account wall:** any model the hub runs (Nemotron here), the free tier, and no app store.
- **Not yet:** push notifications (the next step: Web Push through the hub, with a generic payload such as "Agent S
  needs you" so nothing private leaves the seal), and a lock on the phone app itself (WebAuthn).
