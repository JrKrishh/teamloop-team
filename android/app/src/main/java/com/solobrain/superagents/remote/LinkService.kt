package com.solobrain.superagents.remote

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.solobrain.superagents.Prefs
import com.solobrain.superagents.remote

/**
 * Keeps the line to the laptop open while the app is in the background: Android freezes an app soon after it leaves
 * the screen, and a frozen app hears nothing. A remote-messaging foreground service, with a quiet ongoing notice;
 * Settings → Stay connected turns it off.
 */
class LinkService : Service() {
    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val r = remote
        if (!r.paired || !Prefs.stay(this)) {
            stopSelf()
            return START_NOT_STICKY
        }
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING else 0
        ServiceCompat.startForeground(this, Notifications.LINK_ID, Notifications.link(this, r.laptop.value?.name ?: "your laptop"), type)
        r.start()
        return START_STICKY
    }

    companion object {
        fun start(ctx: Context) {
            if (Prefs.stay(ctx) && ctx.remote.paired) runCatching { ContextCompat.startForegroundService(ctx, Intent(ctx, LinkService::class.java)) }
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, LinkService::class.java))
        }
    }
}
