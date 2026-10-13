package com.solobrain.superagents.remote

import org.json.JSONObject

/** How a tool call reads to a person ("Run npm test"), and how a turn's folded steps sum up ("Read 3 files, ran a
 *  command"). The same words as the desktop and the web app. */
object Labels {
    private val LABEL: Map<String, Pair<String, (JSONObject) -> String>> = mapOf(
        "run_command" to ("Run" to { a -> a.optString("command") }),
        "read_file" to ("Read" to { a -> a.optString("path") }),
        "write_file" to ("Write" to { a -> a.optString("path") }),
        "list_files" to ("List" to { a -> a.optString("path").ifEmpty { "connected repos" } }),
        "search_files" to ("Search" to { a -> a.optString("query") }),
        "git_commit" to ("Commit" to { a -> a.optString("message").lineSequence().firstOrNull().orEmpty() }),
        "git_push" to ("Push" to { a -> a.optString("repo").ifEmpty { "this branch" } }),
        "open_pr" to ("Open a pull request" to { a -> a.optString("title") }),
        "fetch_url" to ("Read page" to { a -> a.optString("url") }),
        "browser_open" to ("Open" to { a -> a.optString("url") }),
        "team_board" to ("Read the board" to { _ -> "" }),
        "team_ask" to ("Ask the team's history" to { a -> a.optString("question") }),
        "create_task" to ("Create task" to { a -> a.optString("title") }),
        "assign_task" to ("Assign" to { a -> "${a.optString("task")} → ${a.optString("owner")}" }),
        "close_task" to ("Close" to { a -> a.optString("task") }),
        "desktop_open" to ("Open app" to { a -> a.optString("app") }),
        "share_files" to ("Share" to { a -> a.optJSONArray("paths").strings().joinToString(", ") }),
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
