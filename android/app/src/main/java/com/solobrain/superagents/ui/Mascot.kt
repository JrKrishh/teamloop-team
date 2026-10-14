package com.solobrain.superagents.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

/** What the mascot is up to. It breathes, blinks and, left idle, fidgets; a tap makes it giggle. While an agent works it
 *  acts out the step: reading, running a command, writing, searching. It asks (hops in, eyes on you), thinks, sleeps when
 *  the laptop is away, celebrates a pairing and droops when something failed. */
enum class Mood { Idle, Wave, Think, Ask, Read, Run, Write, Search, Oops, Sleep, Celebrate }

/** The action that matches what an agent's step does. */
fun moodFor(tool: String?): Mood = when {
    tool == null -> Mood.Think
    tool in READS -> Mood.Read
    tool in WRITES -> Mood.Write
    tool == "run_command" || tool == "open_pr" || tool == "dev_server" || tool.startsWith("git_") || tool.startsWith("desktop_") -> Mood.Run
    tool == "search_files" || tool.startsWith("browser_") -> Mood.Search
    else -> Mood.Think
}

private val READS = setOf("read_file", "list_files", "fetch_url", "team_board", "team_ask", "team_sessions", "recall")
private val WRITES = setOf("write_file", "edit_file", "create_task", "assign_task", "close_task", "set_deadline", "share_files", "remember")

// brand/mark.svg, on its 100 × 100 canvas
private const val HOOD = "M50 95C30 95 14 93 11 86C8.5 80 9 68 9.5 56C11 31 27 14 48 12.5C56 12 63 9.5 70 3.5C71.2 9.5 69.8 14.5 66.5 17.8" +
    "C81 25 90 39 90.5 56C91 68 91.5 80 89 86C86 93 70 95 50 95Z"

/**
 * The Super Agents mascot, drawn from its own vector paths (sharp at any size) and alive: [drop] brings it in from
 * above on a spring, with a squash as it lands, then [onLanded]. [interactive] lets a tap make it giggle.
 */
@Composable
fun Mascot(modifier: Modifier = Modifier, mood: Mood = Mood.Idle, size: Dp = 96.dp, drop: Boolean = false, interactive: Boolean = false,
           onLanded: () -> Unit = {}) {
    val p = LocalPalette.current
    val rim = p.bg.luminance() < 0.5f  // on a dark page the black hood needs an edge to be seen
    val hood = remember { PathParser().parsePathString(HOOD).toPath() }
    val loop = rememberInfiniteTransition(label = "mascot")
    val breath by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2400, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "breath")
    val dart by loop.animateFloat(0f, 1f, infiniteRepeatable(keyframes {
        durationMillis = 2200; 0f at 0; -1f at 300; -1f at 800; 1f at 1100; 1f at 1700; 0f at 2000
    }), label = "dart")
    val wave by loop.animateFloat(-1f, 1f, infiniteRepeatable(tween(520, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "wave")
    val zz by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2600, easing = LinearEasing)), label = "zz")
    val scan by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(1500, easing = LinearEasing)), label = "scan")  // along a line of text
    val tap by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(130), RepeatMode.Reverse), label = "tap")  // typing
    val pulse by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(650, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "pulse")

    val dropY = remember { Animatable(if (drop) -150f else 0f) }
    val hop = remember { Animatable(0f) }
    val squash = remember { Animatable(1f) }
    val blink = remember { Animatable(1f) }
    val joy = remember { Animatable(0f) }
    val glance = remember { Animatable(0f) }  // eyes off to one side, looking around
    val lean = remember { Animatable(0f) }  // a tilt: a wiggle, a droop
    val giggle = remember { Animatable(0f) }  // happy eyes after a tap
    val scope = rememberCoroutineScope()
    val haptic = LocalHapticFeedback.current

    suspend fun bounce(height: Float) {
        hop.animateTo(-height, tween(170, easing = FastOutSlowInEasing))
        scope.launch { squash.snapTo(0.86f); squash.animateTo(1f, spring(dampingRatio = 0.35f, stiffness = 500f)) }
        hop.animateTo(0f, spring(dampingRatio = 0.5f, stiffness = Spring.StiffnessMediumLow))
    }

    LaunchedEffect(drop) {
        if (!drop) return@LaunchedEffect
        dropY.animateTo(0f, spring(dampingRatio = 0.42f, stiffness = 260f))
        onLanded()
    }
    LaunchedEffect(drop) {  // the landing squash, a little after the drop begins
        if (!drop) return@LaunchedEffect
        delay(330)
        squash.snapTo(0.84f)
        squash.animateTo(1f, spring(dampingRatio = 0.35f, stiffness = 420f))
    }
    LaunchedEffect(Unit) {  // blinks at its own pace, sometimes twice
        while (true) {
            delay(Random.nextLong(2200, 4800))
            repeat(if (Random.nextInt(4) == 0) 2 else 1) {
                blink.animateTo(0.08f, tween(70)); blink.animateTo(1f, tween(110)); delay(90)
            }
        }
    }
    LaunchedEffect(mood) {
        glance.snapTo(0f); lean.snapTo(0f)
        when (mood) {
            Mood.Ask -> repeat(2) { bounce(15f); delay(120) }
            Mood.Celebrate -> repeat(3) { bounce(15f); delay(120) }
            Mood.Oops -> {
                launch { squash.snapTo(0.9f); squash.animateTo(1f, spring(dampingRatio = 0.4f, stiffness = 300f)) }
                lean.animateTo(-8f, spring(dampingRatio = 0.5f, stiffness = 200f))
            }
            Mood.Idle -> while (true) {  // left alone, it fidgets now and then
                delay(Random.nextLong(4500, 8500))
                when (Random.nextInt(3)) {
                    0 -> { glance.animateTo(-3.5f, tween(240)); delay(450); glance.animateTo(3.5f, tween(360)); delay(450); glance.animateTo(0f, tween(240)) }
                    1 -> bounce(8f)
                    else -> { repeat(2) { lean.animateTo(6f, tween(160)); lean.animateTo(-6f, tween(220)) }; lean.animateTo(0f, tween(160)) }
                }
            }
            else -> Unit
        }
        if (mood == Mood.Celebrate) { joy.snapTo(0f); joy.animateTo(1f, tween(900)) } else joy.snapTo(0f)
    }
    val poke = if (!interactive) Modifier else Modifier.pointerInput(Unit) {
        detectTapGestures {
            haptic.performHapticFeedback(HapticFeedbackType.ContextClick)
            scope.launch { giggle.snapTo(1f); bounce(12f); delay(450); giggle.snapTo(0f) }
        }
    }

    Canvas(modifier.size(size).then(poke).semantics { contentDescription = "Super Agents mascot" }) {
        val k = this.size.minDimension / 100f
        scale(k, pivot = Offset.Zero) {
            val sleeping = mood == Mood.Sleep
            val typing = if (mood == Mood.Run) (tap - 0.5f) * 1.8f else 0f
            val bob = if (sleeping) 0f else (breath - 0.5f) * 3f + typing
            val breathe = if (sleeping) 1f + breath * 0.03f else 1f
            val tilt = when (mood) { Mood.Wave -> wave * 7f; Mood.Write -> wave * 3f; else -> lean.value }
            val lookX = when (mood) { Mood.Think -> dart * 3f; Mood.Read -> scan * 6f - 3f; Mood.Write -> 2.5f; Mood.Search -> dart * 3.5f; else -> glance.value }
            val lookY = when (mood) { Mood.Read, Mood.Run, Mood.Write -> 3f; Mood.Search -> wave * 1.5f; Mood.Ask -> -2f; else -> 0f }
            translate(0f, dropY.value + hop.value + bob) {
                rotate(tilt, pivot = Offset(50f, 92f)) {
                    scale(scaleX = (2f - squash.value) * breathe, scaleY = squash.value * breathe, pivot = Offset(50f, 95f)) {
                        drawPath(hood, p.ink)
                        if (rim) drawPath(hood, p.face.copy(alpha = 0.3f), style = Stroke(width = 2.4f))
                        drawOval(p.face, topLeft = Offset(20f, 34f), size = Size(60f, 54f))
                        eyes(p.ink, if (giggle.value > 0.5f) Mood.Celebrate else mood, blink.value, lookX, lookY)
                    }
                }
                badge(mood, p, pulse)
            }
            if (sleeping) snores(p.muted, zz)
            if (mood == Mood.Celebrate && joy.value in 0.01f..0.99f) confetti(listOf(p.brick, p.warn, p.ok, p.plan), joy.value)
        }
    }
}

private fun DrawScope.eyes(ink: Color, mood: Mood, blink: Float, lookX: Float, lookY: Float) {
    when (mood) {
        Mood.Sleep -> for (x in listOf(38.5f, 61.5f)) {  // closed: two gentle arcs
            val arc = Path().apply { moveTo(x - 6f, 62f); quadraticTo(x, 67f, x + 6f, 62f) }
            drawPath(arc, ink, style = Stroke(width = 2.6f, cap = StrokeCap.Round))
        }
        Mood.Celebrate -> for (x in listOf(38.5f, 61.5f)) {  // happy: ^ ^
            val arc = Path().apply { moveTo(x - 6f, 64f); quadraticTo(x, 55f, x + 6f, 64f) }
            drawPath(arc, ink, style = Stroke(width = 2.8f, cap = StrokeCap.Round))
        }
        Mood.Oops -> for ((x, inner) in listOf(38.5f to 1f, 61.5f to -1f)) {  // worried: half closed, brows up in the middle
            val ry = 5f * blink
            drawOval(ink, topLeft = Offset(x - 5.6f, 64f - ry), size = Size(11.2f, ry * 2))
            drawLine(ink, Offset(x - 6f * inner, 52.5f), Offset(x + 5f * inner, 49.5f), strokeWidth = 2.2f, cap = StrokeCap.Round)
        }
        else -> {
            val wide = when (mood) { Mood.Ask -> 1.12f; Mood.Search -> 1.15f; else -> 1f }
            for (x in listOf(38.5f, 61.5f)) {
                val ry = 7.8f * wide * blink
                drawOval(ink, topLeft = Offset(x + lookX - 6.2f, 62f + lookY - ry), size = Size(12.4f, ry * 2))
                if (blink > 0.5f) drawCircle(Color.White, radius = 2.1f, center = Offset(x + lookX + 2.4f, 58.6f + lookY))
            }
        }
    }
}

/** A small sign of the action at the bottom right: lines of a page, a prompt, a pencil, a lens, a question, a "!". */
private fun DrawScope.badge(mood: Mood, p: Palette, pulse: Float) {
    val fill = when (mood) { Mood.Read, Mood.Run, Mood.Write, Mood.Search -> p.brick; Mood.Ask -> p.warn; Mood.Oops -> p.bad; else -> return }
    val c = Offset(80f, 82f)
    val r = if (mood == Mood.Ask) 16f + pulse * 1.4f else 16f
    drawCircle(fill, r, c)
    drawCircle(p.ink, r, c, style = Stroke(width = 2f))
    val ink = p.onBrick
    fun line(x1: Float, y1: Float, x2: Float, y2: Float, color: Color = ink, width: Float = 3f) =
        drawLine(color, Offset(c.x + x1, c.y + y1), Offset(c.x + x2, c.y + y2), strokeWidth = width, cap = StrokeCap.Round)
    when (mood) {
        Mood.Read -> { line(-7f, -5f, 7f, -5f); line(-7f, 0f, 7f, 0f); line(-7f, 5f, 3f, 5f) }
        Mood.Run -> { line(-7f, -5f, -2f, 0f); line(-2f, 0f, -7f, 5f); line(1f, 5f, 7f, 5f, ink.copy(alpha = if (pulse > 0.5f) 1f else 0.25f)) }
        Mood.Write -> { line(-4.5f, 4.5f, 4.5f, -4.5f, width = 4.2f); line(-4.5f, 4.5f, -7f, 7f, width = 2f) }
        Mood.Search -> { drawCircle(ink, 4.6f, Offset(c.x - 1.5f, c.y - 1.5f), style = Stroke(width = 3f)); line(2f, 2f, 6.5f, 6.5f) }
        Mood.Ask -> {
            val q = Path().apply {
                moveTo(c.x - 4.5f, c.y - 4f); quadraticTo(c.x - 4.5f, c.y - 9f, c.x, c.y - 9f); quadraticTo(c.x + 4.5f, c.y - 9f, c.x + 4.5f, c.y - 4.5f)
                quadraticTo(c.x + 4.5f, c.y - 1.5f, c.x, c.y + 0.5f); lineTo(c.x, c.y + 2.5f)
            }
            drawPath(q, ink, style = Stroke(width = 3f, cap = StrokeCap.Round, join = StrokeJoin.Round))
            drawCircle(ink, 1.7f, Offset(c.x, c.y + 6.8f))
        }
        Mood.Oops -> { line(0f, -7f, 0f, 1.5f); drawCircle(ink, 1.7f, Offset(c.x, c.y + 6.5f)) }
        else -> Unit
    }
}

private fun DrawScope.snores(color: Color, t: Float) {
    for (i in 0..1) {
        val f = (t + i * 0.5f) % 1f
        val s = 4f + f * 4f
        val x = 74f + f * 10f
        val y = 30f - f * 22f
        val z = Path().apply { moveTo(x, y); lineTo(x + s, y); lineTo(x, y + s); lineTo(x + s, y + s) }
        drawPath(z, color.copy(alpha = (1f - f) * 0.9f), style = Stroke(width = 1.6f, cap = StrokeCap.Round))
    }
}

private fun DrawScope.confetti(colors: List<Color>, t: Float) {
    for (i in 0 until 10) {
        val a = i * 36f * (Math.PI / 180f).toFloat()
        val r = 28f + t * 34f
        drawCircle(colors[i % colors.size].copy(alpha = 1f - t), radius = 2.4f, center = Offset(50f + cos(a) * r, 58f + sin(a) * r * 0.8f))
    }
}
