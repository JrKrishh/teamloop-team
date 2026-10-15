package com.solobrain.superagents.ui

import android.widget.Toast
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Labels
import com.solobrain.superagents.remote.Laptop
import com.solobrain.superagents.remote.Link
import com.solobrain.superagents.remote.LiveTurn
import com.solobrain.superagents.remote.TeamAsk
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch
import kotlin.math.abs
import kotlin.math.roundToInt

/** Every question a running turn waits on, from the phone or the desk, answered with a swipe; then what's working. */
@Composable
fun NeedsYou(laptop: Laptop?, link: Link, onChat: (ChatOpen) -> Unit) {
    val p = LocalPalette.current
    val live = laptop?.live.orEmpty()
    val asks = live.filter { it.ask != null }
    val working = live.filter { it.ask == null }
    if (laptop == null) return Waiting(link)
    LazyColumn(contentPadding = PaddingValues(16.dp, 8.dp, 16.dp, 24.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items(laptop.asks, key = { it.id }) { a -> TeamAskCard(a) }
        items(asks, key = { it.ask!!.id }) { t -> AskCard(t, laptop.agent(t.agent).name, laptop.agent(t.agent).color, onOpen = { onChat(ChatOpen(t.chat, t)) }) }
        if (working.isNotEmpty()) item { Label("Working now") }
        items(working, key = { it.turn }) { t ->
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(p.panel).border(1.dp, p.line, RoundedCornerShape(16.dp))
                .clickable { onChat(ChatOpen(t.chat, t)) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Mascot(size = 36.dp, mood = moodFor(t.now?.name), hood = hoodOf(t.agent, laptop.agent(t.agent).color))  // acts out the step it's on
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(laptop.agent(t.agent).name, style = MaterialTheme.typography.titleMedium)
                    Text(t.now?.let { Labels.line(it) } ?: "Thinking…", style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(t.message, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
        }
        if (live.isEmpty() && laptop.asks.isEmpty()) item {
            Column(Modifier.fillMaxWidth().padding(top = 56.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Mascot(size = 96.dp, mood = if (link == Link.Online) Mood.Idle else Mood.Sleep, interactive = true)
                Spacer(Modifier.height(18.dp))
                Text("Nothing needs you", style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(6.dp))
                Text("Your agents ask here before they run a command or change something. Swipe right to say yes, left to say no.",
                    style = MaterialTheme.typography.bodyMedium, color = p.muted, textAlign = TextAlign.Center, modifier = Modifier.padding(horizontal = 24.dp))
            }
        }
    }
}

@Composable
fun Waiting(link: Link) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    Column(Modifier.fillMaxWidth().padding(top = 80.dp, start = 24.dp, end = 24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Mascot(size = 96.dp, mood = if (link == Link.Offline) Mood.Sleep else Mood.Think)
        Spacer(Modifier.height(18.dp))
        Text(if (link == Link.Offline) "Your laptop isn't answering" else "Finding your laptop…", style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(6.dp))
        Text("Super Agents has to be open on it, with Settings → Phone on.", style = MaterialTheme.typography.bodyMedium, color = p.muted,
            textAlign = TextAlign.Center)
        if (link == Link.Offline) OutlinedButton(onClick = { ctx.remote.tryNow() }, modifier = Modifier.padding(top = 18.dp).testTag("try-again"),
            shape = RoundedCornerShape(14.dp)) { Text("Try again") }
    }
}

@Composable
fun Label(text: String) = Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = LocalPalette.current.faint,
    modifier = Modifier.padding(top = 10.dp, start = 2.dp))

/** A lead's: a step of a member's agent that the team's rules give to a lead. It goes ahead on Allow. */
@Composable
private fun TeamAskCard(a: TeamAsk) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val haptic = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()
    var sending by remember(a.id) { mutableStateOf<Boolean?>(null) }  // the answer on its way (the card goes once it's there)
    var error by remember(a.id) { mutableStateOf<String?>(null) }
    fun decide(ok: Boolean) {
        if (sending != null) return
        sending = ok; error = null
        haptic.performHapticFeedback(if (ok) HapticFeedbackType.Confirm else HapticFeedbackType.Reject)
        scope.launch {
            try { ctx.remote.decideTeam(a.id, ok) }
            catch (e: CancellationException) { throw e }
            catch (e: Exception) { error = e.message ?: "Couldn't reach your laptop."; sending = null }
        }
    }
    val shape = RoundedCornerShape(20.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(p.panel).border(1.dp, p.warn.copy(alpha = 0.6f), shape).padding(16.dp).testTag("team-ask")) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${a.from}'s agent", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.weight(1f))
            Text("needs your yes", style = MaterialTheme.typography.bodySmall)
            Spacer(Modifier.width(6.dp))
            Mascot(size = 28.dp, mood = Mood.Ask)
        }
        Spacer(Modifier.height(8.dp))
        Text(a.what, style = MaterialTheme.typography.titleLarge, maxLines = 3, overflow = TextOverflow.Ellipsis)
        if (a.detail.isNotEmpty()) {
            Spacer(Modifier.height(10.dp))
            Text(a.detail, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text), maxLines = 8, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.bg2).border(1.dp, p.line, RoundedCornerShape(12.dp)).padding(12.dp))
        }
        Spacer(Modifier.height(10.dp))
        Text("Your team's rules give this step to a lead.", style = MaterialTheme.typography.bodySmall)
        error?.let { Spacer(Modifier.height(6.dp)); Text(it, style = MaterialTheme.typography.bodySmall, color = p.bad) }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            OutlinedButton(onClick = { decide(false) }, enabled = sending == null, modifier = Modifier.weight(1f).heightIn(min = 48.dp), shape = RoundedCornerShape(14.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = p.text)) {
                if (sending == false) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = p.text) else Text("Deny")
            }
            Button(onClick = { decide(true) }, enabled = sending == null, modifier = Modifier.weight(1f).heightIn(min = 48.dp).testTag("team-allow"),
                shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick,
                    disabledContainerColor = p.brick.copy(alpha = if (sending == true) 0.85f else 0.35f), disabledContentColor = p.onBrick)) {
                if (sending == true) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = p.onBrick) else Text("Allow")
            }
        }
    }
}

@Composable
private fun AskCard(t: LiveTurn, agent: String, color: String?, onOpen: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val haptic = LocalHapticFeedback.current
    val scope = rememberCoroutineScope()
    val ask = t.ask ?: return
    val (verb, what) = Labels.of(ask.name, ask.args)
    val detail = Labels.detail(ask.name, ask.args)
    val offset = remember { Animatable(0f) }
    var busy by remember { mutableStateOf(false) }
    var leaning by remember { mutableStateOf(0) }
    val width = with(LocalDensity.current) { LocalConfiguration.current.screenWidthDp.dp.toPx() }
    val threshold = width * 0.28f
    fun decide(ok: Boolean) {
        if (busy) return
        busy = true
        haptic.performHapticFeedback(if (ok) HapticFeedbackType.Confirm else HapticFeedbackType.Reject)
        scope.launch {
            offset.animateTo(if (ok) width else -width, tween(220))
            runCatching { ctx.remote.decide(t.turn, ask.id, ok) }.onFailure {
                Toast.makeText(ctx, it.message, Toast.LENGTH_LONG).show()
                offset.animateTo(0f, spring()); busy = false
            }
        }
    }
    val shape = RoundedCornerShape(20.dp)
    Box(Modifier.fillMaxWidth().testTag("ask-card")) {
        val yes = offset.value >= 0
        Row(Modifier.matchParentSize().clip(shape).background(if (yes) p.ok.copy(alpha = 0.22f) else p.bad.copy(alpha = 0.22f)).padding(horizontal = 24.dp),
            horizontalArrangement = if (yes) Arrangement.Start else Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
            Text(if (yes) (if (ask.name == "run_command") "Run it" else "Approve") else "Deny", style = MaterialTheme.typography.titleMedium,
                color = if (yes) p.ok else p.bad)
        }
        Column(Modifier.offset { IntOffset(offset.value.roundToInt(), 0) }
            .pointerInput(ask.id) {
                detectHorizontalDragGestures(
                    onDragEnd = { if (abs(offset.value) > threshold) decide(offset.value > 0) else scope.launch { offset.animateTo(0f, spring(dampingRatio = 0.6f)) } },
                    onDragCancel = { scope.launch { offset.animateTo(0f, spring()) } },
                ) { change, drag ->
                    if (busy) return@detectHorizontalDragGestures
                    change.consume()
                    val next = offset.value + drag
                    val lean = if (next > threshold) 1 else if (next < -threshold) -1 else 0
                    if (lean != 0 && lean != leaning) haptic.performHapticFeedback(HapticFeedbackType.GestureThresholdActivate)
                    leaning = lean
                    scope.launch { offset.snapTo(next) }
                }
            }
            .clip(shape).background(p.panel).border(1.dp, p.warn.copy(alpha = 0.6f), shape).padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(10.dp).background(color?.let { runCatching { Color(android.graphics.Color.parseColor(it)) }.getOrNull() } ?: p.brick, CircleShape))
                Spacer(Modifier.width(8.dp))
                Text(agent, style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.weight(1f))
                Text("is waiting for you", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.width(6.dp))
                Mascot(size = 28.dp, mood = Mood.Ask, hood = hoodOf(t.agent, color))  // hops in as the question arrives, eyes on you
            }
            Spacer(Modifier.height(8.dp))
            Text("$verb $what".trim(), style = MaterialTheme.typography.titleLarge, maxLines = 3, overflow = TextOverflow.Ellipsis)
            if (detail.isNotEmpty()) {
                Spacer(Modifier.height(10.dp))
                Text(detail, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text),
                    maxLines = 8, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.bg2).border(1.dp, p.line, RoundedCornerShape(12.dp)).padding(12.dp))
            }
            Spacer(Modifier.height(10.dp))
            Text("For: ${t.message}", style = MaterialTheme.typography.bodySmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { decide(false) }, enabled = !busy, modifier = Modifier.weight(1f).heightIn(min = 48.dp), shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.outlinedButtonColors(contentColor = LocalPalette.current.text)) { Text("Deny") }
                Button(onClick = { decide(true) }, enabled = !busy, modifier = Modifier.weight(1f).heightIn(min = 48.dp).testTag("approve"), shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) {
                    if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = p.onBrick)
                    else Text(if (ask.name == "run_command") "Run it" else "Allow")
                }
            }
            Text("Open the chat", color = p.brick, style = MaterialTheme.typography.labelMedium,
                modifier = Modifier.padding(top = 10.dp).clickable(onClick = onOpen))
        }
    }
}
