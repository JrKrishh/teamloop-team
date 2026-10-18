package com.solobrain.superagents.remote

import org.json.JSONObject

/** How a tool call reads to a person ("Run npm test"), and how a turn's folded steps sum up ("Read 3 files, ran a
 *  command"). The same words as the desktop and the web app. */
object Labels {
    // every built-in tool, as the desktop's TOOL_UI says it (app/tests/test_runtime.py keeps both complete)
    private val LABEL: Map<String, Pair<String, (JSONObject) -> String>> = mapOf(
        "team_board" to ("Read the board" to { _ -> "" }),
        "team_ask" to ("Ask the team's history" to { a -> a.optString("question") }),
        "team_task" to ("Read task" to { a -> a.optString("task") }),
        "team_usage" to ("Read the team's AI usage" to { a -> if (a.optInt("days") > 0) "last ${a.optInt("days")} days" else "" }),
        "create_task" to ("Create task" to { a -> a.optString("title") + a.optString("owner").let { if (it.isEmpty()) "" else " · $it" } }),
        "assign_task" to ("Assign" to { a -> "${a.optString("task")} → ${a.optString("owner")}" }),
        "close_task" to ("Close" to { a -> a.optString("task") }),
        "start_task" to ("Start on this laptop" to { a -> a.optString("task") + a.optString("repo").let { if (it.isEmpty()) "" else " in $it" } }),
        "set_deadline" to ("Deadline" to { a -> "${a.optString("task")} · ${a.optString("due").ifEmpty { "none" }}" }),
        "pin_decision" to ("Pin a decision" to { a -> a.optString("text") }),
        "team_sessions" to ("Read teammates' sessions" to { _ -> "" }),
        "prompt_session" to ("Prompt a session" to { a ->
            "${a.optString("member").ifEmpty { a.optString("session") }.ifEmpty { "latest" }}: “${a.optString("prompt").take(40)}”" }),
        "session_prompt" to ("Check a prompt" to { a -> a.optString("id").take(8) }),
        "message_teammate" to ("Note for a teammate" to { a ->
            "${if (a.optString("to") == "task") "everyone on ${a.optString("task")}" else a.optString("to")}: “${a.optString("text").take(40)}”" }),
        "share_files" to ("Share" to { a -> "${a.optJSONArray("paths").strings().joinToString(", ")} with ${a.optString("to").ifEmpty { "everyone" }}" }),
        "share_branch" to ("Hand over the branch" to { a -> "to ${a.optString("to").ifEmpty { "everyone" }}" + a.optString("repo").let { if (it.isEmpty()) "" else " · $it" } }),
        "team_files" to ("Read what's shared" to { _ -> "" }),
        "take_share" to ("Take a share" to { a -> a.optString("id").take(8) + a.optString("repo").let { if (it.isEmpty()) "" else " into $it" } }),
        "list_files" to ("List" to { a -> a.optString("path").ifEmpty { "connected repos" } }),
        "read_file" to ("Read" to { a -> a.optString("path") }),
        "search_files" to ("Search" to { a -> "“${a.optString("query")}”" + a.optString("path").let { if (it.isEmpty()) "" else " in $it" } }),
        "write_file" to ("Write" to { a -> a.optString("path") }),
        "run_command" to ("Run" to { a -> a.optString("command") }),
        "git_status" to ("Git status" to { a -> a.optString("repo") }),
        "git_diff" to ("Diff" to { a -> a.optString("repo") + a.optString("base").let { if (it.isEmpty()) "" else " since $it" } }),
        "git_branch" to ("Branch" to { a -> a.optString("name") }),
        "git_commit" to ("Commit" to { a -> a.optString("message").lineSequence().firstOrNull().orEmpty() }),
        "git_push" to ("Push" to { a -> a.optString("repo").ifEmpty { "this branch" } }),
        "git_pull" to ("Pull" to { a -> a.optString("repo") }),
        "open_pr" to ("Open a pull request" to { a -> a.optString("title") }),
        "github_pr" to ("Read pull request" to { a -> "${a.optString("repo")}#${a.optInt("number")}" }),
        "fetch_url" to ("Read page" to { a -> a.optString("url") }),
        "dev_server" to ("Dev server" to { a -> a.optString("action").ifEmpty { "start" } + a.optString("repo").let { if (it.isEmpty()) "" else " · $it" } }),
        "browser_open" to ("Open" to { a -> a.optString("url") }),
        "browser_snapshot" to ("Read the page" to { a -> a.optString("find").let { if (it.isEmpty()) "" else "“$it”" } }),
        "browser_click" to ("Click" to { a -> a.optString("ref") + if (a.optBoolean("double")) " twice" else "" }),
        "browser_type" to ("Type" to { a -> "“${a.optString("text").take(40)}” into ${a.optString("ref")}" + if (a.optBoolean("submit")) " and submit" else "" }),
        "browser_select" to ("Choose" to { a -> "${a.optString("option")} in ${a.optString("ref")}" }),
        "browser_press" to ("Press" to { a -> a.optString("key") }),
        "browser_scroll" to ("Scroll" to { a -> a.optString("ref").ifEmpty { a.optString("direction").ifEmpty { "down" } } }),
        "browser_wait" to ("Wait for" to { a -> a.optString("text").ifEmpty { "${a.optInt("seconds", 5)} s" } }),
        "browser_screenshot" to ("Screenshot" to { _ -> "" }),
        "browser_console" to ("Read the console" to { _ -> "" }),
        "browser_eval" to ("Run in the page" to { a -> a.optString("code").take(60) }),
        "browser_batch" to ("Steps" to { a -> "${a.optJSONArray("steps")?.length() ?: 0} in one go" }),
        "desktop_windows" to ("List windows" to { _ -> "" }),
        "desktop_snapshot" to ("Read window" to { a -> a.optString("window").ifEmpty { a.optString("find").let { if (it.isEmpty()) "current" else "“$it”" } } }),
        "desktop_click" to ("Press" to { a -> a.optString("ref") + if (a.optBoolean("mouse")) " with the mouse" else "" }),
        "desktop_type" to ("Fill" to { a -> "“${a.optString("text").take(40)}” into ${a.optString("ref")}" + if (a.optBoolean("submit")) " and submit" else "" }),
        "desktop_select" to ("Choose" to { a -> "${a.optString("option")} in ${a.optString("ref")}" }),
        "desktop_scroll" to ("Scroll" to { a -> "${a.optString("ref")} ${a.optString("direction").ifEmpty { "down" }}" }),
        "desktop_press" to ("Keys" to { a -> a.optString("keys") + a.optString("window").let { if (it.isEmpty()) "" else " in $it" } }),
        "desktop_open" to ("Open app" to { a -> a.optString("app") }),
        "desktop_screenshot" to ("Screenshot" to { a -> a.optString("window") }),
        "desktop_batch" to ("Steps" to { a -> "${a.optJSONArray("steps")?.length() ?: 0} in one go" }),
        "remember" to ("Remember" to { a -> a.optString("note") }),
        "forget" to ("Forget a note" to { a -> a.optString("id") }),
        "recall" to ("Recall" to { a -> "“${a.optString("query")}”" + a.optString("where").let { if (it.isEmpty() || it == "everywhere") "" else " in $it" } }),
        "load_skill" to ("Use skill" to { a -> a.optString("name") }),
        "read_skill_file" to ("Read skill file" to { a -> "${a.optString("name")}/${a.optString("file")}" }),
    )

    fun of(name: String, args: JSONObject): Pair<String, String> {
        LABEL[name]?.let { (verb, what) -> return verb to what(args) }
        val n = Regex("^mcp__.+?__(.+)$").find(name)?.groupValues?.get(1) ?: name
        val words = n.replace('_', ' ').replaceFirstChar { it.uppercase() }
        val what = args.keys().asSequence().mapNotNull { args.opt(it) as? String }.joinToString(" · ").take(120)
        return words to what
    }

    fun line(s: Step): String = of(s.name, s.args).let { (v, w) -> "$v $w".trim() }

    /** The command or change itself, shown under a question. */
    fun detail(name: String, args: JSONObject): String = when (name) {
        "run_command" -> args.optString("command")
        "write_file" -> args.optString("content")
        "git_commit" -> args.optString("message") + "\n\n" + args.optJSONArray("files").strings().joinToString("\n")
        else -> if (args.length() == 0) "" else args.toString(2)
    }.trim()

    private val STEPS = listOf(
        Regex("^read_file$") to ("read a file" to "read # files"),
        Regex("^(search_files|list_files)$") to ("looked through the code" to "looked through the code # times"),
        Regex("^write_file$") to ("edited a file" to "edited # files"),
        Regex("^run_command$") to ("ran a command" to "ran # commands"),
        Regex("^(git_|github_pr$|open_pr$)") to ("used git" to "took # git steps"),
        Regex("^(browser_|fetch_url$|dev_server$)") to ("used the browser" to "took # browser steps"),
        Regex("^desktop_") to ("used an app" to "took # desktop steps"),
        Regex("^mcp__") to ("used a connector" to "made # connector calls"),
        Regex(".") to ("looked up the team" to "took # team steps"),
    )

    fun summary(names: List<String>): String {
        val counts = LinkedHashMap<Pair<String, String>, Int>()
        for (n in names) { val k = STEPS.first { it.first.containsMatchIn(n) }.second; counts[k] = (counts[k] ?: 0) + 1 }
        val said = counts.entries.joinToString(", ") { (k, n) -> if (n == 1) k.first else k.second.replace("#", n.toString()) }
        return said.replaceFirstChar { it.uppercase() }
    }
}
