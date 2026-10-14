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
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Task

private val SAID = mapOf("blocked" to "blocked", "review" to "in review", "in_progress" to "in progress", "todo" to "to do", "done" to "done")

/** The team's board: active tasks first, Agent S's estimate from the sessions next to what the coding agent claims. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun BoardScreen(onChat: (ChatOpen) -> Unit) {
    val p = LocalPalette.current
    val r = LocalContext.current.remote
    val board by r.board.collectAsState()
    var only by remember { mutableStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf<Task?>(null) }
    LaunchedEffect(Unit) { runCatching { r.loadBoard() }.onFailure { error = it.message } }
    val b = board
    if (b == null) {
        Column(Modifier.fillMaxWidth().padding(top = 80.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Mascot(size = 84.dp, mood = Mood.Think)
            Spacer(Modifier.height(14.dp))
            Text(error ?: "Getting the board from your laptop…", color = p.muted)
        }
        return
    }
    val order = mapOf("blocked" to 0, "review" to 1, "in_progress" to 2)
    val groups = listOf(
        "Active" to b.tasks.filter { it.status in order }.sortedBy { order[it.status] },
        "To do" to b.tasks.filter { it.status == "todo" },
        "Done" to b.tasks.filter { it.status == "done" },
    )
    LazyColumn(contentPadding = PaddingValues(16.dp, 4.dp, 16.dp, 24.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                groups.forEachIndexed { i, (name, items) ->
                    SegmentedButton(selected = only == i, onClick = { only = i }, shape = SegmentedButtonDefaults.itemShape(i, groups.size),
                        label = { Text("$name ${items.size}") })
                }
            }
        }
        items(groups[only].second, key = { it.task }) { t -> TaskCard(t) { open = t } }
        if (groups[only].second.isEmpty()) item { Text(if (only == 0) "Nothing in progress." else "Nothing here.", color = p.muted, modifier = Modifier.padding(8.dp)) }
    }
    open?.let { t ->
        ModalBottomSheet(onDismissRequest = { open = null }, containerColor = p.bg2) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
                Text("${t.task} · ${t.title.ifEmpty { "No title yet" }}", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(10.dp))
                for ((name, lines) in listOf("Blocked" to t.blockers, "Now" to t.doing, "Next" to t.next)) if (lines.isNotEmpty()) {
                    Label(name)
                    for (line in lines) Text(line, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 3.dp))
                }
                if (t.blockers.isEmpty() && t.doing.isEmpty() && t.next.isEmpty()) Text("Agent S hasn't seen work on this yet.", color = p.muted)
                Spacer(Modifier.height(18.dp))
                Button(onClick = { open = null; onChat(ChatOpen(prefill = "What's the status of ${t.task}${if (t.title.isNotEmpty()) " (${t.title})" else ""}?")) },
                    modifier = Modifier.fillMaxWidth().height(50.dp), shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) { Text("Ask Agent S about ${t.task}") }
            }
        }
    }
}

@Composable
private fun TaskCard(t: Task, onOpen: () -> Unit) {
    val p = LocalPalette.current
    val blocked = t.status == "blocked"
    val shape = RoundedCornerShape(18.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(p.panel).border(1.dp, if (blocked) p.bad else p.line, shape).clickable(onClick = onOpen)
        .padding(16.dp).testTag("task")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(t.task, style = MaterialTheme.typography.labelSmall, color = p.brick)
            Spacer(Modifier.width(8.dp))
            Text(t.title.ifEmpty { "No title yet" }, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Spacer(Modifier.width(8.dp))
            val c = when (t.status) { "blocked" -> p.bad; "done", "review" -> p.ok; "todo" -> p.plan; else -> p.muted }
            Text((SAID[t.status] ?: t.status).uppercase(), style = MaterialTheme.typography.labelSmall, color = c,
                modifier = Modifier.border(1.dp, c, RoundedCornerShape(6.dp)).padding(horizontal = 6.dp, vertical = 2.dp))
        }
        t.percent?.let { pct ->
            Spacer(Modifier.height(12.dp))
            val known = t.tools.filter { it == "claude_code" || it == "codex" }
            val who = if (known.size == 1) (if (known[0] == "codex") "Codex" else "Claude Code") else "The agent"
            val gap = t.says != null && t.says - pct >= 15
            Row(verticalAlignment = Alignment.Bottom) {
                Text("$pct%", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.width(6.dp))
                Text("Agent S", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.weight(1f))
                t.says?.let { Text("$who says $it%", style = MaterialTheme.typography.bodySmall, color = if (gap) p.warn else p.muted) }
            }
            Spacer(Modifier.height(6.dp))
            Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(99.dp)).background(p.bg2)) {
                Box(Modifier.fillMaxWidth(pct / 100f).fillMaxHeight().clip(RoundedCornerShape(99.dp)).background(p.brick))
            }
            if (gap) Text("$who claims ${t.says!! - pct} points more than the evidence shows.", style = MaterialTheme.typography.bodySmall, color = p.warn,
                modifier = Modifier.padding(top = 6.dp))
        }
        val tags = listOfNotNull(t.owner, t.due?.let { "due ${it.drop(5)}" }, t.pr, t.blockers.size.takeIf { it > 0 }?.let { "$it blocker${if (it > 1) "s" else ""}" })
        if (tags.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                for (tag in tags) Text(tag, style = MaterialTheme.typography.labelMedium, color = p.muted,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(p.bg2).padding(horizontal = 8.dp, vertical = 3.dp))
            }
        }
    }
}
