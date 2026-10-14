package com.solobrain.superagents.remote

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.net.URLEncoder
import java.security.MessageDigest
import java.security.SecureRandom

class AuthError(message: String, val code: Int = 0) : Exception(message)

/**
 * Signing in, the way the desktop app does it (app/superagents/supa.py): Supabase says who you are, with GitHub or an
 * email and password; the hub trades that for its own session (POST /v1/app/session). Supabase's address and public key
 * come from the hub's /v1/config. GitHub uses PKCE, coming back to the app at [REDIRECT].
 */
class Auth(private val http: OkHttpClient) {
    class Supa(val url: String, val key: String)

    fun supabase(hub: String): Supa {
        val cfg = call(Request.Builder().url("$hub/v1/config").build())
        val url = cfg.optString("supabase_url").trimEnd('/')
        val key = cfg.optString("supabase_key")
        if (url.isEmpty() || key.isEmpty()) throw AuthError("This server doesn't offer sign-in.")
        return Supa(url, key)
    }

    /** An email and password: Supabase's access token. */
    fun password(s: Supa, email: String, password: String): String =
        post("${s.url}/auth/v1/token?grant_type=password", JSONObject().put("email", email).put("password", password), s).getString("access_token")

    /** A new account: its access token, or null when Supabase wants the email confirmed first. The link in that email
     *  comes back to the app at [REDIRECT] with a code for [challenge], as GitHub does, instead of opening the website. */
    fun signUp(s: Supa, email: String, password: String, name: String, challenge: String): String? =
        post("${s.url}/auth/v1/signup?redirect_to=" + URLEncoder.encode(REDIRECT, "UTF-8"), JSONObject().put("email", email).put("password", password)
            .put("data", JSONObject().put("full_name", name)).put("code_challenge", challenge).put("code_challenge_method", "s256"), s).text("access_token")

    fun authorizeUrl(s: Supa, challenge: String): String = "${s.url}/auth/v1/authorize?provider=github&redirect_to=" +
        URLEncoder.encode(REDIRECT, "UTF-8") + "&code_challenge=$challenge&code_challenge_method=s256"

    /** Back from GitHub: the code and the verifier kept for it make Supabase's access token. */
    fun exchange(s: Supa, code: String, verifier: String): String =
        post("${s.url}/auth/v1/token?grant_type=pkce", JSONObject().put("auth_code", code).put("code_verifier", verifier), s).getString("access_token")

    /** The hub's own session for that person. */
    fun session(hub: String, accessToken: String): Account {
        val r = try {
            post("$hub/v1/app/session", JSONObject().put("access_token", accessToken), null)
        } catch (e: AuthError) {
            throw if (e.code == 404) AuthError("This server can't sign phones in yet: it needs the latest hub.", 404) else e
        }
        val u = r.optJSONObject("user") ?: JSONObject()
        return Account(hub, r.getString("token"), u.text("name"), u.text("email"))
    }

    fun signOut(a: Account) {
        runCatching { call(Request.Builder().url("${a.hub}/v1/logout").header("Authorization", "Bearer ${a.token}").post(EMPTY).build()) }
    }

    private fun post(url: String, body: JSONObject, s: Supa?): JSONObject {
        val req = Request.Builder().url(url).post(body.toString().toRequestBody(JSON))
        if (s != null) req.header("apikey", s.key)
        return call(req.build())
    }

    private fun call(req: Request): JSONObject = http.newCall(req).execute().use { res ->
        val text = res.body.string()
        val o = runCatching { JSONObject(text) }.getOrDefault(JSONObject())
        if (!res.isSuccessful) throw AuthError(listOf("msg", "error_description", "message", "detail").firstNotNullOfOrNull { o.text(it) }
            ?: "Sign-in didn't work (${res.code}).", res.code)
        o
    }

    companion object {
        const val REDIRECT = "superagents://auth/callback"
        private val JSON = "application/json".toMediaType()
        private val EMPTY = "{}".toRequestBody(JSON)

        /** PKCE: a verifier the phone keeps, and the challenge for Supabase (base64url SHA-256, no padding). */
        fun pkce(random: SecureRandom = SecureRandom()): Pair<String, String> {
            val verifier = Seal.b64(ByteArray(32).also(random::nextBytes))
            return verifier to Seal.b64(MessageDigest.getInstance("SHA-256").digest(verifier.toByteArray()))
        }
    }
}
