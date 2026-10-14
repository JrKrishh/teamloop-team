package com.solobrain.superagents.remote

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONException
import org.json.JSONObject

/** One channel on a Phoenix-protocol socket: what Supabase Realtime speaks (and the hub's own relay, in development).
 *  Join, heartbeat, broadcast to the others on the channel. Messages are sealed before they get here. */
class Relay(
    private val http: OkHttpClient,
    private val scope: CoroutineScope,
    private val onJoined: () -> Unit,
    private val onEnvelope: (JSONObject) -> Unit,
    private val onDown: () -> Unit,
) {
    private var ws: WebSocket? = null
    private var ref = 0
    private var topic = ""
    private var beat: Job? = null
    @Volatile var joined = false
        private set
    @Volatile private var closed = false

    fun open(url: String, topic: String) {
        this.topic = topic
        ws = http.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                raw("phx_join", JSONObject().put("config", JSONObject()
                    .put("broadcast", JSONObject().put("self", false).put("ack", false))
                    .put("presence", JSONObject().put("key", ""))
                    .put("private", false)))
                beat = scope.launch { while (isActive) { delay(25_000); raw("heartbeat", JSONObject(), "phoenix") } }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                val m = try { JSONObject(text) } catch (e: JSONException) { return }
                if (m.optString("topic") != topic) return
                when (m.optString("event")) {
                    "phx_reply" -> if (!joined) { joined = true; onJoined() }
                    "broadcast" -> m.optJSONObject("payload")?.optJSONObject("payload")?.let(onEnvelope)
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) = down()
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) = down()
        })
    }

    private fun down() {
        joined = false
        beat?.cancel()
        if (!closed) onDown()
    }

    @Synchronized
    fun raw(event: String, payload: JSONObject, t: String = topic): Boolean {
        ref++
        val frame = JSONObject().put("topic", t).put("event", event).put("payload", payload).put("ref", ref.toString())
        return ws?.send(frame.toString()) ?: false
    }

    fun broadcast(env: JSONObject): Boolean =
        joined && raw("broadcast", JSONObject().put("type", "broadcast").put("event", "m").put("payload", env))

    fun close() {
        closed = true
        joined = false
        beat?.cancel()
        ws?.close(1000, null)
        ws = null
    }
}
