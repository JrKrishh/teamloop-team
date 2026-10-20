# Releasing Super Agents

Everything ships under one version: the desktop app, the connector inside it, both hubs, Agent S and the phone app.

1. **Version.** Set the new version in `app/superagents/__init__.py`, the five `pyproject.toml` files (`agent_s`, `app`,
   `cloud`, `connector`, `hub`), `cloud/cloud/__init__.py`, `connector/teamloop/__init__.py`, `hub/hub/__init__.py` and
   `android/app/build.gradle.kts` (`versionName`; also raise `versionCode` by one, or Android won't install it over the
   last one). `app/tests/test_versions.py` fails until they all agree.
2. **Tests.** Every package's suite (README → Tests) and the Android unit tests (`cd android && ./gradlew testDebugUnitTest`).
   Then click through the app against a local hub: every view, the agent editor, a task, the side panes.
3. **Hub database first.** A release that adds a block to `cloud/cloud/migrations.sql` needs it in production before
   the hub that uses it: run each new `-- teamloop_cloud_vN_…` block in Supabase (the SQL editor, or `apply_migration`
   with the block's name). Every statement is safe to run twice. Production has v1 to v6 (14 Oct); v7 (team rules) and
   v8 (waitlist) are waiting.
4. **Hub deploy.** The Vercel project isn't connected to GitHub, so a push deploys nothing. From the repo root:
   `vercel deploy --prod --skip-domain --yes`, open the new deployment's `/healthz` (it shows the version), then promote
   it. The hub also serves the website (`cloud/cloud/site`), so site changes go out the same way. The hub is invite only:
   people already in a team can start more, and `HUB_TEAM_CREATORS` on Vercel (emails, comma-separated) lets others
   start their first one.
5. **Builds.** Push the tag `v<version>`. CI builds `SuperAgents-Setup.exe` (and installs, opens and uninstalls it on a
   clean Windows machine) and the APK. Download both artifacts from that run.
6. **Release.** `gh release create v<version> SuperAgents-Setup.exe SuperAgents-android.apk`, with exactly those asset
   names: the invite page links to `releases/latest/download/<name>`.

## Known gaps
- **The APK is signed with CI's debug key**, which changes between runs, so a new APK may need the old one uninstalled
  first. A release key (kept as a CI secret) fixes it.
- **The installer isn't code-signed**, so Windows SmartScreen warns on first open. SignPath Foundation signs open-source
  projects for free.
