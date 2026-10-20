package com.solobrain.superagents.remote

import org.json.JSONArray
import org.json.JSONObject

/** What the laptop tells the phone, as Kotlin. Parsed from the same messages the web app reads. */
data class Agent(val id: String, val name: String, val color: String?, val mode: String?, val model: String? = null)

data class ChatItem(val id: String, val title: String, val agent: String?, val updated: Double, val project: String? = null)

data class Step(val id: String, val name: String, val args: JSONObject)

data class LiveTurn(val turn: String, val chat: String?, val agent: String?, val message: String, val ask: Step?, val now: Step?)

/** A lead's: a step of a member's agent waiting for their yes, by the team's rules (Super Team → Rules). */
data class TeamAsk(val id: String, val from: String, val what: String, val detail: String, val rule: String)

/** A coding agent on the laptop that a turn can run on instead of Nemotron ("claude_code", "codex"), and the model it
 *  would use there. */
data class Engine(val id: String, val label: String, val modelLabel: String?)

/** [model] and [effort]: what the desktop is set to, where the phone starts. [asks]: what waits on this lead's yes.
 *  [notes]: unread notes from teammates and their agents (Super Team → Inbox on the desktop). */
data class Laptop(val host: String, val user: String?, val agents: List<Agent>, val chats: List<ChatItem>, val live: List<LiveTurn>,
                  val model: String? = null, val effort: String? = null, val asks: List<TeamAsk> = emptyList(),
                  val notes: List<Note> = emptyList(), val engines: List<Engine> = emptyList()) {
    val name: String get() = user?.substringBefore(' ')?.let { "$it's laptop" } ?: "Your laptop"
    fun agent(id: String?): Agent = agents.firstOrNull { it.id == id }
        ?: Agent(id ?: "agent-s", if (id == null || id == "agent-s") "Agent S" else "Agent", null, null)
}

data class Task(
    val task: String, val title: String, val status: String, val owner: String?, val tools: List<String>, val due: String?,
    val percent: Int?, val says: Int?, val confidence: String?,
    val blockers: List<String>, val doing: List<String>, val next: List<String>, val pr: String?,
    val editing: List<String> = emptyList(),  // files its sessions edited in the last half hour
)

/** A file more than one session edited in the last half hour: where merge conflicts start. */
data class Overlap(val file: String, val who: List<String>)

data class Board(val room: String, val tasks: List<Task>, val overlaps: List<Overlap> = emptyList())

/** A note between teammates and their coding agents. [to]: one person ("you" for this phone's person), or null for
 *  everyone; [task]: what it's about, if anything. */
data class Note(val from: String, val mine: Boolean, val agent: Boolean, val to: String?, val text: String, val at: Double,
                val id: Long = 0, val task: String? = null)

fun parseNotes(a: JSONArray?): List<Note> = a.objects().map {
    Note(it.optString("from"), it.optBoolean("mine"), it.optBoolean("agent"), it.text("to"), it.optString("text"), it.optDouble("at", 0.0),
        it.optLong("id"), it.text("task"))
}

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

fun parseAsks(a: JSONArray?): List<TeamAsk> = a.objects().map {
    TeamAsk(it.optString("id"), it.optString("from"), it.optString("what"), it.optString("detail"), it.optString("rule"))
}

fun parseLaptop(o: JSONObject) = Laptop(
    host = o.optString("laptop"), user = o.text("user"),
    agents = o.optJSONArray("agents").objects().map { Agent(it.optString("id"), it.optString("name"), it.text("color"), it.text("mode"), it.text("model")) },
    chats = o.optJSONArray("chats").objects().map { ChatItem(it.optString("id"), it.optString("title"), it.text("agent"), it.optDouble("updated", 0.0), it.text("project")) },
    live = parseLive(o.optJSONArray("live")),
    model = o.optJSONObject("prefs")?.text("model"), effort = o.optJSONObject("prefs")?.text("effort"),
    asks = parseAsks(o.optJSONArray("asks")),
    notes = parseNotes(o.optJSONArray("notes")),
    engines = o.optJSONArray("engines").objects().map { Engine(it.optString("id"), it.optString("label"), it.text("model_label")) },
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
            editing = it.optJSONArray("editing").strings(),
        )
    },
    overlaps = o.optJSONArray("overlaps").objects().map { Overlap(it.optString("file"), it.optJSONArray("who").strings()) },
)
