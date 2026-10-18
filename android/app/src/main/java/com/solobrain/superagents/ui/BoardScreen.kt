package com.solobrain.superagents.ui

import android.widget.Toast
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Note
import com.solobrain.superagents.remote.Task
import kotlinx.coroutines.launch

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
        items(b.overlaps, key = { "overlap-" + it.file }) { o ->  // two sessions in one file: where merge conflicts start
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(p.warn.copy(alpha = 0.13f)).padding(12.dp)) {
                Text(buildString { append(o.file); append(" was edited by "); append(o.who.joinToString(" and ")); append(" in the last half hour.") },
                    style = MaterialTheme.typography.bodyMedium)
            }
        }
        items(groups[only].second, key = { it.task }) { t -> TaskCard(t) { open = t } }
        if (groups[only].second.isEmpty()) item { Text(if (only == 0) "Nothing in progress." else "Nothing here.", color = p.muted, modifier = Modifier.padding(8.dp)) }
    }
    open?.let { t ->
        ModalBottomSheet(onDismissRequest = { open = null }, containerColor = p.bg2) {
            Column(Modifier.fillMaxWidth().imePadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
                Text("${t.task} · ${t.title.ifEmpty { "No title yet" }}", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(10.dp))
                for ((name, lines) in listOf("Blocked" to t.blockers, "Now" to t.doing, "Next" to t.next)) if (lines.isNotEmpty()) {
                    Label(name)
                    for (line in lines) Text(line, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 3.dp))
                }
                if (t.blockers.isEmpty() && t.doing.isEmpty() && t.next.isEmpty()) Text("Agent S hasn't seen work on this yet.", color = p.muted)
                if (t.editing.isNotEmpty()) {
                    Label("Editing now")
                    for (f in t.editing) Text(f, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 3.dp))
                }
                Notes(t.task)
                Spacer(Modifier.height(18.dp))
                Button(onClick = { open = null; onChat(ChatOpen(prefill = "What's the status of ${t.task}${if (t.title.isNotEmpty()) " (${t.title})" else ""}?")) },
                    modifier = Modifier.fillMaxWidth().height(50.dp), shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) { Text("Ask Agent S about ${t.task}") }
            }
        }
    }
}

/** A task's notes between the people and coding agents on it, as on the desktop: read them, and leave one for everyone
 *  else on the task, or reply to one person. Their agents read it at their next step. */
@Composable
private fun Notes(task: String) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val r = ctx.remote
    val scope = rememberCoroutineScope()
    var notes by remember(task) { mutableStateOf<List<Note>?>(null) }
    var error by remember(task) { mutableStateOf<String?>(null) }
    var to by remember(task) { mutableStateOf<String?>(null) }  // null: everyone else on the task
    var draft by remember(task) { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    LaunchedEffect(task) { runCatching { r.notes(task) }.onSuccess { notes = it }.onFailure { error = it.message } }
    Label("Notes")
    val ns = notes
    when {
        ns == null -> Text(error ?: "Getting the notes…", style = MaterialTheme.typography.bodySmall, color = p.muted)
        ns.isEmpty() -> Text("No notes yet. Agents leave one when a change affects someone else's work.", style = MaterialTheme.typography.bodySmall, color = p.muted)
        else -> for (n in ns.takeLast(10)) {
            Column(Modifier.fillMaxWidth().padding(vertical = 3.dp).clip(RoundedCornerShape(12.dp)).background(p.panel).padding(horizontal = 12.dp, vertical = 8.dp)) {
                Text(n.text, style = MaterialTheme.typography.bodyMedium)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    val who = if (n.mine) (if (n.agent) "your agent" else "you") else n.from + if (n.agent) "'s agent" else ""
                    Text("$who → ${n.to ?: "everyone"} · ${ago(n.at)}", style = MaterialTheme.typography.bodySmall, color = p.faint, modifier = Modifier.weight(1f))
                    if (!n.mine) Text("Reply", style = MaterialTheme.typography.labelMedium, color = p.brick,
                        modifier = Modifier.clickable { to = n.from }.padding(6.dp))
                }
            }
        }
    }
    if (ns == null && error != null) return
    Spacer(Modifier.height(8.dp))
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(to?.let { "To $it" } ?: "To everyone else on $task", style = MaterialTheme.typography.labelMedium, color = p.muted)
        if (to != null) Text("Everyone instead", style = MaterialTheme.typography.labelMedium, color = p.brick,
            modifier = Modifier.clickable { to = null }.padding(horizontal = 10.dp, vertical = 4.dp))
    }
    OutlinedTextField(draft, { draft = it.take(1000) }, Modifier.fillMaxWidth().testTag("note"), maxLines = 4, shape = RoundedCornerShape(14.dp),
        placeholder = { Text("A note for them and their agents") },
        trailingIcon = {
            IconButton(enabled = draft.isNotBlank() && !sending, onClick = {
                sending = true
                scope.launch {
                    runCatching { r.note(task, to ?: "task", draft.trim()) }
                        .onSuccess { (fresh, skipped) ->
                            notes = fresh; draft = ""
                            if (skipped.isNotEmpty()) Toast.makeText(ctx, "Not to ${skipped.joinToString(", ")}: they turned off notes from teammates.", Toast.LENGTH_LONG).show()
                        }
                        .onFailure { Toast.makeText(ctx, it.message ?: "Couldn't reach your laptop.", Toast.LENGTH_LONG).show() }
                    sending = false
                }
            }) { Icon(Glyph.Up, "Send the note") }
        })
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
