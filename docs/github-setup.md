# Connect GitHub to a TeamLoop hub

PRs, reviews, CI runs and commits then attach to tasks on the board:
- an open PR moves a task to **review**;
- a merged PR moves it to **done**;
- a failing CI run shows red on the card.

## 1. Hub settings
```bash
GITHUB_WEBHOOK_SECRET=<long random string>           # the same value goes into GitHub
HUB_GITHUB_REPOS=owner/repo=teamloop,owner/other=teamloop
```

## 2a. Quickest: a repo webhook (one repo)
1. Open the repo's **Settings → Webhooks → Add webhook**.
2. Fill in:
   - **Payload URL:** `https://<your hub>/v1/github`
   - **Content type:** `application/json`
   - **Secret:** your `GITHUB_WEBHOOK_SECRET`
3. Under **Events**, choose these: *Pull requests*, *Pull request reviews*, *Workflow runs*, *Check suites*, *Pushes*.

## 2b. Several repos: a GitHub App (PLAN.md D10)
1. Create the app under **Settings → Developer settings → GitHub Apps → New**.
2. Set the same webhook URL and secret.
3. Give it read-only permissions: Pull requests, Checks, Actions, Contents.
4. Subscribe to the same events, then install it on the repos you want.

## How tasks are matched
1. A `TeamLoop-Task: T-14` trailer on a commit. `teamloop git-hook install` adds it to the commits a coding agent makes,
   and only those: a pushed commit without it was made by hand and isn't shown, since Super Team follows agents' work.
2. For pull requests, reviews and checks: a task id in the branch name, e.g. `T-14-github-webhooks`.
3. Otherwise, a task id in the PR title.

Events with no task are ignored. Redeliveries are safe, because ids come from `X-GitHub-Delivery`. GitHub's own `ping` gets a pong.
