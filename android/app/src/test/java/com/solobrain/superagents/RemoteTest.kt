package com.solobrain.superagents

import com.solobrain.superagents.remote.Labels
import com.solobrain.superagents.remote.Note
import com.solobrain.superagents.remote.Pairings
import com.solobrain.superagents.remote.Seal
import com.solobrain.superagents.remote.parseLaptop
import com.solobrain.superagents.remote.parseNotes
import com.solobrain.superagents.remote.relayUrlFrom
import com.solobrain.superagents.ui.ChatModel
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test
import javax.crypto.spec.SecretKeySpec

/** The phone's side of the protocol, against the laptop's: the same seal, the same links, events in order. */
class RemoteTest {
    private val key = SecretKeySpec(ByteArray(32) { it.toByte() }, "AES")
    private val channel = "0123456789abcdef0123456789abcdef"

    @Test fun opensWhatTheLaptopSealed() {
        // sealed by app/superagents/remote.py with the same key and channel
        val env = JSONObject("""{"iv": "ukMREu0fmGZsKWQm", "c": "rh8-L_YIDL2qmPImqWsnUxGj4J7M50NxqbBo9sYjcs65pV7WWQy7tYmBHVlJlr63-cD8yGeWgkGI8Gl5wjpC2NBhx_vF-v01P3yfkhXuWhGZ_hsVU_DP5WvQrRsouWWEiO8rvw"}""")
        val m = Seal.unseal(key, channel, env)
        assertEquals("hello", m.getString("t"))
        assertEquals("Sealed by remote.py", m.getString("note"))
        assertThrows(Exception::class.java) { Seal.unseal(key, "another-channel", env) }  // bound to its channel
        assertThrows(Exception::class.java) { Seal.unseal(SecretKeySpec(ByteArray(32), "AES"), channel, env) }  // and its key
    }

    @Test fun sealsWithAFreshNonceEachTime() {
        val a = Seal.seal(key, channel, JSONObject().put("t", "ping"))
        val b = Seal.seal(key, channel, JSONObject().put("t", "ping"))
        assertNotEquals(a.getString("iv"), b.getString("iv"))
        assertEquals("ping", Seal.unseal(key, channel, a).getString("t"))
    }

    @Test fun readsPairingLinks() {
        val k = Seal.b64(ByteArray(32) { 7 })
        val web = Pairings.parse("https://teamloop.vercel.app/remote/#p=$channel&k=$k")!!
        assertEquals("https://teamloop.vercel.app", web.hub)
        assertEquals(channel, web.channel)
        val app = Pairings.parse("superagents://pair#p=$channel&k=$k&h=http://127.0.0.1:8811")!!
        assertEquals("http://127.0.0.1:8811", app.hub)
        assertNull(Pairings.parse("superagents://pair#p=$channel&k=$k"))  // no hub to reach
        assertNull(Pairings.parse("https://hub/remote/#p=nothex&k=$k"))
        assertNull(Pairings.parse("https://hub/remote/#p=$channel&k=" + Seal.b64(ByteArray(16))))  // a short key
        assertNull(Pairings.parse("https://hub/remote/"))
    }

    @Test fun findsWhereThePhoneAndTheLaptopMeet() {
        val supa = JSONObject().put("relay", "supabase").put("supabase_url", "https://ab.supabase.co").put("supabase_key", "sb_publishable_x")
        val wss = "wss://ab.supabase.co/realtime/v1/websocket?apikey=sb_publishable_x&vsn=1.0.0"
        assertEquals(wss, relayUrlFrom("https://hub", supa))
        assertEquals("ws://127.0.0.1:8811/v1/relay?vsn=1.0.0", relayUrlFrom("http://127.0.0.1:8811", JSONObject().put("relay", "hub")))
        supa.remove("relay")
        assertEquals(wss, relayUrlFrom("https://hub", supa))  // a hub from before the relay field: its Supabase project is the relay
        assertNull(relayUrlFrom("https://hub", supa.put("relay", JSONObject.NULL)))  // a hub that says it has none
        assertNull(relayUrlFrom("https://hub", JSONObject()))
    }

    @Test fun showsEventsInOrderAndAsksForGaps() {
        val m = ChatModel()
        val b = m.agent("agent-s")
        val asked = mutableListOf<Int>()
        val tool = { i: Int, status: String -> JSONObject().put("i", i).put("kind", "tool").put("id", "c1").put("name", "run_command")
            .put("args", JSONObject().put("command", "npm test")).put("status", status) }
        m.onEvents("t1", listOf(tool(0, "asking")), { _, after -> asked.add(after) })  // before the turn is known: kept
        m.bind("t1", b) { _, after -> asked.add(after) }
        assertEquals("asking", b.cards["c1"]!!.status)
        m.onEvents("t1", listOf(JSONObject().put("i", 2).put("kind", "answer").put("text", "Done.")), { _, after -> asked.add(after) })
        assertNull(b.answer)  // 1 is missing: held back, and asked for
        assertEquals(listOf(1), asked)
        m.onEvents("t1", listOf(tool(1, "done"), tool(1, "done")), { _, _ -> })
        assertEquals("done", b.cards["c1"]!!.status)
        assertEquals("Done.", b.answer)
    }

    @Test fun saysWhatTheStepsDid() {
        assertEquals("Read 3 files, ran a command", Labels.summary(listOf("read_file", "read_file", "run_command", "read_file")))
        assertEquals("Run" to "npm test", Labels.of("run_command", JSONObject().put("command", "npm test")))
        assertEquals("Note for a teammate" to "everyone on T-19: “Rebase first”",
            Labels.of("message_teammate", JSONObject().put("to", "task").put("task", "T-19").put("text", "Rebase first")))
    }

    @Test fun readsATasksNotes() {
        // as app/superagents/remote.py's notes_view sends them, oldest first
        val notes = parseNotes(JSONArray("""[{"from": "Asha", "mine": false, "agent": true, "to": null, "text": "Renamed /v1/session", "at": 1.5},
            {"from": "Yang", "mine": true, "agent": false, "to": "Asha", "text": "Thanks", "at": 2.0}]"""))
        assertEquals(Note("Asha", false, true, null, "Renamed /v1/session", 1.5), notes[0])
        assertEquals("Asha", notes[1].to)
    }

    @Test fun hearsUnreadNotesFromTheLaptop() {
        // as remote.py's team_notes sends them in hello and in each live push
        val lp = parseLaptop(JSONObject("""{"laptop": "DESK", "user": "Yang", "agents": [], "chats": [], "live": [], "asks": [],
            "notes": [{"id": 7, "from": "Asha", "mine": false, "agent": true, "to": "you", "task": "T-3", "text": "Rebase first", "at": 1.0}]}"""))
        assertEquals(Note("Asha", false, true, "you", "Rebase first", 1.0, 7, "T-3"), lp.notes.single())
        assertEquals(emptyList<Note>(), parseLaptop(JSONObject("""{"laptop": "DESK", "agents": [], "chats": [], "live": []}""")).notes)  // an older laptop
    }
}
