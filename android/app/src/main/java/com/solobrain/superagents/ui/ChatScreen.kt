package com.solobrain.superagents.ui

import android.widget.Toast
import androidx.activity.compose.BackHandler
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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Labels
import com.solobrain.superagents.remote.objects
import com.solobrain.superagents.remote.text
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.TreeMap

/** One tool call in a turn, as it moves from asking or running to done. */
class Card(val id: String) {
    var name by mutableStateOf("")
    var args by mutableStateOf(JSONObject())
    var status by mutableStateOf("")
    var result by mutableStateOf<String?>(null)
}

/** One agent turn in the chat: its steps, what it said along the way, what waits for you, and its answer. */
class Block(val agent: String?, val past: Boolean = false) {
    var turn: String? = null
    val cards = mutableStateMapOf<String, Card>()
    val order = mutableStateListOf<String>()
    val notes = mutableStateListOf<String>()
    var answer by mutableStateOf<String?>(null)
    var failed by mutableStateOf<String?>(null)
    var line by mutableStateOf<String?>(if (past) null else "Thinking…")
    var planned by mutableIntStateOf(0)
    var planDone by mutableStateOf(false)
    var next = 0
    val buf = TreeMap<Int, JSONObject>()
    var asked = 0L
    fun waiting(c: Card) = !past && (c.status == "asking" || c.status == "planned")
}

sealed interface Item {
    data class User(val text: String) : Item
    class Agent(val block: Block) : Item
}

/** The chat's model: events from the laptop, applied strictly in order; a gap asks for what's missing. */
class ChatModel {
    val items = mutableStateListOf<Item>()
    private val blocks = HashMap<String, Block>()
    private val early = HashMap<String, MutableList<JSONObject>>()
    var running by mutableStateOf<String?>(null)
    var chatId: String? = null
    var title by mutableStateOf("New chat")
    var tick by mutableIntStateOf(0)

    fun user(text: String) { items.add(Item.User(text)); tick++ }
    fun nextOf(turn: String) = blocks[turn]?.next ?: 0
    fun agent(agent: String?, past: Boolean = false): Block = Block(agent, past).also { items.add(Item.Agent(it)); tick++ }

    fun bind(turn: String, b: Block, catchUp: (String, Int) -> Unit) {
        b.turn = turn
        blocks[turn] = b
        early.remove(turn)?.let { onEvents(turn, it, catchUp) }
    }

    fun onEvents(turn: String, evs: List<JSONObject>, catchUp: (String, Int) -> Unit) {
        val b = blocks[turn] ?: run { early.getOrPut(turn) { mutableListOf() }.addAll(evs); return }
        for (e in evs) { val i = e.optInt("i", -1); if (i >= b.next) b.buf[i] = e }
        while (b.buf.containsKey(b.next)) { val e = b.buf.remove(b.next)!!; b.next++; apply(b, e) }
        if (b.buf.isNotEmpty() && System.currentTimeMillis() - b.asked > 3000) { b.asked = System.currentTimeMillis(); catchUp(turn, b.next) }
    }

    fun apply(b: Block, e: JSONObject) {
        when (e.optString("kind")) {
            "thinking" -> b.line = "Thinking…"
            "text" -> b.notes.add(e.optString("text"))
            "tool" -> {
                val id = e.optString("id")
                val c = b.cards[id] ?: Card(id).also { b.cards[id] = it; b.order.add(id) }
                if (e.has("name")) c.name = e.optString("name")
                e.optJSONObject("args")?.let { c.args = it }
                c.status = e.optString("status")
                if (e.has("result") && !e.isNull("result")) c.result = e.optString("result")
                if (!b.past) b.line = when (c.status) { "asking" -> "Waiting for you…"; "running" -> "Working…"; else -> b.line }
            }
            "answer" -> { b.answer = e.optString("text"); b.line = null }
            "error" -> { b.failed = e.optString("text"); b.line = null }
            "end" -> {
                if (b.answer != null || b.failed != null) b.line = null
                if (!b.past) b.planned = e.optInt("planned")
                if (running == b.turn) running = null
                b.line = null
            }
        }
        tick++
    }
}

private val MODES = listOf("manual" to "Manual", "auto" to "Auto", "plan" to "Plan")
private val MODE_HINT = mapOf("manual" to "Asks before each change", "auto" to "Routine changes itself; commands still ask", "plan" to "Nothing changes until you run the plan")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(open: ChatOpen, onBack: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val r = ctx.remote
    val laptop by r.laptop.collectAsState()
    val scope = rememberCoroutineScope()
    val haptic = LocalHapticFeedback.current
    val model = remember { ChatModel() }
    val list = rememberLazyListState()
    var text by remember { mutableStateOf(open.prefill.orEmpty()) }
    var agent by remember { mutableStateOf(open.live?.agent ?: "agent-s") }
    var mode by remember { mutableStateOf("manual") }
    var picking by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(open.id != null) }
    val catchUp: (String, Int) -> Unit = { turn, after -> scope.launch { runCatching { r.watch(turn, after) } } }
    BackHandler(onBack = onBack)

    fun send(message: String) {
        val msg = message.trim()
        if (msg.isEmpty() || model.running != null) return
        text = ""
        haptic.performHapticFeedback(HapticFeedbackType.Confirm)
        model.user(msg)
        val b = model.agent(agent)
        if (model.title == "New chat") model.title = msg.take(60)
        scope.launch {
            runCatching { r.send(model.chatId, agent, mode, msg) }
                .onSuccess { (turn, chat) -> model.chatId = chat; model.running = turn; model.bind(turn, b, catchUp) }
                .onFailure { b.failed = it.message; b.line = null }
        }
    }

    LaunchedEffect(Unit) {
        launch { r.events.collect { (turn, evs) -> model.onEvents(turn, evs, catchUp) } }
        val live = open.live
        if (open.id != null) {
            model.chatId = open.id
            runCatching { r.chat(open.id) }.onSuccess { c ->
                model.title = c.optString("title").ifEmpty { "Chat" }
                c.optString("agent").takeIf { it.isNotEmpty() }?.let { agent = it }
                for (v in c.optJSONArray("view").objects()) {
                    model.user(v.optString("user"))
                    val b = model.agent(v.optString("agent").ifEmpty { agent }, past = true)
                    for (e in v.optJSONArray("events").objects()) model.apply(b, e)
                    b.answer = v.text("answer")
                    b.line = null
                }
            }.onFailure { if (live == null) Toast.makeText(ctx, it.message, Toast.LENGTH_LONG).show() else model.title = live.message.take(60) }
            loading = false
        }
        val watching = live ?: laptop?.live?.firstOrNull { it.chat != null && it.chat == open.id }
        if (watching != null) {  // a turn running now, maybe started at the desk
            model.user(watching.message)
            val b = model.agent(watching.agent)
            model.running = watching.turn
            model.bind(watching.turn, b, catchUp)
            runCatching { r.watch(watching.turn, 0, watching.chat, watching.agent) }
        }
        if (open.send && !open.prefill.isNullOrBlank()) send(open.prefill)
    }
    LaunchedEffect(model.running) {  // anything lost at a turn's very end comes back within 30 s
        while (model.running != null) { delay(30_000); model.running?.let { t -> catchUp(t, model.nextOf(t)) } }
    }
    LaunchedEffect(model.tick) { if (model.items.isNotEmpty()) list.animateScrollToItem(model.items.size - 1, scrollOffset = 100_000) }

    Column(Modifier.fillMaxSize().background(p.bg).imePadding()) {
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 8.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack, modifier = Modifier.testTag("back")) { Icon(Glyph.Back, "Back") }
            Column(Modifier.weight(1f)) {
                Text(model.title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("${laptop?.agent(agent)?.name ?: "Agent S"} · ${MODES.first { it.first == mode }.second}", style = MaterialTheme.typography.bodySmall)
            }
        }
        Box(Modifier.fillMaxWidth().weight(1f)) {
            if (loading) Column(Modifier.fillMaxWidth().padding(top = 80.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Mascot(size = 72.dp, mood = Mood.Think); Text("Opening…", color = p.muted)
            }
            LazyColumn(state = list, contentPadding = PaddingValues(16.dp, 12.dp, 16.dp, 20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                itemsIndexed(model.items) { _, item ->
                    when (item) {
                        is Item.User -> Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            Text(item.text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.widthIn(max = 300.dp)
                                .clip(RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp)).background(p.panel2).padding(horizontal = 14.dp, vertical = 10.dp))
                        }
                        is Item.Agent -> AgentBlock(item.block, laptop?.agent(item.block.agent)?.name ?: "Agent S",
                            laptop?.agent(item.block.agent)?.color, model)
                    }
                }
            }
        }
        Composer(text, { text = it }, model.running != null, "${laptop?.agent(agent)?.name ?: "Agent S"} · ${MODES.first { it.first == mode }.second}",
            parseColor(laptop?.agent(agent)?.color) ?: p.brick, onPick = { picking = true },
            onSend = { send(text) }, onStop = { model.running?.let { t -> haptic.performHapticFeedback(HapticFeedbackType.Reject); scope.launch { runCatching { r.stopTurn(t) } } } })
    }

    if (picking) ModalBottomSheet(onDismissRequest = { picking = false }, containerColor = p.bg2) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
            Text("Who, and how", style = MaterialTheme.typography.titleLarge)
            Label("Agent")
            for (a in laptop?.agents.orEmpty()) Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp))
                .background(if (a.id == agent) p.panel2 else p.bg2).clickable { agent = a.id; a.mode?.let { m -> if (MODES.any { it.first == m }) mode = m }; picking = false }
                .padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).background(parseColor(a.color) ?: p.brick, CircleShape)); Spacer(Modifier.width(12.dp))
                Text(a.name, style = MaterialTheme.typography.titleMedium)
            }
            Label("Mode")
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                MODES.forEachIndexed { i, (k, name) ->
                    SegmentedButton(selected = mode == k, onClick = { mode = k }, shape = SegmentedButtonDefaults.itemShape(i, MODES.size), label = { Text(name) })
                }
            }
            Text(MODE_HINT[mode].orEmpty(), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
        }
    }
}

@Composable
private fun Composer(text: String, onText: (String) -> Unit, running: Boolean, who: String, dot: androidx.compose.ui.graphics.Color,
                     onPick: () -> Unit, onSend: () -> Unit, onStop: () -> Unit) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxWidth().background(p.bg).navigationBarsPadding().padding(horizontal = 12.dp, vertical = 8.dp)) {
        Row(Modifier.clip(RoundedCornerShape(999.dp)).border(1.dp, p.line2, RoundedCornerShape(999.dp)).background(p.panel).clickable(onClick = onPick)
            .padding(horizontal = 12.dp, vertical = 6.dp).testTag("pick"), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(9.dp).background(dot, CircleShape)); Spacer(Modifier.width(8.dp))
            Text(who, style = MaterialTheme.typography.labelMedium, color = p.muted); Spacer(Modifier.width(4.dp))
            Icon(Glyph.Down, null, Modifier.size(16.dp), tint = p.muted)
        }
        Spacer(Modifier.size(8.dp))
        Row(verticalAlignment = Alignment.Bottom) {
            OutlinedTextField(text, onText, Modifier.weight(1f).heightIn(min = 52.dp, max = 180.dp).testTag("input"), shape = RoundedCornerShape(18.dp),
                placeholder = { Text("Message your laptop's agents") })
            Spacer(Modifier.width(8.dp))
            FilledIconButton(onClick = { if (running) onStop() else onSend() }, modifier = Modifier.size(52.dp).testTag("send"),
                colors = IconButtonDefaults.filledIconButtonColors(containerColor = if (running) p.panel2 else p.brick, contentColor = if (running) p.text else p.onBrick)) {
                Icon(if (running) Glyph.Stop else Glyph.Up, if (running) "Stop" else "Send")
            }
        }
    }
}

@Composable
private fun AgentBlock(b: Block, name: String, color: String?, model: ChatModel) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val r = ctx.remote
    val scope = rememberCoroutineScope()
    val folded = b.order.mapNotNull { b.cards[it] }.filter { !b.waiting(it) }
    val waiting = b.order.mapNotNull { b.cards[it] }.filter { b.waiting(it) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(10.dp).background(parseColor(color) ?: p.brick, CircleShape)); Spacer(Modifier.width(8.dp))
            Text(name, style = MaterialTheme.typography.titleMedium)
        }
        if (folded.isNotEmpty() || b.notes.isNotEmpty()) Steps(b, folded)
        for (c in waiting) ToolCard(c, b, open = true, onDecide = { ok ->
            scope.launch { runCatching { r.decide(b.turn ?: return@launch, c.id, ok) }.onFailure { Toast.makeText(ctx, it.message, Toast.LENGTH_LONG).show() } }
        })
        b.line?.let { Row(verticalAlignment = Alignment.CenterVertically) { Mascot(size = 26.dp, mood = Mood.Think); Spacer(Modifier.width(8.dp)); Text(it, color = p.muted) } }
        b.answer?.let { Markdown(it) }
        b.failed?.let { Text(it, color = p.bad) }
        if (b.planned > 0 && !b.planDone && model.running != b.turn) Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).border(1.dp, p.plan, RoundedCornerShape(14.dp))
            .background(p.panel).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("${b.planned} change${if (b.planned > 1) "s" else ""} planned. Nothing has changed yet.", style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            OutlinedButton(onClick = { b.planDone = true; for (c in waiting.filter { it.status == "planned" }) c.status = "discarded" }) { Text("Discard") }
            Spacer(Modifier.width(6.dp))
            Button(onClick = { b.planDone = true; model.running = b.turn; scope.launch { runCatching { r.runPlan(b.turn ?: return@launch) } } },
                colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) { Text("Run plan") }
        }
    }
}

/** The turn's steps, folded into one line like Claude Code's: what they did, what failed or never ran, what's running. */
@Composable
private fun Steps(b: Block, folded: List<Card>) {
    val p = LocalPalette.current
    var openSteps by remember { mutableStateOf(false) }
    val turn by animateFloatAsState(if (openSteps) 90f else 0f, label = "caret")
    val skipped = folded.count { it.status in setOf("asking", "planned", "discarded", "declined") }
    val ran = folded.filter { it.status !in setOf("asking", "planned", "discarded", "declined") }
    val failed = ran.count { it.status == "failed" }
    val now = ran.lastOrNull { it.status == "running" }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(p.bg2).border(1.dp, p.line, RoundedCornerShape(14.dp))) {
        Row(Modifier.fillMaxWidth().clickable { openSteps = !openSteps }.padding(horizontal = 12.dp, vertical = 10.dp).testTag("steps"), verticalAlignment = Alignment.CenterVertically) {
            Icon(Glyph.Right, null, Modifier.size(16.dp).rotate(turn), tint = p.faint)
            Spacer(Modifier.width(8.dp))
            Text(if (ran.isEmpty() && skipped == 0) "Notes along the way" else Labels.summary(ran.map { it.name }),
                style = MaterialTheme.typography.bodyMedium, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
            if (skipped > 0) Text("  $skipped not run", style = MaterialTheme.typography.labelSmall, color = p.faint)
            if (failed > 0) Text("  $failed failed", style = MaterialTheme.typography.labelSmall, color = p.bad)
            now?.let { Spacer(Modifier.weight(1f)); Text(Labels.line(com.solobrain.superagents.remote.Step(it.id, it.name, it.args)),
                style = MaterialTheme.typography.labelSmall, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 140.dp)) }
        }
        AnimatedVisibility(openSteps, enter = expandVertically() + fadeIn(), exit = shrinkVertically() + fadeOut()) {
            Column(Modifier.fillMaxWidth().padding(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                for (n in b.notes) Text(n, style = MaterialTheme.typography.bodyMedium, color = p.muted, modifier = Modifier.padding(horizontal = 4.dp))
                for (c in folded) ToolCard(c, b, open = false, onDecide = {})
            }
        }
    }
}

@Composable
private fun ToolCard(c: Card, b: Block, open: Boolean, onDecide: (Boolean) -> Unit) {
    val p = LocalPalette.current
    var showOut by remember { mutableStateOf(false) }
    var busy by remember(c.status) { mutableStateOf(false) }
    val (verb, what) = Labels.of(c.name, c.args)
    val color = when (c.status) { "done" -> p.ok; "failed" -> p.bad; "asking" -> p.warn; "planned" -> p.plan; else -> p.faint }
    val said = mapOf("running" to "running", "asking" to "needs you", "planned" to "planned", "done" to "✓ done", "failed" to "✕ failed",
        "declined" to "declined", "discarded" to "discarded")[c.status] ?: c.status
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.panel)
        .border(1.dp, if (open) color.copy(alpha = 0.7f) else p.line, RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().clickable(enabled = c.result != null) { showOut = !showOut }.padding(horizontal = 10.dp, vertical = 9.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text(verb, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.width(8.dp))
            Text(what, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            Text(said, style = MaterialTheme.typography.labelSmall, color = color)
        }
        if (showOut) c.result?.let {
            Text(it, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text), maxLines = 30, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth().background(p.bg2).padding(10.dp))
        }
        if (open && c.status == "asking") Column(Modifier.fillMaxWidth().padding(10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val detail = Labels.detail(c.name, c.args)
            if (detail.isNotEmpty()) Text(detail, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text), maxLines = 10, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(p.bg2).padding(10.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { busy = true; onDecide(false) }, enabled = !busy, modifier = Modifier.weight(1f), shape = RoundedCornerShape(12.dp)) { Text("Deny") }
                Button(onClick = { busy = true; onDecide(true) }, enabled = !busy, modifier = Modifier.weight(1f).testTag("allow"), shape = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) { Text(if (c.name == "run_command") "Run it" else "Allow") }
            }
        }
    }
}
