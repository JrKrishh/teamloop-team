package com.solobrain.superagents.remote

import android.content.Context
import android.security.keystore.KeyProperties
import android.security.keystore.KeyProtection
import java.net.URLDecoder
import java.security.KeyStore
import javax.crypto.SecretKey
import javax.crypto.spec.SecretKeySpec

/** This phone's pairing with a laptop: the hub, the channel, and the key, which lives in Android Keystore. */
class Pairing(val hub: String, val channel: String, val key: SecretKey)

object Pairings {
    private const val ALIAS = "sa-pairing"

    /** A pairing code as a link: https://<hub>/remote/#p=<channel>&k=<key> (the laptop's QR code), or
     *  superagents://pair#p=<channel>&k=<key>&h=<hub>. The key rides in the fragment, which never reaches a server. */
    class Link(val hub: String, val channel: String, val key: ByteArray)

    fun parse(text: String): Link? {
        val link = text.trim()
        val fragment = link.substringAfter('#', "")
        if (fragment.isEmpty()) return null
        val q = fragment.split('&').mapNotNull { part ->
            val kv = part.split('=', limit = 2)
            if (kv.size == 2) kv[0] to URLDecoder.decode(kv[1], "UTF-8") else null
        }.toMap()
        val channel = q["p"]?.takeIf { Regex("[0-9a-f]{32}").matches(it) } ?: return null
        val raw = q["k"]?.let { runCatching { Seal.unb64(it) }.getOrNull() }?.takeIf { it.size == 32 } ?: return null
        val hub = q["h"] ?: Regex("^(https?://[^/#?]+)").find(link)?.groupValues?.get(1) ?: return null
        if (!hub.startsWith("https://") && !hub.startsWith("http://")) return null
        return Link(hub.trimEnd('/'), channel, raw)
    }

    private fun keystore() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("pairing", Context.MODE_PRIVATE)

    /** Keeps the key in Keystore, where it can be used but never read back, and forgets the bytes. */
    fun save(ctx: Context, link: Link): Pairing {
        keystore().setEntry(ALIAS, KeyStore.SecretKeyEntry(SecretKeySpec(link.key, "AES")),
            KeyProtection.Builder(KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build())
        link.key.fill(0)
        prefs(ctx).edit().putString("hub", link.hub).putString("channel", link.channel).apply()
        return load(ctx) ?: error("The key didn't keep")
    }

    /** Paired or not, from the preferences alone: no Keystore on the main thread at startup. */
    fun has(ctx: Context): Boolean = prefs(ctx).contains("channel")

    fun load(ctx: Context): Pairing? {
        val p = prefs(ctx)
        val hub = p.getString("hub", null) ?: return null
        val channel = p.getString("channel", null) ?: return null
        val key = runCatching { keystore().getKey(ALIAS, null) as? SecretKey }.getOrNull() ?: return null
        return Pairing(hub, channel, key)
    }

    fun forget(ctx: Context) {
        runCatching { keystore().deleteEntry(ALIAS) }
        prefs(ctx).edit().clear().apply()
    }
}
