package com.solobrain.superagents.remote

import org.json.JSONObject
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The seal on every message between this phone and the laptop: AES-256-GCM with the channel bound in as associated
 * data, the same as the laptop's (app/superagents/remote.py) and the web app's. The relay carries only noise.
 */
object Seal {
    private val enc = Base64.getUrlEncoder().withoutPadding()
    private val dec = Base64.getUrlDecoder()

    fun b64(bytes: ByteArray): String = enc.encodeToString(bytes)
    fun unb64(text: String): ByteArray = dec.decode(text)

    fun seal(key: SecretKey, channel: String, msg: JSONObject): JSONObject {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key)  // the provider (Android Keystore, or the JVM's) picks a fresh 96-bit nonce
        c.updateAAD(channel.toByteArray())
        val body = c.doFinal(msg.toString().toByteArray())
        return JSONObject().put("iv", b64(c.iv)).put("c", b64(body))
    }

    fun unseal(key: SecretKey, channel: String, env: JSONObject): JSONObject {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, unb64(env.getString("iv"))))
        c.updateAAD(channel.toByteArray())
        return JSONObject(String(c.doFinal(unb64(env.getString("c")))))
    }
}
