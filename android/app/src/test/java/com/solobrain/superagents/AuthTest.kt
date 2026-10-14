package com.solobrain.superagents

import com.solobrain.superagents.remote.Auth
import com.solobrain.superagents.remote.AuthError
import com.solobrain.superagents.remote.Seal
import okhttp3.OkHttpClient
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.net.InetAddress
import java.net.ServerSocket
import java.net.URLDecoder
import java.security.MessageDigest

/** Signing in against a stand-in for the hub and Supabase on one local port: the requests the desktop app makes. */
class AuthTest {
    /** Just enough HTTP/1.1 for these tests: one request per connection, JSON both ways. */
    private class Stub(val route: (method: String, path: String, headers: Map<String, String>, body: String) -> Pair<Int, String>) {
        private val socket = ServerSocket(0, 50, InetAddress.getByName("127.0.0.1"))
        val port: Int get() = socket.localPort

        init {
            Thread {
                while (!socket.isClosed) {
                    val c = runCatching { socket.accept() }.getOrNull() ?: break
                    c.use {
                        val input = it.getInputStream().bufferedReader()
                        val (method, path) = (input.readLine() ?: return@use).split(" ").let { p -> p[0] to p[1] }
                        val headers = generateSequence { input.readLine()?.takeIf(String::isNotEmpty) }
                            .associate { l -> l.substringBefore(':').lowercase() to l.substringAfter(':').trim() }
                        val buf = CharArray(headers["content-length"]?.toInt() ?: 0)
                        var read = 0
                        while (read < buf.size) { val n = input.read(buf, read, buf.size - read); if (n < 0) break; read += n }
                        val (code, out) = route(method, path, headers, String(buf, 0, read))
                        val bytes = out.toByteArray()
                        it.getOutputStream().apply {
                            write("HTTP/1.1 $code X\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
                            write(bytes)
                            flush()
                        }
                    }
                }
            }.apply { isDaemon = true }.start()
        }

        fun stop() = socket.close()
    }

    private lateinit var stub: Stub
    private lateinit var hub: String
    private val seen = mutableListOf<String>()
    private val auth = Auth(OkHttpClient())

    @Before fun start() {
        stub = Stub { method, path, headers, body ->
            seen.add("$method $path ${headers["apikey"] ?: "-"} ${headers["authorization"] ?: "-"} $body")
            when (path) {
                "/v1/config" -> 200 to """{"supabase_url": "$hub", "supabase_key": "sb_publishable_test"}"""
                "/auth/v1/token?grant_type=password" ->
                    if (JSONObject(body).optString("password") == "right-password") 200 to """{"access_token": "sb-access", "user": {"id": "u1"}}"""
                    else 400 to """{"code": 400, "error_code": "invalid_credentials", "msg": "Invalid login credentials"}"""
                "/auth/v1/signup" -> 200 to """{"id": "u2", "email": "new@example.com"}"""  // confirmation needed: no session yet
                "/auth/v1/token?grant_type=pkce" -> 200 to """{"access_token": "sb-from-github"}"""
                "/v1/app/session" -> 200 to """{"token": "s_hub", "expires_in": 2592000, "user": {"id": "u1", "email": "yang@example.com", "name": "Yang"}}"""
                "/v1/logout" -> 200 to """{"ok": true}"""
                else -> 404 to """{"detail": "no"}"""
            }
        }
        hub = "http://127.0.0.1:${stub.port}"
    }

    @After fun stop() = stub.stop()

    @Test fun signsInWithEmailThenGetsTheHubsOwnSession() {
        val s = auth.supabase(hub)
        val account = auth.session(hub, auth.password(s, "yang@example.com", "right-password"))
        assertEquals("s_hub", account.token)
        assertEquals("Yang", account.name)
        assertEquals("yang@example.com", account.email)
        assertTrue(seen[1], seen[1].startsWith("POST /auth/v1/token?grant_type=password sb_publishable_test"))  // Supabase gets its key
        assertTrue(seen[2], seen[2].startsWith("POST /v1/app/session - - ") && seen[2].contains("\"access_token\":\"sb-access\""))
        auth.signOut(account)
        assertTrue(seen.last(), seen.last().startsWith("POST /v1/logout - Bearer s_hub"))
    }

    @Test fun saysWhatSupabaseSaid() {
        val e = assertThrows(AuthError::class.java) { auth.password(auth.supabase(hub), "yang@example.com", "wrong-password") }
        assertEquals("Invalid login credentials", e.message)
        assertNull(auth.signUp(auth.supabase(hub), "new@example.com", "a-password", "New"))  // confirm the email first
        val old = assertThrows(AuthError::class.java) { auth.session("$hub/old", "sb-access") }  // a hub from before phone sign-in
        assertEquals("This server can't sign phones in yet: it needs the latest hub.", old.message)
    }

    @Test fun githubUsesPkceAndComesBackToTheApp() {
        val (verifier, challenge) = Auth.pkce()
        assertEquals(Seal.b64(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray())), challenge)
        assertTrue(verifier.length >= 43 && !verifier.contains('=') && !challenge.contains('='))
        val url = auth.authorizeUrl(auth.supabase(hub), challenge)
        assertTrue(url, url.startsWith("$hub/auth/v1/authorize?provider=github&redirect_to="))
        assertEquals(Auth.REDIRECT, URLDecoder.decode(url.substringAfter("redirect_to=").substringBefore('&'), "UTF-8"))
        assertTrue(url, url.endsWith("&code_challenge=$challenge&code_challenge_method=s256"))
        assertEquals("sb-from-github", auth.exchange(auth.supabase(hub), "the-code", verifier))
        assertTrue(seen.last(), seen.last().contains("\"auth_code\":\"the-code\"") && seen.last().contains("\"code_verifier\":\"$verifier\""))
    }
}
