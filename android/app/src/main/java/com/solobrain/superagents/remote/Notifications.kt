package com.solobrain.superagents.remote

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.solobrain.superagents.MainActivity
import com.solobrain.superagents.Prefs
import com.solobrain.superagents.R

/**
 * What reaches you when the app isn't on screen: a question with Deny and Approve on the notification itself
 * (Approve needs the phone unlocked; the lock screen shows only who's asking), an answer, and the quiet ongoing
 * "connected" notice that keeps the line open.
 */
object Notifications {
    const val LINK_ID = 4242
    private const val LINK = "link"
    private const val ASKS = "asks"
    private const val ANSWERS = "answers"
    private const val BRICK = 0xFFA8443D.toInt()

    fun channels(ctx: Context) {
        ctx.getSystemService(NotificationManager::class.java).createNotificationChannels(listOf(
            NotificationChannel(LINK, "Connection to your laptop", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Keeps Super Agents listening for your agents' questions"; setShowBadge(false)
            },
            NotificationChannel(ASKS, "When an agent needs you", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "A command or a change waiting for your yes or no"
            },
            NotificationChannel(ANSWERS, "When an agent answers", NotificationManager.IMPORTANCE_DEFAULT),
        ))
    }

    private fun open(ctx: Context, code: Int, chat: String? = null, turn: String? = null): PendingIntent =
        PendingIntent.getActivity(ctx, code, Intent(ctx, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_SINGLE_TOP
            if (chat != null) putExtra("chat", chat)
            if (turn != null) putExtra("turn", turn)
        }, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    private fun may(ctx: Context): Boolean =
        Prefs.notify(ctx) && NotificationManagerCompat.from(ctx).areNotificationsEnabled() &&
            (Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)

    fun link(ctx: Context, laptop: String): Notification = NotificationCompat.Builder(ctx, LINK)
        .setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK)
        .setContentTitle("Connected to $laptop").setContentText("Listening for your agents' questions")
        .setOngoing(true).setSilent(true).setCategory(NotificationCompat.CATEGORY_SERVICE)
        .setContentIntent(open(ctx, 1)).build()

    fun updateLink(ctx: Context, laptop: String) {
        if (may(ctx)) runCatching { NotificationManagerCompat.from(ctx).notify(LINK_ID, link(ctx, laptop)) }
    }

    fun ask(ctx: Context, t: LiveTurn, ask: Step, agent: String) {
        if (!may(ctx)) return
        val id = ask.id.hashCode()
        val what = Labels.line(ask)
        fun decide(ok: Boolean) = PendingIntent.getBroadcast(ctx, id * 2 + (if (ok) 1 else 0),
            Intent(ctx, DecideReceiver::class.java).putExtra("turn", t.turn).putExtra("call", ask.id).putExtra("approve", ok),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val public = NotificationCompat.Builder(ctx, ASKS).setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK)
            .setContentTitle("$agent needs you").build()
        val n = NotificationCompat.Builder(ctx, ASKS).setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK)
            .setContentTitle("$agent needs you").setContentText(what)
            .setStyle(NotificationCompat.BigTextStyle().bigText("$what\nFor: ${t.message}"))
            .setPriority(NotificationCompat.PRIORITY_HIGH).setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(public)
            .setContentIntent(open(ctx, id, t.chat, t.turn)).setAutoCancel(true)
            .addAction(NotificationCompat.Action.Builder(0, "Deny", decide(false)).build())
            .addAction(NotificationCompat.Action.Builder(0, if (ask.name == "run_command") "Run it" else "Allow", decide(true))
                .setAuthenticationRequired(true).build())
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify("ask", id, n) }
    }

    /** A lead's: a member's agent waits for their yes, by the team's rules. Deny or Allow right here. */
    fun teamAsk(ctx: Context, a: TeamAsk) {
        if (!may(ctx)) return
        val id = a.id.hashCode()
        fun decide(ok: Boolean) = PendingIntent.getBroadcast(ctx, id * 2 + (if (ok) 1 else 0),
            Intent(ctx, DecideReceiver::class.java).putExtra("approval", a.id).putExtra("approve", ok),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val title = "${a.from}'s agent needs your yes"
        val public = NotificationCompat.Builder(ctx, ASKS).setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK).setContentTitle(title).build()
        val n = NotificationCompat.Builder(ctx, ASKS).setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK)
            .setContentTitle(title).setContentText(a.what)
            .setStyle(NotificationCompat.BigTextStyle().bigText(if (a.detail.isEmpty()) a.what else "${a.what}\n${a.detail.take(400)}"))
            .setPriority(NotificationCompat.PRIORITY_HIGH).setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE).setPublicVersion(public)
            .setContentIntent(open(ctx, id)).setAutoCancel(true)
            .addAction(NotificationCompat.Action.Builder(0, "Deny", decide(false)).build())
            .addAction(NotificationCompat.Action.Builder(0, "Allow", decide(true)).setAuthenticationRequired(true).build())
            .build()
        runCatching { NotificationManagerCompat.from(ctx).notify("ask", id, n) }
    }

    fun cancelAsk(ctx: Context, call: String) = NotificationManagerCompat.from(ctx).cancel("ask", call.hashCode())

    /** Questions answered elsewhere (at the desk, or in the app) leave the shade. */
    fun keepAsks(ctx: Context, waiting: Set<String>) {
        val keep = waiting.map { it.hashCode() }.toSet()
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.activeNotifications.filter { it.tag == "ask" && it.id !in keep }.forEach { nm.cancel("ask", it.id) }
    }

    fun answered(ctx: Context, agent: String, chat: String?) {
        if (!may(ctx)) return
        val n = NotificationCompat.Builder(ctx, ANSWERS).setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK)
            .setContentTitle("$agent answered").setContentText("Open Super Agents to read it.")
            .setContentIntent(open(ctx, (chat ?: "answer").hashCode(), chat)).setAutoCancel(true).build()
        runCatching { NotificationManagerCompat.from(ctx).notify("answer", (chat ?: "answer").hashCode(), n) }
    }

    fun failed(ctx: Context, call: String, why: String) {
        if (!may(ctx)) return
        val n = NotificationCompat.Builder(ctx, ASKS).setSmallIcon(R.drawable.ic_stat_icon).setColor(BRICK)
            .setContentTitle("That didn't reach your laptop").setContentText(why)
            .setContentIntent(open(ctx, call.hashCode())).setAutoCancel(true).build()
        runCatching { NotificationManagerCompat.from(ctx).notify("ask", call.hashCode(), n) }
    }
}
