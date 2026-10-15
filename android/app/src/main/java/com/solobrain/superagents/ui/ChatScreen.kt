package com.solobrain.superagents.ui

import android.widget.Toast
import android.content.ClipData
import android.content.ClipboardManager
import android.os.Build
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import com.solobrain.superagents.remote.Agent
import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.IntOffset
import kotlin.math.roundToInt
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Labels
import com.solobrain.superagents.remote.LiveTurn
import com.solobrain.superagents.remote.RemoteError
import com.solobrain.superagents.remote.objects
import com.solobrain.superagents.remote.text
import kotlinx.coroutines.CancellationException
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
    var lead by mutableStateOf<String?>(null)  // waiting for this lead's yes, by the team's rules, not yours
}

/** One agent turn in the chat: its steps, what it said along the way, what waits for you, and its answer. */
class Block(val agent: String?, val past: Boolean = false) {
    var turn: String? = null
    val cards = mutableStateMapOf<String, Card>()
    val order = mutableStateListOf<String>()
    val notes = mutableStateListOf<String>()
    val steers = mutableStateListOf<Pair<String, Boolean>>()  // notes typed while it worked, and whether from the phone
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
            "mode" -> MODES.firstOrNull { it.first == e.optString("mode") }?.let { b.notes.add("Switched to ${it.second} mode") }  // while it ran
            "steer" -> b.steers.add(e.optString("text") to (e.optString("via") == "phone"))  // a note typed while it worked
            "tool" -> {
                val id = e.optString("id")
                val c = b.cards[id] ?: Card(id).also { b.cards[id] = it; b.order.add(id) }
                if (e.has("name")) c.name = e.optString("name")
                e.optJSONObject("args")?.let { c.args = it }
                c.status = e.optString("status")
                c.lead = e.optString("lead").ifEmpty { null }
                if (e.has("result") && !e.isNull("result")) c.result = e.optString("result")
                if (!b.past) b.line = when (c.status) { "asking" -> "Waiting for ${c.lead ?: "you"}…"; "running" -> "Working…"; else -> b.line }
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
// The desktop's model picker and effort levels, word for word
private val MODELS = listOf("auto" to ("Auto" to "Super for chats, Ultra for the digest"), "lightning" to ("Lightning" to "Fastest replies"),
    "super" to ("Super" to "Balanced · 120B"), "ultra" to ("Ultra" to "Deepest reasoning · 550B"))
private val EFFORTS = listOf("low" to "Low", "medium" to "Medium", "high" to "High", "max" to "Max")
private val EFFORT_HINT = mapOf("low" to "Quickest; fine for lookups and small edits", "medium" to "Thinks before it acts",
    "high" to "Thinks longer: plans, reviews, tricky bugs", "max" to "Thinks the longest; slowest")

@OptIn(ExperimentalMaterial3Api::class, ExperimentalComposeUiApi::class)
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
    var pickedModel by remember { mutableStateOf<String?>(null) }  // until picked: whatever the desktop is set to
    var pickedEffort by remember { mutableStateOf<String?>(null) }
    var picking by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(open.id != null) }
    var loadError by remember { mutableStateOf<String?>(null) }  // the chat's history didn't come: say so, with Try again
    var follow by remember { mutableStateOf(true) }  // stay with the newest message, unless they scrolled up to read
    val catchUp: (String, Int) -> Unit = { turn, after -> scope.launch { runCatching { r.watch(turn, after) } } }
    BackHandler(onBack = onBack)

    fun send(message: String) {
        val msg = message.trim()
        if (msg.isEmpty()) return
        model.running?.let { turn ->  // typed while it works: a note it reads before its next step; nothing stops
            text = ""
            haptic.performHapticFeedback(HapticFeedbackType.Confirm)
            scope.launch { runCatching { r.steer(turn, msg) }.onFailure { text = msg; Toast.makeText(ctx, it.message, Toast.LENGTH_LONG).show() } }
            return
        }
        text = ""
        follow = true
        haptic.performHapticFeedback(HapticFeedbackType.Confirm)
        model.user(msg)
        val b = model.agent(agent)
        if (model.title == "New chat") model.title = msg.take(60)
        scope.launch {
            runCatching { r.send(model.chatId, agent, mode, pickedModel ?: laptop?.model ?: "auto", pickedEffort ?: laptop?.effort ?: "medium", msg) }
                .onSuccess { (turn, chat) -> model.chatId = chat; model.running = turn; model.bind(turn, b, catchUp) }
                .onFailure { b.failed = it.message; b.line = null }
        }
    }

    suspend fun history(id: String, live: LiveTurn?) {
        loading = true; loadError = null
        runCatching { r.chat(id) }.onSuccess { c ->
            model.title = c.optString("title").ifEmpty { "Chat" }
            c.optString("agent").takeIf { it.isNotEmpty() }?.let { agent = it }
            for (v in c.optJSONArray("view").objects()) {
                model.user(v.optString("user"))
                val b = model.agent(v.optString("agent").ifEmpty { agent }, past = true)
                for (e in v.optJSONArray("events").objects()) model.apply(b, e)
                b.answer = v.text("answer")
                b.line = null
            }
        }.onFailure { if (live == null) loadError = it.message ?: "Couldn't reach your laptop." else model.title = live.message.take(60) }  // live: not saved yet
        loading = false
    }

    LaunchedEffect(Unit) {
        launch { r.events.collect { (turn, evs) -> model.onEvents(turn, evs, catchUp) } }
        val live = open.live
        if (open.id != null) {
            model.chatId = open.id
            history(open.id, live)
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
    LaunchedEffect(model.tick) {  // a busy turn sends many events a second: one scroll after the burst, not one per event
        delay(80)
        if (follow && model.items.isNotEmpty()) list.animateScrollToItem(model.items.size - 1, scrollOffset = 100_000)
    }
    LaunchedEffect(list.isScrollInProgress, list.canScrollForward) {
        if (!list.canScrollForward) follow = true else if (list.isScrollInProgress) follow = false
    }

    val who = laptop?.agent(agent)
    Column(Modifier.fillMaxSize().background(p.bg).imePadding()) {
        Row(Modifier.fillMaxWidth().statusBarsPadding().padding(horizontal = 4.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack, modifier = Modifier.testTag("back")) { Icon(Glyph.Back, "Back") }
            Text(model.title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).padding(end = 16.dp))
        }
        if (list.canScrollBackward) HorizontalDivider(color = p.line) else Spacer(Modifier.height(1.dp))
        Box(Modifier.fillMaxWidth().weight(1f)) {
            when {
                loading -> Column(Modifier.fillMaxWidth().padding(top = 80.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    Mascot(size = 72.dp, mood = Mood.Think); Text("Opening…", color = p.muted)
                }
                loadError != null && model.items.isEmpty() -> Column(Modifier.fillMaxWidth().padding(top = 80.dp, start = 24.dp, end = 24.dp),
                    horizontalAlignment = Alignment.CenterHorizontally) {
                    Mascot(size = 72.dp, mood = Mood.Oops)
                    Text("Couldn't open this chat", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 12.dp))
                    Text(loadError.orEmpty(), color = p.muted, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp))
                    OutlinedButton(onClick = { open.id?.let { id -> scope.launch { history(id, null) } } }, shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.padding(top = 16.dp).testTag("try-again")) { Text("Try again") }
                }
                model.items.isEmpty() -> Welcome(hoodOf(agent, who?.color), onAsk = { send(it) })
                else -> LazyColumn(state = list, contentPadding = PaddingValues(18.dp, 16.dp, 18.dp, 28.dp), verticalArrangement = Arrangement.spacedBy(26.dp)) {
                    itemsIndexed(model.items) { _, item ->
                        when (item) {
                            is Item.User -> UserBubble(item.text)
                            is Item.Agent -> AgentBlock(item.block, laptop?.agent(item.block.agent), model)
                        }
                    }
                }
            }
            if (!follow && model.items.isNotEmpty()) Box(Modifier.align(Alignment.BottomCenter).padding(bottom = 12.dp).size(40.dp)
                .shadow(6.dp, CircleShape).clip(CircleShape).background(p.panel2)
                .clickable { follow = true; scope.launch { list.animateScrollToItem(model.items.size - 1, scrollOffset = 100_000) } },
                contentAlignment = Alignment.Center) { Icon(Glyph.Down, "To the newest message", Modifier.size(20.dp)) }
        }
        val tuning = "${MODELS.toMap()[pickedModel ?: laptop?.model ?: "auto"]?.first ?: "Auto"} · " +
            (EFFORTS.toMap()[pickedEffort ?: laptop?.effort ?: "medium"] ?: "Medium")
        Composer(text, { text = it }, model.running != null, agent, who?.name ?: "Agent S", who?.color, MODES.first { it.first == mode }.second, tuning,
            onPick = { picking = true }, onSend = { send(text) },
            onStop = { model.running?.let { t -> haptic.performHapticFeedback(HapticFeedbackType.Reject)
                scope.launch { runCatching { r.stopTurn(t) }.onFailure { Toast.makeText(ctx, it.message, Toast.LENGTH_LONG).show() } } } })
    }

    if (picking) ModalBottomSheet(onDismissRequest = { picking = false }, containerColor = p.bg2,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {  // four choices: open all the way
        // a sheet is its own window: its tags need turning into resource ids again, for UI tests
        Column(Modifier.fillMaxWidth().semantics { testTagsAsResourceId = true }.verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp).padding(bottom = 28.dp)) {
            Text("Who, and how", style = MaterialTheme.typography.titleLarge)
            Label("Agent")
            for (a in laptop?.agents.orEmpty()) Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp))
                .background(if (a.id == agent) p.panel2 else p.bg2).clickable { agent = a.id; a.mode?.let { m -> if (MODES.any { it.first == m }) mode = m }; pickedModel = a.model ?: "auto" }
                .padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Avatar(a.id, a.name, a.color, 26.dp); Spacer(Modifier.width(12.dp))
                Text(a.name, style = MaterialTheme.typography.titleMedium)
            }
            Label("Mode")
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(top = 6.dp)) {
                MODES.forEachIndexed { i, (k, name) ->
                    SegmentedButton(selected = mode == k, onClick = {
                        if (mode != k) model.running?.let { t -> scope.launch { runCatching { r.setMode(t, k) } } }  // the running answer switches too
                        mode = k
                    }, shape = SegmentedButtonDefaults.itemShape(i, MODES.size), label = { Text(name) })
                }
            }
            Text(MODE_HINT[mode].orEmpty(), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            Label("Model")
            val usingModel = pickedModel ?: laptop?.model ?: "auto"
            for ((k, v) in MODELS) Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(if (k == usingModel) p.panel2 else p.bg2)
                .clickable { pickedModel = k }.padding(horizontal = 14.dp, vertical = 11.dp).testTag("model-$k"), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(v.first, style = MaterialTheme.typography.titleMedium)
                    Text(v.second, style = MaterialTheme.typography.bodySmall)
                }
                if (k == usingModel) Box(Modifier.size(8.dp).background(p.brick, CircleShape))
            }
            Label("Effort")
            val at = EFFORTS.indexOfFirst { it.first == (pickedEffort ?: laptop?.effort ?: "medium") }.coerceAtLeast(0)
            EffortTrack(at) { haptic.performHapticFeedback(HapticFeedbackType.SegmentTick); pickedEffort = EFFORTS[it].first }
            AnimatedContent(at, Modifier.fillMaxWidth(), transitionSpec = {  // the hint goes the way the thumb went: the old one out first
                val way = if (targetState > initialState) 1 else -1
                (slideInHorizontally(tween(220, 70)) { way * it / 5 } + fadeIn(tween(220, 70))) togetherWith
                    (slideOutHorizontally(tween(120)) { -way * it / 5 } + fadeOut(tween(90)))
            }, label = "effort hint") { i ->
                Text(EFFORT_HINT[EFFORTS[i].first].orEmpty(), style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}

/** Effort is a scale, so it's picked like one: the thumb slides along the track to the level you tap. */
@Composable
private fun EffortTrack(at: Int, onPick: (Int) -> Unit) {
    val p = LocalPalette.current
    val slide by animateFloatAsState(at.toFloat(), spring(dampingRatio = 0.7f, stiffness = Spring.StiffnessMediumLow), label = "effort")
    BoxWithConstraints(Modifier.fillMaxWidth().padding(top = 6.dp).height(44.dp).border(1.dp, p.line2, CircleShape).padding(3.dp)) {
        val step = maxWidth / EFFORTS.size
        // the spring overshoots a little: not past either end of the track
        Box(Modifier.offset { IntOffset((step.toPx() * slide.coerceIn(0f, EFFORTS.size - 1f)).roundToInt(), 0) }.width(step).fillMaxHeight().clip(CircleShape)
            .background(p.brick.copy(alpha = 0.14f)).border(1.dp, p.brick.copy(alpha = 0.5f), CircleShape))
        Row(Modifier.fillMaxSize().selectableGroup()) {
            EFFORTS.forEachIndexed { i, (k, name) ->
                val color by animateColorAsState(if (i == at) p.brick else p.muted, label = "effort label")
                Box(Modifier.weight(1f).fillMaxHeight().clip(CircleShape).selectable(i == at, role = Role.RadioButton) { if (i != at) onPick(i) }
                    .testTag("effort-$k"), contentAlignment = Alignment.Center) {
                    Text(name, style = MaterialTheme.typography.labelLarge, color = color)
                }
            }
        }
    }
}

/** A new chat: the mascot says hello, with a few things to ask. */
@Composable
private fun Welcome(hood: Color?, onAsk: (String) -> Unit) {
    val p = LocalPalette.current
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 40.dp),
        horizontalAlignment = Alignment.CenterHorizontally) {
        Mascot(size = 88.dp, mood = Mood.Wave, interactive = true, hood = hood)
        Spacer(Modifier.height(18.dp))
        Text("What should your agents do?", style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
        Spacer(Modifier.height(6.dp))
        Text("They work on your laptop. Each step shows here, and anything that needs your yes.",
            style = MaterialTheme.typography.bodyMedium, color = p.muted, textAlign = TextAlign.Center)
        Spacer(Modifier.height(24.dp))
        for (q in QUICK) Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(16.dp)).background(p.panel)
            .clickable { onAsk(q) }.padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(q, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Icon(Glyph.Right, null, Modifier.size(16.dp), tint = p.faint)
        }
    }
}

@Composable
private fun UserBubble(text: String) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth().padding(start = 48.dp), horizontalArrangement = Arrangement.End) {
        Text(text, style = MaterialTheme.typography.bodyLarge, modifier = Modifier
            .clip(RoundedCornerShape(22.dp, 22.dp, 6.dp, 22.dp)).background(p.bubble).padding(horizontal = 16.dp, vertical = 11.dp))
    }
}

/** Who answers: every agent is a mascot in its own hood colour; Agent S's is the page's ink. */
@Composable
private fun Avatar(agentId: String?, name: String, color: String?, size: Dp) =
    Mascot(size = size, mood = Mood.Idle, fidget = false, hood = hoodOf(agentId, color), label = name)

/** One box for writing: the message, then who answers and how, and send, all inside it, as in Claude's app. */
@Composable
private fun Composer(text: String, onText: (String) -> Unit, running: Boolean, agentId: String, agentName: String, agentColor: String?, modeName: String, tuning: String,
                     onPick: () -> Unit, onSend: () -> Unit, onStop: () -> Unit) {
    val p = LocalPalette.current
    var focused by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(26.dp)
    val stop = running && text.isBlank()  // while it works: Stop, or send the note you typed for it
    val ready = running || text.isNotBlank()
    Box(Modifier.fillMaxWidth().background(p.bg).navigationBarsPadding().padding(start = 12.dp, end = 12.dp, top = 4.dp, bottom = 10.dp)) {
        Column(Modifier.fillMaxWidth().shadow(if (p.bg.luminance() > 0.5f) 10.dp else 0.dp, shape).clip(shape).background(p.panel)
            .border(1.dp, if (focused) p.brick.copy(alpha = 0.55f) else p.line, shape)) {
            BasicTextField(text, onText, Modifier.fillMaxWidth().heightIn(max = 168.dp).padding(start = 18.dp, end = 18.dp, top = 16.dp, bottom = 6.dp)
                .onFocusChanged { focused = it.isFocused }.testTag("input"),
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = p.text), cursorBrush = SolidColor(p.brick),
                decorationBox = { inner ->
                    Box { if (text.isEmpty()) Text(if (running) "Add a note while it works" else "Message your laptop's agents", style = MaterialTheme.typography.bodyLarge, color = p.faint); inner() }
                })
            Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Row(Modifier.clip(RoundedCornerShape(999.dp)).background(p.panel2).clickable(onClick = onPick)
                    .padding(start = 6.dp, end = 10.dp, top = 5.dp, bottom = 5.dp).testTag("pick"), verticalAlignment = Alignment.CenterVertically) {
                    Avatar(agentId, agentName, agentColor, 20.dp); Spacer(Modifier.width(6.dp))
                    Text("$agentName · $modeName", style = MaterialTheme.typography.labelMedium); Spacer(Modifier.width(2.dp))
                    Icon(Glyph.Down, null, Modifier.size(14.dp), tint = p.muted)
                }
                Spacer(Modifier.width(6.dp))
                Row(Modifier.clip(RoundedCornerShape(999.dp)).background(p.panel2).clickable(onClick = onPick)
                    .padding(horizontal = 10.dp, vertical = 7.dp).testTag("tuning"), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Glyph.Gauge, null, Modifier.size(14.dp), tint = p.muted); Spacer(Modifier.width(5.dp))
                    Text(tuning, style = MaterialTheme.typography.labelMedium, maxLines = 1)
                }
                Spacer(Modifier.weight(1f))
                Box(Modifier.size(40.dp).clip(CircleShape).background(if (stop) p.text else if (ready) p.brick else p.panel2)
                    .clickable { if (stop) onStop() else onSend() }.testTag("send"), contentAlignment = Alignment.Center) {
                    Icon(if (stop) Glyph.Stop else Glyph.Up, if (stop) "Stop" else if (running) "Add the note" else "Send", Modifier.size(20.dp),
                        tint = if (stop) p.bg else if (ready) p.onBrick else p.faint)
                }
            }
        }
    }
}

/** One answer: who's answering, the steps folded into a line, anything waiting for a yes, what it's doing now, then
 *  the answer itself as plain text on the page, no box around it. */
@Composable
private fun AgentBlock(b: Block, who: Agent?, model: ChatModel) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val r = ctx.remote
    val scope = rememberCoroutineScope()
    val cards = b.order.mapNotNull { b.cards[it] }
    val folded = cards.filter { !b.waiting(it) }
    val asking = cards.filter { b.waiting(it) && it.status == "asking" }
    val planned = cards.filter { b.waiting(it) && it.status == "planned" }
    val name = who?.name ?: "Agent S"
    val hood = hoodOf(b.agent, who?.color)
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Avatar(b.agent, name, who?.color, 24.dp); Spacer(Modifier.width(8.dp))
            Text(name, style = MaterialTheme.typography.labelLarge, color = p.muted)
        }
        if (folded.isNotEmpty() || b.notes.isNotEmpty()) Steps(b, folded)
        for (c in asking) key(c.id) {
            val decide: suspend (Boolean) -> Unit = { ok -> r.decide(b.turn ?: throw RemoteError("This answer isn't running any more."), c.id, ok) }
            if (c.lead != null) LeadWait(c, decide) else Approval(c, hood, decide)
        }
        for ((note, phone) in b.steers) SteerNote(note, phone)
        b.line?.let { WorkingLine(b, it, hood) }
        b.answer?.let { a ->
            Markdown(a)
            if (model.running == null || model.running != b.turn) AnswerActions(a)  // not while it's still being written
        }
        b.failed?.let {
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(p.bad.copy(alpha = 0.10f)).padding(12.dp)) {
                Mascot(size = 28.dp, mood = Mood.Oops, hood = hood); Spacer(Modifier.width(10.dp))
                Text(it, style = MaterialTheme.typography.bodyMedium, color = p.bad)
            }
        }
        if (b.planned > 0 && !b.planDone && model.running != b.turn) Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp))
            .background(p.plan.copy(alpha = 0.10f)).padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("${b.planned} change${if (b.planned > 1) "s" else ""} planned", style = MaterialTheme.typography.titleMedium)
            Text("Nothing has changed yet. Run the plan to make ${if (b.planned > 1) "them" else "it"}.", style = MaterialTheme.typography.bodySmall)
            for (c in planned) Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(6.dp).background(p.plan, CircleShape)); Spacer(Modifier.width(10.dp))
                Text(Labels.of(c.name, c.args).let { (v, w) -> "$v $w".trim() }, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { b.planDone = true; for (c in planned) c.status = "discarded" }, modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.outlinedButtonColors(contentColor = p.text)) { Text("Discard") }
                Button(onClick = {
                    val turn = b.turn ?: return@Button
                    b.planDone = true; model.running = turn
                    scope.launch {
                        runCatching { r.runPlan(turn) }.onFailure {  // the plan is still there: say why, and Run plan works again
                            b.planDone = false; if (model.running == turn) model.running = null
                            Toast.makeText(ctx, it.message ?: "Couldn't reach your laptop.", Toast.LENGTH_LONG).show()
                        }
                    }
                },
                    modifier = Modifier.weight(1f), shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) { Text("Run plan") }
            }
        }
    }
}

/** A step waiting for a yes: what it is, the command or change itself, and the two answers. A tap answers at once (a
 *  buzz, a spinner on the button) and the card goes when the laptop starts the step; if the answer can't get there,
 *  the card says so and both buttons work again. */
@Composable
private fun Approval(c: Card, hood: Color?, onDecide: suspend (Boolean) -> Unit) {
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    val haptic = LocalHapticFeedback.current
    var sending by remember { mutableStateOf<Boolean?>(null) }  // the answer on its way
    var error by remember { mutableStateOf<String?>(null) }
    fun decide(ok: Boolean) {
        if (sending != null) return
        sending = ok; error = null
        haptic.performHapticFeedback(if (ok) HapticFeedbackType.Confirm else HapticFeedbackType.Reject)
        scope.launch {
            try { onDecide(ok) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { error = e.message ?: "Couldn't reach your laptop."; sending = null }
        }
    }
    val (verb, what) = Labels.of(c.name, c.args)
    val detail = Labels.detail(c.name, c.args).ifEmpty { "$verb $what".trim() }
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(p.panel).border(1.dp, p.warn.copy(alpha = 0.45f), RoundedCornerShape(20.dp))
        .padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Mascot(size = 32.dp, mood = Mood.Ask, hood = hood)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(if (c.name == "run_command") "Wants to run a command" else "Wants to ${verb.lowercase()} this", style = MaterialTheme.typography.titleMedium)
                Text("Nothing happens until you say yes", style = MaterialTheme.typography.bodySmall)
            }
        }
        Text(detail, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text), maxLines = 10, overflow = TextOverflow.Ellipsis,
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.bg2).padding(12.dp))
        error?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = p.bad, modifier = Modifier.testTag("decide-error")) }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { decide(false) }, enabled = sending == null, modifier = Modifier.weight(1f).heightIn(min = 48.dp),
                shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.outlinedButtonColors(contentColor = p.text)) {
                if (sending == false) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = p.text) else Text("Deny")
            }
            Button(onClick = { decide(true) }, enabled = sending == null, modifier = Modifier.weight(1f).heightIn(min = 48.dp).testTag("allow"),
                shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick,
                    disabledContainerColor = p.brick.copy(alpha = if (sending == true) 0.85f else 0.35f), disabledContentColor = p.onBrick)) {
                if (sending == true) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = p.onBrick)
                else Text(if (c.name == "run_command") "Run it" else "Allow")
            }
        }
    }
}

/** A step the team's rules give to a lead: it waits for their yes (at their desk or on their phone); you can cancel it. */
@Composable
private fun LeadWait(c: Card, onDecide: suspend (Boolean) -> Unit) {
    val p = LocalPalette.current
    val scope = rememberCoroutineScope()
    var sending by remember { mutableStateOf(false) }
    val (verb, what) = Labels.of(c.name, c.args)
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(p.panel).border(1.dp, p.line2, RoundedCornerShape(20.dp))
        .padding(16.dp).testTag("lead-wait"), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Waiting for ${c.lead}'s yes", style = MaterialTheme.typography.titleMedium)
        Text("$verb $what".trim(), style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text), maxLines = 4, overflow = TextOverflow.Ellipsis)
        Text("Your team's rules give this step to a lead. It goes ahead when they say yes.", style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = { sending = true; scope.launch { runCatching { onDecide(false) }; sending = false } }, enabled = !sending,
            shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.outlinedButtonColors(contentColor = p.text)) { Text("Cancel the step") }
    }
}

/** A note typed while it worked, quoted with where it came from. */
@Composable
private fun SteerNote(note: String, phone: Boolean) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Box(Modifier.width(2.dp).fillMaxHeight().background(p.line2))
        Spacer(Modifier.width(10.dp))
        Text(buildAnnotatedString {
            withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = p.text)) { append(if (phone) "You  " else "You, at the laptop  ") }
            append(note)
        }, style = MaterialTheme.typography.bodyMedium, color = p.muted)
    }
}

/** Under a finished answer: copy it. */
@Composable
private fun AnswerActions(answer: String) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    Box(Modifier.size(34.dp).clip(CircleShape).clickable {
        ctx.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("answer", answer))
        if (Build.VERSION.SDK_INT < 33) Toast.makeText(ctx, "Copied", Toast.LENGTH_SHORT).show()  // Android 13+ says so itself
    }, contentAlignment = Alignment.Center) { Icon(Glyph.Copy, "Copy the answer", Modifier.size(18.dp), tint = p.faint) }
}

@Composable
private fun shimmer(base: Color, glow: Color): Brush {
    val x by rememberInfiniteTransition(label = "shimmer").animateFloat(-240f, 960f, infiniteRepeatable(tween(1700, easing = LinearEasing)), label = "x")
    return Brush.linearGradient(listOf(base, glow, base), start = Offset(x, 0f), end = Offset(x + 240f, 0f))
}

/** What the agent is doing now: the mascot acts out the step, and the line names it with a shimmer, like Claude's
 *  "thinking". A quick step (reading a file takes milliseconds) stays up a moment, long enough to be seen. */
@Composable
private fun WorkingLine(b: Block, line: String, hood: Color?) {
    val p = LocalPalette.current
    val latest = b.order.lastOrNull()?.let { b.cards[it] }
    var shown by remember(b) { mutableStateOf<Card?>(null) }
    LaunchedEffect(latest?.id, latest?.status) {
        if (latest != null && (latest.status == "running" || latest.status == "asking")) shown = latest
        else if (shown != null) { delay(1600); shown = null }
    }
    val step = shown
    val acting = step != null && step.status != "asking"
    Row(verticalAlignment = Alignment.CenterVertically) {
        Mascot(size = 32.dp, mood = when { step == null -> Mood.Think; step.status == "asking" -> Mood.Ask; else -> moodFor(step.name) }, hood = hood)
        Spacer(Modifier.width(10.dp))
        val style = if (acting) MaterialTheme.typography.bodySmall.copy(fontFamily = Mono) else MaterialTheme.typography.bodyMedium
        Text(if (acting) Labels.of(step!!.name, step.args).let { (v, w) -> "$v $w".trim() } else line, maxLines = 1, overflow = TextOverflow.Ellipsis,
            style = style.copy(brush = shimmer(p.faint, p.text)))
    }
}

/** The turn's steps, folded into one quiet line like Claude Code's; open, a timeline of what ran, each with its result. */
@Composable
private fun Steps(b: Block, folded: List<Card>) {
    val p = LocalPalette.current
    var openSteps by remember { mutableStateOf(false) }
    val turn by animateFloatAsState(if (openSteps) 90f else 0f, label = "caret")
    val skipped = folded.count { it.status in setOf("asking", "planned", "discarded", "declined") }
    val ran = folded.filter { it.status !in setOf("asking", "planned", "discarded", "declined") }
    val failed = ran.count { it.status == "failed" }
    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.clip(RoundedCornerShape(10.dp)).clickable { openSteps = !openSteps }.padding(vertical = 6.dp, horizontal = 2.dp).testTag("steps"),
            verticalAlignment = Alignment.CenterVertically) {
            Text(if (ran.isEmpty() && skipped == 0) "Notes along the way" else Labels.summary(ran.map { it.name }),
                style = MaterialTheme.typography.bodyMedium, color = p.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
            if (failed > 0) Text("  · $failed failed", style = MaterialTheme.typography.bodyMedium, color = p.bad)
            if (skipped > 0) Text("  · $skipped not run", style = MaterialTheme.typography.bodyMedium, color = p.faint)
            Spacer(Modifier.width(6.dp))
            Icon(Glyph.Right, if (openSteps) "Hide the steps" else "Show the steps", Modifier.size(14.dp).rotate(turn), tint = p.faint)
        }
        AnimatedVisibility(openSteps, enter = expandVertically() + fadeIn(), exit = shrinkVertically() + fadeOut()) {
            Column(Modifier.fillMaxWidth().padding(start = 2.dp, top = 6.dp)) {
                for (n in b.notes) Text(n, style = MaterialTheme.typography.bodyMedium, color = p.muted, modifier = Modifier.padding(start = 26.dp, bottom = 8.dp))
                folded.forEachIndexed { i, c -> StepRow(c, last = i == folded.lastIndex) }
            }
        }
    }
}

/** One step on the timeline: a dot for how it went, what it did, and its output on a tap. */
@Composable
private fun StepRow(c: Card, last: Boolean) {
    val p = LocalPalette.current
    var showOut by remember { mutableStateOf(false) }
    val (verb, what) = Labels.of(c.name, c.args)
    val color = when (c.status) { "done" -> p.ok; "failed" -> p.bad; "running" -> p.brick; else -> p.faint }
    val said = when (c.status) { "failed" -> "failed"; "running" -> "running"; "declined", "discarded", "planned", "asking" -> "not run"; else -> "" }
    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
        Column(Modifier.width(18.dp).fillMaxHeight(), horizontalAlignment = Alignment.CenterHorizontally) {
            Spacer(Modifier.height(10.dp))
            Box(Modifier.size(8.dp).background(color, CircleShape))
            if (!last) Box(Modifier.padding(top = 4.dp).width(1.5.dp).weight(1f).background(p.line2))
        }
        Column(Modifier.weight(1f).padding(start = 8.dp, bottom = if (last) 0.dp else 6.dp)) {
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable(enabled = c.result != null) { showOut = !showOut }.padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text(verb, style = MaterialTheme.typography.labelLarge)
                Spacer(Modifier.width(8.dp))
                Text(what, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono), maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                if (said.isNotEmpty()) Text(said, style = MaterialTheme.typography.labelSmall, color = color)
            }
            if (showOut) c.result?.let {
                Text(it, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text), maxLines = 30, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp).clip(RoundedCornerShape(10.dp)).background(p.bg2).padding(10.dp))
            }
        }
    }
}
