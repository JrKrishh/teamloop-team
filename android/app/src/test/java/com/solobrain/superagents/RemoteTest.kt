package com.solobrain.superagents

import com.solobrain.superagents.remote.Labels
import com.solobrain.superagents.remote.Pairings
import com.solobrain.superagents.remote.Seal
import com.solobrain.superagents.ui.ChatModel
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
    }
}
