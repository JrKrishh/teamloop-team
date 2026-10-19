package com.solobrain.superagents.remote

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.util.Log
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONObject
import java.net.URLEncoder
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import kotlin.math.abs
import kotlin.math.min

/**
 * This phone's line to Super Agents on the laptop: the relay socket, the sealed requests and their answers, turn
 * events as they happen, and the list of running turns (with the question each waits on), pushed by the laptop.
 * One per process; the LinkService keeps the process (and so the line) alive in the background.
 */
private const val TAG = "SuperAgents"

class Remote(private val app: Context) {
    val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    val http = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).connectTimeout(15, TimeUnit.SECONDS).build()
    private val random = SecureRandom()

    val link = MutableStateFlow(Link.NotPaired)
    val laptop = MutableStateFlow<Laptop?>(null)
    val board = MutableStateFlow<Board?>(null)
    val events = MutableSharedFlow<Pair<String, List<JSONObject>>>(extraBufferCapacity = 256)

    @Volatile var inForeground = false
    @Volatile private var pairing: Pairing? = null  // the key comes out of Keystore off the main thread, when connecting
    @Volatile private var known = Pairings.has(app)
    @Volatile private var relay: Relay? = null
    @Volatile private var connecting = false
    @Volatile private var watching = false
    private var backoff = 1000L
    @Volatile private var pinger: Job? = null
    @Volatile private var greeter: Job? = null
    private val pending = ConcurrentHashMap<String, CompletableDeferred<JSONObject>>()
    private val seen = ConcurrentHashMap<String, Long>()
    private val told: MutableSet<String> = ConcurrentHashMap.newKeySet()
    private val turns = ConcurrentHashMap<String, Pair<String?, String?>>()  // the phone's turns: chat, agent
    val device = "${Build.MODEL} · Super Agents app"

    init { link.value = if (known) Link.Connecting else Link.NotPaired }

    val paired: Boolean get() = known

    /** The app came on screen: connect, or on a live line ask the laptop again, so chats and questions are fresh. */
    fun start() {
        if (known && relay == null) connect() else if (relay?.joined == true) hello()
        if (!watching) {  // back on a network (out of a lift, Wi-Fi again): connect now, not after the wait between tries
            watching = true
            app.getSystemService(ConnectivityManager::class.java)?.registerDefaultNetworkCallback(object : ConnectivityManager.NetworkCallback() {
                override fun onAvailable(network: Network) { if (known && relay == null) { backoff = 1000; connect() } }
            })
        }
    }

    fun pair(l: Pairings.Link) {
        stop()
        pairing = Pairings.save(app, l)
        known = true
        told.clear(); laptop.value = null; board.value = null
        link.value = Link.Connecting
        connect()
    }

    fun forget() {
        stop()
        Pairings.forget(app)
        pairing = null; known = false; laptop.value = null; board.value = null
        link.value = Link.NotPaired
    }

    /** Try again pressed: the laptop now, not after the wait between tries. */
    fun tryNow() {
        if (relay?.joined == true) hello(now = true) else if (known) { backoff = 1000; link.value = Link.Connecting; connect() }
    }

    private fun stop() {
        relay?.close(); relay = null
        pinger?.cancel(); greeter?.cancel()
    }

    private fun connect() {
        if (!known) return
        synchronized(this) { if (connecting || relay != null) return; connecting = true }
        scope.launch {
            val p = pairing ?: Pairings.load(app)?.also { pairing = it }
            if (p == null) { connecting = false; known = false; link.value = Link.NotPaired; return@launch }
            val url = runCatching { relayUrl(p.hub) }.getOrNull()
            if (url == null || pairing !== p) {
                connecting = false
                if (pairing === p) { link.value = Link.Offline; retry() }
                return@launch
            }
            lateinit var r: Relay
            r = Relay(http, scope,
                onJoined = { backoff = 1000; hello(now = true) },
                onEnvelope = { receive(it) },
                onDown = { if (relay === r) { relay = null; link.value = Link.Offline; retry() } })
            relay = r
            connecting = false
            r.open(url, "realtime:sa-${p.channel}")
        }
    }

    private fun retry() {
        scope.launch {
            delay(backoff)
            backoff = min(backoff * 2, 30_000)
            if (relay == null && known) connect()
        }
    }

    private fun relayUrl(hub: String): String =
        http.newCall(Request.Builder().url("$hub/v1/config").build()).execute().use { res ->
            relayUrlFrom(hub, JSONObject(res.body.string())) ?: throw RemoteError("This server can't reach your laptop yet.")
        }

    private fun receive(env: JSONObject) {
        val p = pairing ?: return
        val m = runCatching { Seal.unseal(p.key, p.channel, env) }.getOrNull() ?: return  // not sealed with this phone's key
        val now = System.currentTimeMillis()
        val id = m.optString("id")
        if (m.optString("from") != "laptop" || id.isEmpty() || abs(now - m.optLong("ts")) > 120_000) return
        if (seen.putIfAbsent(id, now) != null) return  // a replay
        if (seen.size > 600) seen.entries.removeIf { now - it.value > 240_000 }
        link.value = Link.Online
        Log.d(TAG, "from the laptop: ${m.optString("t")}${if (inForeground) "" else " (in the background)"}")  // the kind only, never what it says
        val waiting = m.optString("re").takeIf { it.isNotEmpty() }?.let { pending.remove(it) }
        when {
            waiting != null -> waiting.complete(m)
            m.optString("t") == "events" -> onEvents(m.optString("turn"), m.optJSONArray("events").objects())
            m.optString("t") == "live" -> laptop.value?.let {
                laptop.value = it.copy(live = parseLive(m.optJSONArray("live")), asks = parseAsks(m.optJSONArray("asks")),
                    notes = parseNotes(m.optJSONArray("notes"))); liveChanged()
            } ?: hello()  // the laptop is there but this phone has no answer to its hello yet: ask again now
        }
    }

    private fun onEvents(turn: String, evs: List<JSONObject>) {
        events.tryEmit(turn to evs)
        if (!inForeground && evs.any { it.optString("kind") == "answer" }) {
            val (chat, agent) = turns[turn] ?: (null to null)
            Notifications.answered(app, laptop.value?.agent(agent)?.name ?: "Agent S", chat)
        }
    }

    /** A request to the laptop, answered by a message that names it. */
    suspend fun request(msg: JSONObject, waitMs: Long = 15_000): JSONObject {
        val p = pairing ?: throw RemoteError("This phone isn't paired.")
        val r = relay?.takeIf { it.joined } ?: throw LineDown("Not connected to your laptop yet.")
        val id = Seal.b64(ByteArray(12).also(random::nextBytes))
        val answer = CompletableDeferred<JSONObject>()
        pending[id] = answer
        msg.put("from", "phone").put("id", id).put("ts", System.currentTimeMillis())
        if (!r.broadcast(Seal.seal(p.key, p.channel, msg))) {
            pending.remove(id)
            throw LineDown("Not connected to your laptop yet.")
        }
        val reply = try { withTimeoutOrNull(waitMs) { answer.await() } } finally { pending.remove(id) }  // cancelled too
        if (reply == null) {
            link.value = Link.Offline
            throw LineDown("Your laptop didn't answer. Is Super Agents open on it?")
        }
        if (reply.optString("t") == "error") throw RemoteError(reply.optString("error"))
        return reply
    }

    /** Hello until the laptop answers, for as long as this line is up (Super Agents may open on the laptop much later),
     *  waiting longer between tries; then ping, so the laptop keeps pushing what's running. `now` starts over at once
     *  (a new line, or Try again) instead of leaving it to a hello that's waiting. */
    private fun hello(now: Boolean = false) {
        val r = relay ?: return
        if (!now && greeter?.isActive == true) return  // already trying
        greeter?.cancel()
        greeter = scope.launch {
            var wait = 2_000L
            while (relay === r && r.joined) {
                try {
                    refresh(5_000)
                    pinger?.cancel()
                    pinger = scope.launch {
                        while (isActive) { delay(30_000); if (relay?.joined == true) runCatching { request(JSONObject().put("t", "ping")) } }
                    }
                    return@launch
                } catch (e: RemoteError) {
                    delay(wait); wait = min(wait * 2, 30_000)
                }
            }
        }
    }

    suspend fun refresh(waitMs: Long = 10_000) {
        laptop.value = parseLaptop(request(JSONObject().put("t", "hello").put("device", device).put("account", account()), waitMs))
        liveChanged()
    }

    /** Who this phone is signed in as, for the laptop to show next to it (the pairing key is what lets it in). */
    private fun account(): Any = if (!Accounts.signedIn(app)) JSONObject.NULL
        else JSONObject().put("name", Accounts.name(app) ?: JSONObject.NULL).put("email", Accounts.email(app) ?: JSONObject.NULL)

    /** While the app isn't on screen, each waiting question becomes one notification, including one first seen on
     *  screen and left unanswered when the app went away (SuperAgentsApp calls this then); answered ones go away. */
    fun liveChanged() {
        val lp = laptop.value ?: return
        if (!inForeground) {
            for (t in lp.live) {
                val ask = t.ask ?: continue
                if (told.add(ask.id)) { Log.d(TAG, "a question, in the background"); Notifications.ask(app, t, ask, lp.agent(t.agent).name) }
            }
            for (a in lp.asks) if (told.add(a.id)) Notifications.teamAsk(app, a)  // a member's agent wants this lead's yes
            for (n in lp.notes) if (told.add("note-${n.id}")) Notifications.note(app, n)  // a teammate or their agent wrote
        }
        Notifications.keepAsks(app, lp.live.mapNotNull { it.ask?.id }.toSet() + lp.asks.map { it.id })
        Notifications.keepNotes(app, lp.notes.map { it.id }.toSet())  // read at the desk: gone here too
    }

    suspend fun send(chat: String?, agent: String, mode: String, model: String, effort: String, message: String): Pair<String, String> {
        val r = request(JSONObject().put("t", "send").put("chat", chat ?: JSONObject.NULL).put("agent", agent)
            .put("mode", mode).put("model", model).put("effort", effort).put("message", message))
        val turn = r.getString("turn")
        turns[turn] = r.getString("chat") to agent
        return turn to r.getString("chat")
    }

    suspend fun watch(turn: String, after: Int, chat: String? = null, agent: String? = null) {
        if (chat != null || agent != null) turns[turn] = chat to agent
        request(JSONObject().put("t", "watch").put("turn", turn).put("after", after))
    }

    suspend fun decide(turn: String, call: String, approve: Boolean) {
        again { JSONObject().put("t", "decide").put("turn", turn).put("call", call).put("approve", approve) }
        Notifications.cancelAsk(app, call)
    }

    /** For what's safe to say twice (a yes said twice is still one yes): when the line died without a word, as it can
     *  while the phone sleeps, connect again and say it once more instead of leaving the agent waiting. */
    private suspend fun again(msg: () -> JSONObject): JSONObject = try {
        request(msg(), 8_000)
    } catch (e: LineDown) {
        Log.d(TAG, "no answer on the line: connecting again")
        stop()
        backoff = 1000
        connect()  // and if the phone is offline, again the moment a network is back (start's callback)
        withTimeoutOrNull(20_000) { while (relay?.joined != true) delay(250) }
        request(msg(), 10_000)
    }

    /** A lead's yes or no to a member's agent's step, through the laptop to the team's hub. Said twice, it's still once. */
    suspend fun decideTeam(id: String, approve: Boolean) {
        try {
            again { JSONObject().put("t", "team_decide").put("approval", id).put("approve", approve) }  // "id" is the message's own
        } catch (e: RemoteError) {
            if (e.message?.startsWith("Already decided") != true) throw e  // the first try got there; its answer didn't
        }
        Notifications.cancelAsk(app, id)
    }

    suspend fun stopTurn(turn: String) { request(JSONObject().put("t", "stop").put("turn", turn)) }
    /** Typed while the answer runs: a note it reads before its next step. */
    suspend fun steer(turn: String, text: String) { request(JSONObject().put("t", "steer").put("turn", turn).put("text", text)) }
    /** Switched while the answer runs: it carries on in the new mode. */
    suspend fun setMode(turn: String, mode: String) { request(JSONObject().put("t", "mode").put("turn", turn).put("mode", mode)) }

    suspend fun runPlan(turn: String) { request(JSONObject().put("t", "run_plan").put("turn", turn)) }

    suspend fun chat(id: String): JSONObject = request(JSONObject().put("t", "chat").put("chat", id)).getJSONObject("chat")

    suspend fun loadBoard() { board.value = parseBoard(request(JSONObject().put("t", "board"), 25_000)) }

    /** Read on the phone, through the laptop to the hub: the desktop's badge clears too. */
    suspend fun markNotesRead(upTo: Long) {
        request(JSONObject().put("t", "notes_read").put("up_to", upTo))
        laptop.value?.let { lp -> laptop.value = lp.copy(notes = lp.notes.filter { it.id > upTo }) }
        Notifications.cancelNotes(app)
    }

    suspend fun notes(task: String): List<Note> = parseNotes(request(JSONObject().put("t", "notes").put("task", task), 15_000).optJSONArray("notes"))

    /** Leaves a note for everyone else on the task ([to] "task") or one person; the task's notes after it, and who
     *  turned notes off. */
    suspend fun note(task: String, to: String, text: String): Pair<List<Note>, List<String>> {
        val r = request(JSONObject().put("t", "note").put("task", task).put("to", to).put("text", text), 15_000)
        return parseNotes(r.optJSONArray("notes")) to r.optJSONArray("skipped").strings()
    }
}

/** Where phone and laptop meet: Supabase Realtime when the hub has it, else the hub's own socket. A hub from before the
 *  "relay" field (T-32 and older) still names its Supabase project, and that project is the relay. */
internal fun relayUrlFrom(hub: String, cfg: JSONObject): String? {
    val relay = if (cfg.has("relay")) cfg.optString("relay") else if (!cfg.isNull("supabase_url") && !cfg.isNull("supabase_key")) "supabase" else ""
    return when (relay) {
        "supabase" -> cfg.getString("supabase_url").trimEnd('/').replaceFirst("https://", "wss://") +
            "/realtime/v1/websocket?apikey=" + URLEncoder.encode(cfg.getString("supabase_key"), "UTF-8") + "&vsn=1.0.0"
        "hub" -> hub.replaceFirst("https://", "wss://").replaceFirst("http://", "ws://") + "/v1/relay?vsn=1.0.0"
        else -> null
    }
}
