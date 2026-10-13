# Super Agents for Android, native (14 Oct 2026)

Yang: "make it like an authentic Android app … mascot animations, smooth motion, a startup screen, then an auth screen
like Claude Code's or Codex's remote control." This is the end-to-end plan; decision D29 in PLAN.md.

## Verdict
A native app in **Kotlin with Jetpack Compose and Material 3** replaces the Capacitor shell (D28), which never
shipped. The web app (`cloud/cloud/site/remote/`) stays for iPhones and browsers. The laptop side, the relay and the
protocol don't change: the native app speaks the same sealed messages.

## Why: what the Capacitor build showed on an Android 16 emulator (14/15)
- **No background notifications from the web layer.**
  - The WebView reports "visible" after Home.
  - Android freezes the app soon after it leaves the screen.
  - Even with a foreground service keeping the process alive, the Capacitor bridge didn't serve plugin calls in the
    background: a direct `LocalNotifications.schedule` hung.
  - "Agent S needs you" can't be raised from JavaScript in the background.
- **A web page in a frame doesn't feel like an Android app:** scrolling, gestures, motion, sheets, back, haptics.
- **Native gives:**
  - a real service that holds the line to the laptop;
  - notifications with **Approve / Deny buttons on the notification itself** (Claude Code's remote makes you open the
    app);
  - the key in Android Keystore (hardware-backed, never readable);
  - Material motion and predictive back.

## The experience
1. **Startup**
   - Android's splash shows the mascot on its brick circle.
   - Then a 1.3 s animation: the mascot drops in on a spring, squashes as it lands, its tuft wiggles, it blinks twice,
     and "Super Agents" rises under it.
   - Later launches get a 0.5 s version; a tap skips it.
2. **Connect** (the "auth" screen, like Claude Code's or Codex's remote control: you prove you're at the laptop):
   - The mascot waves. "Connect to your laptop", with three steps (open Super Agents, Settings → Phone, Pair a phone).
   - **Scan the pairing code** (Google's code scanner, no camera permission), or **Paste a link**.
   - A chip: "End-to-end encrypted. Only this phone and your laptop hold the key."
   - Connecting: the mascot looks around. Connected: "Paired with Yang's laptop", and the mascot jumps.
   - Then two cards: **Lock with fingerprint?** and **Let your agents reach you** (the notification permission,
     explained first).
3. **Home**: a Material 3 navigation bar (Needs you with a badge, Chats, Board) and a top bar with the laptop's status
   (online dot and name).
   - **Needs you:**
     - each question as a card with the command or the change;
     - swipe right to approve, left to deny, or tap the buttons;
     - haptics on both;
     - "Working now" under them, with each turn's current step;
     - nothing waiting: the mascot dozes.
   - **Chats:** search, one-tap questions (assist chips), chats by day, and a New chat button.
   - **Board:** Active, To do and Done; Agent S's estimate next to the coding agent's claim; tap a task for its sheet.
4. **A chat:**
   - messages, with the steps folded into one line that opens with a smooth expand;
   - questions inline, the plan footer, Markdown answers;
   - the composer with an agent and mode chip (a bottom sheet), and Send / Stop.
5. **Settings:** the laptop, the fingerprint lock, notifications, stay connected, forget the laptop, about.

The mascot carries the state across screens: it thinks (eyes dart) while a turn runs, hops when a question arrives,
sleeps when the laptop is offline, and celebrates a pairing.

## In the background
- **LinkService**, a foreground service of type `remoteMessaging`, holds the connection while the app is paired: the
  relay socket, a heartbeat, and a ping every 30 s so the laptop keeps pushing.
  - Android shows a quiet, ongoing "Connected to Yang's laptop" notification. Settings can turn it off.
- **A new question** posts a high-priority notification with **Deny** and **Run it** (**Approve** for anything but a command):
  - Run it and Approve require the phone to be unlocked;
  - the lock screen shows only "Agent S needs you";
  - tapping opens the chat.
- **An answer** posts "Agent S answered".
- **Later:** Firebase push for when the service is off. It needs a free Firebase project from Yang.

## Security
- **The key:** the pairing key is imported into Android Keystore, so it can't be exported. AES-256-GCM, with the
  channel as associated data, as on the laptop and the web app.
- **Relay and replays:** the same stale, replay and reflection checks as the web app; nothing private on the lock
  screen; no message text in logs.
- **Lock and network:** the fingerprint lock uses BiometricPrompt with a PIN fallback, on opening and after a minute
  away. Plain HTTP only to loopback (a dev hub through `adb reverse`, which never leaves the phone), HTTPS to everything else;
  debug builds also allow the emulator's 10.0.2.2.

## Build
- **Where:** `android/` at the repo root, Gradle (Kotlin DSL), SDK 36 (min 26), JDK 21. Kotlin, Compose BOM,
  Material 3, OkHttp (WebSocket), androidx.biometric, core-splashscreen, and Google's code scanner.
- **The mascot** is drawn in Compose from `brand/mark.svg`'s own paths: no image files, any size, every frame animated.
  The fonts are the desktop's (Bricolage, Figtree, JetBrains Mono).
- **CI:** the `apk` job runs the JVM tests and builds the shrunk release APK, debug-signed until there's a release key.

## Checked by
- **JVM tests:** the seal opens what the laptop's Python code sealed, with a fresh nonce each time (every message in
  the end-to-end run proves the other direction); pairing links; event ordering and gaps; the step labels.
- **The emulator (Android 16), end to end with real Nemotron:**
  - pair by link; the screens via UI Automator;
  - a turn from the app, approved in the chat;
  - a turn from the desk, approved from the notification's **Run it** button with the app in the background;
  - Board, back, settings, and screenshots of each screen.

## Results (14 Oct)
- **End to end on the emulator, with real Nemotron:** 15/15 each, on the debug build and the release build (R8).
  The first release run failed at pairing: release builds refused plain HTTP to the dev hub. Loopback is now
  allowed in every build.
- **Size:** the release APK is 2.8 MB (R8); the debug build is 15 MB, and the Capacitor debug build was 31 MB.
- **Cold start** on the software-rendered emulator: 1.4–2.5 s release, 4.1–4.4 s debug; 2.8–4.8 s for the first
  launch after an install. The intro waits for Android's splash to leave before the mascot drops, so the drop is
  seen even on a slow first launch (it used to play under the splash).

## Not in this round
Firebase push, App Links (needs `assetlinks.json` on the hub with the release key), release signing, a Play Store
listing, an iPhone app.
