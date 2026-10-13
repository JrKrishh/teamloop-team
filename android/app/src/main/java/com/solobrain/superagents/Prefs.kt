package com.solobrain.superagents

import android.content.Context

/** The app's switches (Settings): the fingerprint lock, notifications, staying connected, and whether the long
 *  intro has played once. */
object Prefs {
    private fun p(ctx: Context) = ctx.getSharedPreferences("settings", Context.MODE_PRIVATE)
    fun lock(ctx: Context) = p(ctx).getBoolean("lock", false)
    fun setLock(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("lock", on).apply()
    fun notify(ctx: Context) = p(ctx).getBoolean("notify", true)
    fun setNotify(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("notify", on).apply()
    fun stay(ctx: Context) = p(ctx).getBoolean("stay", true)
    fun setStay(ctx: Context, on: Boolean) = p(ctx).edit().putBoolean("stay", on).apply()
    fun introSeen(ctx: Context) = p(ctx).getBoolean("intro", false)
    fun setIntroSeen(ctx: Context) = p(ctx).edit().putBoolean("intro", true).apply()
}
