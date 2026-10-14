package com.solobrain.superagents.remote

import android.content.Context
import android.content.pm.ApplicationInfo
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** This phone's Super Agents account: who's signed in, and the hub session that says so. */
class Account(val hub: String, val token: String, val name: String?, val email: String?)

/**
 * The account, kept on the phone: the session token sealed with a key that lives in Android Keystore (usable here, never
 * readable), the name and email beside it (not secret). Sign-in goes to the hub this phone is paired with, else the
 * public one.
 */
object Accounts {
    const val HUB = "https://teamloop.vercel.app"
    private const val ALIAS = "sa-account"
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("account", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        }.generateKey()
    }

    /** Where to sign in: the paired laptop's hub, or the public one (a debug build can be pointed elsewhere for tests). */
    fun hub(ctx: Context): String = prefs(ctx).getString("hub_override", null)?.takeIf { debuggable(ctx) }
        ?: ctx.getSharedPreferences("pairing", Context.MODE_PRIVATE).getString("hub", null) ?: HUB

    fun overrideHub(ctx: Context, hub: String) { if (debuggable(ctx)) prefs(ctx).edit().putString("hub_override", hub.trimEnd('/')).apply() }

    private fun debuggable(ctx: Context) = ctx.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0

    fun signedIn(ctx: Context) = prefs(ctx).contains("token")
    fun name(ctx: Context): String? = prefs(ctx).getString("name", null)
    fun email(ctx: Context): String? = prefs(ctx).getString("email", null)

    fun save(ctx: Context, a: Account) {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = c.iv + c.doFinal(a.token.toByteArray())
        prefs(ctx).edit().putString("account_hub", a.hub).putString("token", Seal.b64(sealed)).putString("name", a.name)
            .putString("email", a.email).remove("verifier").apply()
    }

    fun load(ctx: Context): Account? {
        val p = prefs(ctx)
        val sealed = p.getString("token", null)?.let { runCatching { Seal.unb64(it) }.getOrNull() } ?: return null
        val token = runCatching {
            val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, sealed, 0, 12)) }
            String(c.doFinal(sealed, 12, sealed.size - 12))
        }.getOrNull() ?: return null
        return Account(p.getString("account_hub", null) ?: HUB, token, p.getString("name", null), p.getString("email", null))
    }

    /** A GitHub sign-in or an email sign-up in progress: the PKCE verifier waits here while the browser or the email is
     *  open (the app may be closed). */
    fun startPending(ctx: Context, hub: String, verifier: String) = prefs(ctx).edit().putString("verifier", verifier).putString("pending_hub", hub).apply()

    fun takePending(ctx: Context): Pair<String, String>? {
        val p = prefs(ctx)
        val v = p.getString("verifier", null) ?: return null
        val hub = p.getString("pending_hub", null) ?: return null
        p.edit().remove("verifier").remove("pending_hub").apply()
        return hub to v
    }

    fun forget(ctx: Context) {
        val override = prefs(ctx).getString("hub_override", null)
        val e = prefs(ctx).edit().clear()
        if (override != null) e.putString("hub_override", override)
        e.apply()
    }
}
