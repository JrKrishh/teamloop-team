---
name: code-review
description: Review code changes like a senior engineer on the team. Use when asked to review a pull request, a branch, a diff or a teammate's work on a task; gives blocking issues first, with file and line.
---

# Code review

## Get the change
- A connected repo on this laptop: `git_diff` (uncommitted changes, or `base` such as `main` for the whole branch).
- A pull request: `github_pr` with `owner/repo` and the number.
- A teammate's work in progress: `prompt_session` into their session, asking for the diff and what they meant to do. It may wait for them to allow it; read the answer with `session_prompt`.
- The task's intent: `team_task` for its timeline, `team_board` for its owner and deadline.

Read the whole change before judging any part of it. If you can't see the change, say so; never review from a description.

## What to check, in order
1. **Correctness.** Does it do what the task says? Edge cases: empty, missing, huge, concurrent, failing. Off-by-one, wrong comparisons, unhandled errors, resources left open.
2. **Tests.** Is the new behaviour tested, including the failure path? Would the tests fail if the code were wrong?
3. **Security.** Input that reaches a shell, SQL, file paths or HTML; secrets in code or logs; permission checks on every new endpoint.
4. **Scope.** Every changed line should trace to the task. Flag drive-by refactors, speculative options and dead code.
5. **Simplicity.** Could it be half as long? Duplicated logic, needless abstraction, clever code that needs a comment to explain.
6. **Names and readability.** Only where they would mislead the next reader.

Don't comment on style a formatter would fix.

## How to report
Start with a one-line verdict: **ready**, **ready with small fixes**, or **needs changes**.

Then:
- **Blocking**: each with `file:line`, what is wrong, why it matters, and the fix.
- **Should fix**: same format, not blocking.
- **Questions**: things you couldn't decide from the code.

Quote the line you mean. Keep each point to two sentences. If there's nothing blocking, say so plainly.

If asked to, turn blocking issues into tasks with `create_task` (owner: the author; a deadline if the task has one). The person's mode decides whether those changes wait for approval.
