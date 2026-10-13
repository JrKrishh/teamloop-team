package com.solobrain.superagents.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.solobrain.superagents.MainActivity
import com.solobrain.superagents.Prefs
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Laptop
import com.solobrain.superagents.remote.Link
import com.solobrain.superagents.remote.LinkService
import com.solobrain.superagents.remote.LiveTurn

enum class Tab(val title: String, val icon: ImageVector) { Needs("Needs you", Glyph.Inbox), Chats("Chats", Glyph.Chat), Board("Board", Glyph.Board) }

/** Opening a chat: an existing one, one still on its first turn (live), or a new one, maybe with a question ready. */
data class ChatOpen(val id: String? = null, val live: LiveTurn? = null, val prefill: String? = null, val send: Boolean = false)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Home(activity: MainActivity, tab: Tab, onTab: (Tab) -> Unit, onChat: (ChatOpen) -> Unit, onForgotten: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val r = ctx.remote
    val laptop by r.laptop.collectAsState()
    val link by r.link.collectAsState()
    val board by r.board.collectAsState()
    val haptic = LocalHapticFeedback.current
    var settings by remember { mutableStateOf(false) }
    val waiting = laptop?.live?.count { it.ask != null } ?: 0

    Scaffold(
        containerColor = p.bg,
        topBar = {
            Row(Modifier.fillMaxWidth().background(p.bg).statusBarsPadding().padding(start = 20.dp, end = 12.dp, top = 10.dp, bottom = 6.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(if (tab == Tab.Board) board?.room ?: "Board" else tab.title, style = MaterialTheme.typography.headlineSmall)
                    Status(link, laptop)
                }
                IconButton(onClick = { settings = true }, modifier = Modifier.testTag("settings")) { Icon(Glyph.Gear, "Settings", tint = p.muted) }
            }
        },
        bottomBar = {
            NavigationBar(containerColor = p.bg2) {
                for (t in Tab.entries) NavigationBarItem(
                    selected = t == tab,
                    onClick = { haptic.performHapticFeedback(HapticFeedbackType.SegmentTick); onTab(t) },
                    icon = {
                        if (t == Tab.Needs && waiting > 0) BadgedBox(badge = { Badge(containerColor = p.warn) { Text("$waiting") } }) { Icon(t.icon, null) }
                        else Icon(t.icon, null)
                    },
                    label = { Text(t.title) },
                    modifier = Modifier.testTag("tab-${t.name.lowercase()}"),
                    colors = NavigationBarItemDefaults.colors(selectedIconColor = p.brick, selectedTextColor = p.brick, indicatorColor = p.panel2,
                        unselectedIconColor = p.faint, unselectedTextColor = p.faint),
                )
            }
        },
        floatingActionButton = {
            if (tab == Tab.Chats) ExtendedFloatingActionButton(onClick = { onChat(ChatOpen()) }, containerColor = p.brick, contentColor = p.onBrick,
                modifier = Modifier.testTag("new-chat")) {
                Icon(Glyph.Plus, null); Spacer(Modifier.width(8.dp)); Text("New chat")
            }
        },
    ) { pad ->
        Box(Modifier.fillMaxSize().padding(pad)) {
            when (tab) {
                Tab.Needs -> NeedsYou(laptop, link, onChat)
                Tab.Chats -> Chats(laptop, onChat)
                Tab.Board -> BoardScreen(onChat)
            }
        }
    }

    if (settings) ModalBottomSheet(onDismissRequest = { settings = false }, containerColor = p.bg2) {
        Settings(activity, laptop, link, onForget = { settings = false; LinkService.stop(ctx); r.forget(); onForgotten() })
    }
}

@Composable
fun Status(link: Link, laptop: Laptop?) {
    val p = LocalPalette.current
    val (color, text) = when (link) {
        Link.Online -> p.ok to "Online · ${laptop?.host ?: "your laptop"}"
        Link.Connecting -> p.faint to "Connecting…"
        Link.Offline -> p.warn to "Your laptop isn't answering"
        Link.NotPaired -> p.faint to "Not paired"
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(7.dp).background(color, CircleShape))
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.testTag("status"))
    }
}

@Composable
private fun Settings(activity: MainActivity, laptop: Laptop?, link: Link, onForget: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    var lock by remember { mutableStateOf(Prefs.lock(ctx)) }
    var notify by remember { mutableStateOf(Prefs.notify(ctx)) }
    var stay by remember { mutableStateOf(Prefs.stay(ctx)) }
    var sure by remember { mutableStateOf(false) }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> notify = granted; Prefs.setNotify(ctx, granted) }
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
        Text("Settings", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(14.dp))
        Row(Modifier.fillMaxWidth().background(p.panel, RoundedCornerShape(16.dp)).border(1.dp, p.line, RoundedCornerShape(16.dp)).padding(14.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Mascot(size = 40.dp, mood = if (link == Link.Online) Mood.Idle else Mood.Sleep)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(laptop?.name ?: "Your laptop", style = MaterialTheme.typography.titleMedium)
                Status(link, laptop)
            }
        }
        Spacer(Modifier.height(8.dp))
        if (activity.canLock()) Toggle("Lock with fingerprint", "On opening, and after a minute away.", lock) { on ->
            if (!on) { lock = false; Prefs.setLock(ctx, false) } else activity.authenticate { ok -> if (ok) { lock = true; Prefs.setLock(ctx, true) } }
        }
        Toggle("Notify me", "When an agent needs you or answers, while the app is closed.", notify) { on ->
            val granted = Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
            if (on && !granted && Build.VERSION.SDK_INT >= 33) ask.launch(Manifest.permission.POST_NOTIFICATIONS)
            else { notify = on; Prefs.setNotify(ctx, on) }
        }
        Toggle("Stay connected in the background", "So questions reach you when the app is closed. Android shows a small notice while it's on.", stay) { on ->
            stay = on; Prefs.setStay(ctx, on); if (on) LinkService.start(ctx) else LinkService.stop(ctx)
        }
        Spacer(Modifier.height(16.dp))
        Text("End-to-end encrypted: only this phone and your laptop hold the key. To cut this phone off from the laptop, unpair it there.",
            style = MaterialTheme.typography.bodySmall)
        Spacer(Modifier.height(14.dp))
        OutlinedButton(onClick = { if (sure) onForget() else sure = true }, modifier = Modifier.fillMaxWidth().testTag("forget"), shape = RoundedCornerShape(14.dp),
            contentPadding = PaddingValues(14.dp)) {
            Text(if (sure) "Forget it: press again" else "Forget this laptop", color = if (sure) p.bad else p.text)
        }
        Spacer(Modifier.height(10.dp))
        val version = remember { runCatching { ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName }.getOrNull().orEmpty() }
        Text("Super Agents $version for Android · MIT licence", style = MaterialTheme.typography.bodySmall, color = p.faint)
    }
}

@Composable
private fun Toggle(title: String, sub: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(sub, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.width(12.dp))
        Switch(on, onChange)
    }
}
