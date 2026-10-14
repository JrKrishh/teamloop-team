package com.solobrain.superagents.remote

import org.json.JSONArray
import org.json.JSONObject

/** What the laptop tells the phone, as Kotlin. Parsed from the same messages the web app reads. */
data class Agent(val id: String, val name: String, val color: String?, val mode: String?, val model: String? = null)

data class ChatItem(val id: String, val title: String, val agent: String?, val updated: Double, val project: String? = null)

data class Step(val id: String, val name: String, val args: JSONObject)

data class LiveTurn(val turn: String, val chat: String?, val agent: String?, val message: String, val ask: Step?, val now: Step?)

/** [model] and [effort]: what the desktop is set to, where the phone starts. */
data class Laptop(val host: String, val user: String?, val agents: List<Agent>, val chats: List<ChatItem>, val live: List<LiveTurn>,
                  val model: String? = null, val effort: String? = null) {
    val name: String get() = user?.substringBefore(' ')?.let { "$it's laptop" } ?: "Your laptop"
    fun agent(id: String?): Agent = agents.firstOrNull { it.id == id }
        ?: Agent(id ?: "agent-s", if (id == null || id == "agent-s") "Agent S" else "Agent", null, null)
}

data class Task(
    val task: String, val title: String, val status: String, val owner: String?, val tools: List<String>, val due: String?,
    val percent: Int?, val says: Int?, val confidence: String?,
    val blockers: List<String>, val doing: List<String>, val next: List<String>, val pr: String?,
)

data class Board(val room: String, val tasks: List<Task>)

enum class Link { NotPaired, Connecting, Online, Offline }

open class RemoteError(message: String) : Exception(message)
/** The message didn't get there, or no answer came back: the line, not the laptop, said no. */
class LineDown(message: String) : RemoteError(message)

fun JSONObject.text(key: String): String? = if (!has(key) || isNull(key)) null else optString(key)
fun JSONArray?.objects(): List<JSONObject> = if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it) }
fun JSONArray?.strings(): List<String> = if (this == null) emptyList() else (0 until length()).mapNotNull { opt(it) as? String }

fun step(o: JSONObject?): Step? = o?.let { Step(it.optString("id"), it.optString("name"), it.optJSONObject("args") ?: JSONObject()) }

fun parseLive(a: JSONArray?): List<LiveTurn> = a.objects().map {
    LiveTurn(it.optString("turn"), it.text("chat"), it.text("agent"), it.optString("message"), step(it.optJSONObject("ask")), step(it.optJSONObject("now")))
}

fun parseLaptop(o: JSONObject) = Laptop(
    host = o.optString("laptop"), user = o.text("user"),
    agents = o.optJSONArray("agents").objects().map { Agent(it.optString("id"), it.optString("name"), it.text("color"), it.text("mode"), it.text("model")) },
    chats = o.optJSONArray("chats").objects().map { ChatItem(it.optString("id"), it.optString("title"), it.text("agent"), it.optDouble("updated", 0.0), it.text("project")) },
    live = parseLive(o.optJSONArray("live")),
    model = o.optJSONObject("prefs")?.text("model"), effort = o.optJSONObject("prefs")?.text("effort"),
)

fun parseBoard(o: JSONObject) = Board(
    room = o.optString("room").ifEmpty { "Board" },
    tasks = o.optJSONArray("tasks").objects().map {
        val pr = it.optJSONObject("pr")
        Task(
            task = it.optString("task"), title = it.optString("title"), status = it.optString("status"), owner = it.text("owner")
                ?: it.optJSONArray("members").strings().firstOrNull(),
            tools = it.optJSONArray("tools").strings(), due = it.text("due"),
            percent = if (it.isNull("percent") || !it.has("percent")) null else it.optInt("percent"),
            says = if (it.isNull("says") || !it.has("says")) null else it.optInt("says"), confidence = it.text("confidence"),
            blockers = it.optJSONArray("blockers").strings(), doing = it.optJSONArray("doing").strings(), next = it.optJSONArray("next").strings(),
            pr = pr?.let { p -> "PR #${p.optInt("number")} ${p.optString("state")}" },
        )
    },
)
