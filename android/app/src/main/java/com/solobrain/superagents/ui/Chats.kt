package com.solobrain.superagents.ui

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
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote.Laptop
import java.util.Calendar

private val QUICK = listOf("What's blocked right now?", "Which tasks used the most AI this week?", "Plan our next tasks with owners and deadlines", "Write today's digest")

fun ago(t: Double): String {
    val s = (System.currentTimeMillis() / 1000.0 - t).coerceAtLeast(0.0)
    return when { s < 60 -> "now"; s < 3600 -> "${(s / 60).toInt()} min"; s < 86400 -> "${(s / 3600).toInt()} h"; else -> "${(s / 86400).toInt()} d" }
}

fun parseColor(hex: String?): Color? = hex?.let { runCatching { Color(android.graphics.Color.parseColor(it)) }.getOrNull() }

/** Your chats on the laptop: search, a few one-tap questions, and the list by day. */
@Composable
fun Chats(laptop: Laptop?, onChat: (ChatOpen) -> Unit) {
    val p = LocalPalette.current
    var q by remember { mutableStateOf("") }
    if (laptop == null) return Waiting(com.solobrain.superagents.remote.Link.Connecting)
    val shown = laptop.chats.filter { q.isBlank() || it.title.contains(q.trim(), ignoreCase = true) }
    val midnight = Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0) }.timeInMillis / 1000.0
    val groups = listOf("Today" to shown.filter { it.updated >= midnight }, "Earlier" to shown.filter { it.updated < midnight })
    LazyColumn(contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 96.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        item {
            OutlinedTextField(q, { q = it }, Modifier.fillMaxWidth().testTag("search"), singleLine = true, shape = RoundedCornerShape(14.dp),
                placeholder = { Text("Search chats") }, leadingIcon = { Icon(Glyph.Search, null, Modifier.size(20.dp)) })
        }
        if (q.isBlank()) item {
            LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                items(QUICK) { text ->
                    AssistChip(onClick = { onChat(ChatOpen(prefill = text, send = true)) }, label = { Text(text) }, shape = RoundedCornerShape(999.dp),
                        colors = AssistChipDefaults.assistChipColors(containerColor = p.panel))
                }
            }
        }
        for ((name, items) in groups) {
            if (items.isEmpty()) continue
            item { Label(name) }
            items(items, key = { it.id }) { c ->
                val a = laptop.agent(c.agent)
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(p.panel).border(1.dp, p.line, RoundedCornerShape(16.dp))
                    .clickable { onChat(ChatOpen(c.id)) }.padding(14.dp).testTag("chat-row"), verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp).background(parseColor(a.color) ?: p.brick, CircleShape))
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(c.title.ifEmpty { "Untitled chat" }, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(a.name, style = MaterialTheme.typography.bodySmall)
                    }
                    Text(ago(c.updated), style = MaterialTheme.typography.bodySmall, color = p.faint)
                }
            }
        }
        if (shown.isEmpty()) item { Text(if (q.isBlank()) "No chats yet. Ask something below." else "No chat matches.", color = p.muted, modifier = Modifier.padding(8.dp)) }
    }
}
