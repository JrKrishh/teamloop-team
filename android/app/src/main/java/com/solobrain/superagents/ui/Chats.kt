package com.solobrain.superagents.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote.ChatItem
import com.solobrain.superagents.remote.Laptop
import com.solobrain.superagents.remote.Link

private val QUICK = listOf("What's blocked right now?", "Which tasks used the most AI this week?", "Plan our next tasks with owners and deadlines", "Write today's digest")
private const val GENERAL = "General"  // chats that worked in no repo: the team, the board, questions

fun ago(t: Double): String {
    val s = (System.currentTimeMillis() / 1000.0 - t).coerceAtLeast(0.0)
    return when { s < 60 -> "now"; s < 3600 -> "${(s / 60).toInt()} min"; s < 86400 -> "${(s / 3600).toInt()} h"; else -> "${(s / 86400).toInt()} d" }
}

fun parseColor(hex: String?): Color? = hex?.let { runCatching { Color(android.graphics.Color.parseColor(it)) }.getOrNull() }

/** Your chats on the laptop: search, a few one-tap questions, the latest three, then each project's chats in a folder
 *  of its own (the repo its agent worked in), so a long history stays a short list. */
@Composable
fun Chats(laptop: Laptop?, onChat: (ChatOpen) -> Unit) {
    val p = LocalPalette.current
    var q by remember { mutableStateOf("") }
    val open = remember { mutableStateMapOf<String, Boolean>() }
    if (laptop == null) return Waiting(Link.Connecting)
    val query = q.trim()
    val shown = laptop.chats.filter { query.isEmpty() || it.title.contains(query, ignoreCase = true) || it.project.orEmpty().contains(query, ignoreCase = true) }
    val folders = shown.groupBy { it.project ?: GENERAL }.toList().sortedByDescending { (_, chats) -> chats.maxOf { it.updated } }
    LazyColumn(contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 96.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            OutlinedTextField(q, { q = it }, Modifier.fillMaxWidth().testTag("search"), singleLine = true, shape = RoundedCornerShape(14.dp),
                placeholder = { Text("Search chats and projects") }, leadingIcon = { Icon(Glyph.Search, null, Modifier.size(20.dp)) })
        }
        if (query.isEmpty()) item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(QUICK) { text ->
                    AssistChip(onClick = { onChat(ChatOpen(prefill = text, send = true)) }, label = { Text(text) }, shape = RoundedCornerShape(999.dp),
                        colors = AssistChipDefaults.assistChipColors(containerColor = p.panel))
                }
            }
        }
        if (query.isNotEmpty()) {
            if (shown.isNotEmpty()) item { ChatList(shown, laptop, onChat) }
        } else if (shown.isNotEmpty()) {
            item { Label("Recent") }
            item { ChatList(shown.take(3), laptop, onChat) }
            item { Label("Projects") }
            items(folders, key = { "folder-" + it.first }) { (name, chats) ->
                val isOpen = open[name] ?: (folders.size == 1)
                Folder(name, chats, isOpen, { open[name] = !isOpen }, laptop, onChat)
            }
        }
        if (shown.isEmpty()) item { Text(if (query.isEmpty()) "No chats yet. Ask something below." else "No chat matches.", color = p.muted, modifier = Modifier.padding(8.dp)) }
    }
}

/** Chats as rows in one card: a lot less to scroll than a card each. */
@Composable
private fun ChatList(chats: List<ChatItem>, laptop: Laptop, onChat: (ChatOpen) -> Unit) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(p.panel).border(1.dp, p.line, RoundedCornerShape(16.dp))) {
        chats.forEachIndexed { i, c ->
            if (i > 0) HorizontalDivider(Modifier.padding(start = 36.dp), color = p.line)
            ChatRow(c, laptop, onChat, withProject = true)
        }
    }
}

@Composable
private fun ChatRow(c: ChatItem, laptop: Laptop, onChat: (ChatOpen) -> Unit, withProject: Boolean) {
    val p = LocalPalette.current
    val a = laptop.agent(c.agent)
    Row(Modifier.fillMaxWidth().clickable { onChat(ChatOpen(c.id)) }.padding(horizontal = 14.dp, vertical = 12.dp).testTag("chat-row"),
        verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(10.dp).background(parseColor(a.color) ?: p.brick, CircleShape))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(c.title.ifEmpty { "Untitled chat" }, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(if (withProject && c.project != null) "${a.name} · ${c.project}" else a.name, style = MaterialTheme.typography.bodySmall,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(8.dp))
        Text(ago(c.updated), style = MaterialTheme.typography.bodySmall, color = p.faint)
    }
}

/** A project's folder: its name, how many chats and how recent; it opens in place to show them. */
@Composable
private fun Folder(name: String, chats: List<ChatItem>, open: Boolean, onToggle: () -> Unit, laptop: Laptop, onChat: (ChatOpen) -> Unit) {
    val p = LocalPalette.current
    val turn by animateFloatAsState(if (open) 90f else 0f, label = "folder")
    val last = ago(chats.maxOf { it.updated }).let { if (it == "now") "just now" else "$it ago" }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(p.panel).border(1.dp, p.line, RoundedCornerShape(16.dp))) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(14.dp).testTag("folder"), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)).background(p.panel2), contentAlignment = Alignment.Center) {
                Icon(Glyph.Folder, null, Modifier.size(20.dp), tint = if (name == GENERAL) p.muted else p.brick)
            }
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("${chats.size} chat${if (chats.size == 1) "" else "s"} · $last", style = MaterialTheme.typography.bodySmall)
            }
            Icon(Glyph.Right, if (open) "Close $name" else "Open $name", Modifier.size(18.dp).rotate(turn), tint = p.muted)
        }
        AnimatedVisibility(open, enter = expandVertically() + fadeIn(), exit = shrinkVertically() + fadeOut()) {
            Column {
                for (c in chats) {
                    HorizontalDivider(color = p.line)
                    ChatRow(c, laptop, onChat, withProject = false)
                }
            }
        }
    }
}
