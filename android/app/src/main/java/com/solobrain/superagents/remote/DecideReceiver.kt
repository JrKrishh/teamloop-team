package com.solobrain.superagents.remote

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.solobrain.superagents.remote
import kotlinx.coroutines.launch

/** Deny or Approve, pressed on a question's notification: answered without opening the app. */
class DecideReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val approval = intent.getStringExtra("approval")  // a lead's yes to a member's agent, by the team's rules
        val turn = intent.getStringExtra("turn")
        val call = approval ?: intent.getStringExtra("call") ?: return
        if (approval == null && turn == null) return
        val approve = intent.getBooleanExtra("approve", false)
        val done = goAsync()
        val r = ctx.remote
        r.scope.launch {
            try {
                if (approval != null) r.decideTeam(approval, approve) else r.decide(turn!!, call, approve)
            } catch (e: Exception) {
                Notifications.failed(ctx, call, e.message ?: "Open Super Agents to answer it.")
            } finally {
                done.finish()
            }
        }
    }
}
