package com.solobrain.superagents.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.LinearOutSlowInEasing
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.keyframes
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.withInfiniteAnimationFrameNanos
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
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
import kotlin.math.exp
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
private val WRITES = setOf("write_file", "create_task", "assign_task", "close_task", "set_deadline", "share_files", "remember")

// brand/mark.svg, on its 100 × 100 canvas
private const val HOOD = "M50 95C30 95 14 93 11 86C8.5 80 9 68 9.5 56C11 31 27 14 48 12.5C56 12 63 9.5 70 3.5C71.2 9.5 69.8 14.5 66.5 17.8" +
    "C81 25 90 39 90.5 56C91 68 91.5 80 89 86C86 93 70 95 50 95Z"

private const val TAU = 6.2831855f

/** An agent's hood: its own colour. Agent S wears the page's ink. */
fun hoodOf(agentId: String?, color: String?): Color? = if (agentId == null || agentId == "agent-s") null else parseColor(color)

/** Follows where it should be on a critically damped spring, solved exactly (steady at any frame rate): the eyes
 *  quickly, so a glance is a dart, and the head a beat later. */
private class Follow(private val w: Float) {
    var now by mutableFloatStateOf(0f)
        private set
    private var v = 0f
    fun step(to: Float, dt: Float) {
        val c1 = now - to; val c2 = v + w * c1; val e = exp(-w * dt)
        now = to + (c1 + c2 * dt) * e
        v = (c2 - w * (c1 + c2 * dt)) * e
    }
}

/** Where the eyes look, in canvas units off centre, for what it's doing. */
private fun aim(mood: Mood, glance: Float, dart: Float, line: Float, sway: Float): Offset = when (mood) {
    Mood.Think -> Offset(dart * 3.2f, -2.4f)  // up and off to one side, then the other
    Mood.Read -> Offset(line, 2.6f)  // along a line of text, then back to the start of the next
    Mood.Write -> Offset(2.5f, 3f)
    Mood.Run -> Offset(0f, 3f)
    Mood.Search -> Offset(dart * 3.6f, sin(sway * TAU) * 1.5f)
    Mood.Ask -> Offset(0f, -2f)  // eyes on you
    Mood.Oops -> Offset(0f, 1.8f)
    else -> Offset(glance, 0f)
}

/**
 * The Super Agents mascot, drawn from its own vector paths (sharp at any size) and alive. It breathes from its base;
 * blinks close fast and open slower; its eyes dart and its head turns after them; a mood change eases over instead of
 * jumping. [drop] brings it in from above, falling faster and faster, landing squashed with a little rebound, then
 * [onLanded]. [interactive] lets a tap make it giggle; [fidget] off keeps it calm when idle. [hood] is an agent's own
 * colour (see [hoodOf]); [label] is what a screen reader says.
 */
@Composable
fun Mascot(modifier: Modifier = Modifier, mood: Mood = Mood.Idle, size: Dp = 96.dp, drop: Boolean = false, interactive: Boolean = false, fidget: Boolean = true,
           hood: Color? = null, label: String = "Super Agents mascot", onLanded: () -> Unit = {}) {
    val p = LocalPalette.current
    val rim = hood == null && p.bg.luminance() < 0.5f  // on a dark page the black hood needs an edge to be seen
    val shape = remember { PathParser().parsePathString(HOOD).toPath() }
    val loop = rememberInfiniteTransition(label = "mascot")
    // cycles run as phases (0 to 1, steadily) and are drawn as sine waves, so there's no hitch where one meets the next
    val breath by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(4400, easing = LinearEasing)), label = "breath")
    val sway by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(1100, easing = LinearEasing)), label = "sway")
    val tap by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(300, easing = LinearEasing)), label = "tap")  // typing
    val pulse by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(1300, easing = LinearEasing)), label = "pulse")
    val zz by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2600, easing = LinearEasing)), label = "zz")
    // where the eyes hold while it thinks, or reads a line; they jump between holds, and the springs make each jump a dart
    val dart by loop.animateFloat(0f, 0f, infiniteRepeatable(keyframes {
        durationMillis = 2400; 0f at 380; -1f at 400; -1f at 1100; 1f at 1120; 1f at 1900; 0f at 1920
    }), label = "dart")
    val line by loop.animateFloat(-3f, -3f, infiniteRepeatable(keyframes {
        durationMillis = 1900; -3f at 300; -1f at 320; -1f at 640; 1f at 660; 1f at 980; 3f at 1000; 3f at 1500; -3f at 1520
    }), label = "line")

    val dropY = remember { Animatable(if (drop) -150f else 0f) }
    val hop = remember { Animatable(0f) }
    val squash = remember { Animatable(1f) }  // under 1 squashed (wider), over 1 stretched (taller)
    val blink = remember { Animatable(1f) }
    val joy = remember { Animatable(0f) }
    val lean = remember { Animatable(0f) }  // a tilt: a wobble, a curious head tilt, a droop
    var glance by remember { mutableFloatStateOf(0f) }  // where idle eyes look
    var giggles by remember { mutableIntStateOf(0) }  // happy eyes while a tap's hop lasts
    val eyeX = remember { Follow(42f) }; val eyeY = remember { Follow(42f) }
    val headX = remember { Follow(11f) }; val headY = remember { Follow(11f) }
    val moodNow by rememberUpdatedState(mood)
    val scope = rememberCoroutineScope()
    val haptic = LocalHapticFeedback.current

    suspend fun bounce(height: Float) {  // crouch, spring up stretched, slow at the top, fall faster and faster, land squashed
        squash.animateTo(0.9f, tween(90, easing = FastOutSlowInEasing))
        scope.launch { squash.animateTo(1.07f, tween(130)); squash.animateTo(1f, tween(200)) }
        hop.animateTo(-height, tween(200, easing = LinearOutSlowInEasing))
        hop.animateTo(0f, tween(180, easing = FastOutLinearInEasing))
        scope.launch { squash.snapTo(0.86f); squash.animateTo(1f, spring(dampingRatio = 0.38f, stiffness = 420f)) }
    }

    LaunchedEffect(Unit) {  // eyes and head chase where they should be, every frame
        var last = 0L
        while (true) withInfiniteAnimationFrameNanos { t ->
            val dt = if (last == 0L) 0f else ((t - last) / 1e9f).coerceAtMost(0.1f)
            last = t
            val to = aim(moodNow, glance, dart, line, sway)
            eyeX.step(to.x, dt); eyeY.step(to.y, dt); headX.step(to.x, dt); headY.step(to.y, dt)
        }
    }
    LaunchedEffect(drop) {
        if (!drop) return@LaunchedEffect
        dropY.animateTo(0f, tween(460, easing = FastOutLinearInEasing))
        squash.snapTo(0.8f)
        launch { squash.animateTo(1f, spring(dampingRatio = 0.35f, stiffness = 380f)) }
        hop.animateTo(-12f, tween(170, easing = LinearOutSlowInEasing))
        hop.animateTo(0f, tween(150, easing = FastOutLinearInEasing))
        launch { squash.snapTo(0.92f); squash.animateTo(1f, spring(dampingRatio = 0.45f, stiffness = 420f)) }
        onLanded()
    }
    LaunchedEffect(Unit) {  // blinks at its own pace, sometimes twice: the lid drops fast and lifts slower
        while (true) {
            delay(Random.nextLong(2400, 5600))
            repeat(if (Random.nextInt(4) == 0) 2 else 1) {
                blink.animateTo(0.08f, tween(75, easing = FastOutLinearInEasing)); delay(35)
                blink.animateTo(1f, tween(150, easing = LinearOutSlowInEasing)); delay(110)
            }
        }
    }
    LaunchedEffect(mood) {
        glance = 0f
        if (mood != Mood.Oops) launch { lean.animateTo(0f, spring(dampingRatio = 0.6f, stiffness = 160f)) }
        when (mood) {
            Mood.Ask -> repeat(2) { bounce(14f); delay(110) }
            Mood.Celebrate -> repeat(3) { bounce(16f); delay(90) }
            Mood.Oops -> {
                launch { squash.snapTo(0.9f); squash.animateTo(1f, spring(dampingRatio = 0.4f, stiffness = 300f)) }
                lean.animateTo(-8f, spring(dampingRatio = 0.55f, stiffness = 180f))
            }
            Mood.Idle -> while (fidget) {  // left alone, it fidgets now and then (not as an avatar beside every answer)
                delay(Random.nextLong(4500, 8500))
                when (Random.nextInt(4)) {
                    0 -> { glance = -3.5f; delay(Random.nextLong(500, 900)); glance = 3.5f; delay(Random.nextLong(500, 900)); glance = 0f }  // looks about
                    1 -> bounce(8f)
                    2 -> lean.animateTo(0f, spring(dampingRatio = 0.22f, stiffness = 110f), initialVelocity = 70f)  // a wobble that dies away
                    else -> { lean.animateTo(6f, spring(dampingRatio = 0.75f, stiffness = 90f)); delay(900); lean.animateTo(0f, spring(dampingRatio = 0.7f, stiffness = 90f)) }  // a curious head tilt
                }
            }
            else -> Unit
        }
        if (mood == Mood.Celebrate) { joy.snapTo(0f); joy.animateTo(1f, tween(900)) } else joy.snapTo(0f)
    }
    val poke = if (!interactive) Modifier else Modifier.pointerInput(Unit) {
        detectTapGestures {
            haptic.performHapticFeedback(HapticFeedbackType.ContextClick)
            scope.launch { giggles++; try { bounce(12f); delay(450) } finally { giggles-- } }
        }
    }

    Canvas(modifier.size(size).then(poke).semantics { contentDescription = label }) {
        val k = this.size.minDimension / 100f
        scale(k, pivot = Offset.Zero) {
            val sleeping = mood == Mood.Sleep
            val b = (1f - cos(breath * TAU)) / 2f  // a breath in and out; asleep, deeper
            val deep = if (sleeping) 2.2f else 1f
            val typing = if (mood == Mood.Run) sin(tap * TAU) * 0.9f else 0f
            val rock = when (mood) { Mood.Wave -> sin(sway * TAU) * 7f; Mood.Write -> sin(sway * TAU) * 2.5f; else -> 0f }
            val fx = headX.now * 0.4f; val fy = headY.now * 0.35f  // the face turns toward where the eyes went
            translate(0f, dropY.value + hop.value + typing) {
                rotate(rock + lean.value + headX.now * 0.6f, pivot = Offset(50f, 92f)) {
                    scale(scaleX = (2f - squash.value) * (1f + b * 0.008f * deep), scaleY = squash.value * (1f + b * 0.026f * deep), pivot = Offset(50f, 95f)) {
                        drawPath(shape, hood ?: p.ink)
                        if (rim) drawPath(shape, p.face.copy(alpha = 0.3f), style = Stroke(width = 2.4f))
                        drawOval(p.face, topLeft = Offset(20f + fx, 34f + fy), size = Size(60f, 54f))
                        translate(eyeX.now + fx, eyeY.now + fy) { eyes(p.ink, if (giggles > 0) Mood.Celebrate else mood, blink.value) }
                    }
                }
                badge(mood, p, (1f - cos(pulse * TAU)) / 2f)
            }
            if (sleeping) snores(p.muted, zz)
            if (mood == Mood.Celebrate && joy.value in 0.01f..0.99f) confetti(listOf(p.brick, p.warn, p.ok, p.plan), joy.value)
        }
    }
}

/** The eyes at rest; the caller moves them to where they look. */
private fun DrawScope.eyes(ink: Color, mood: Mood, blink: Float) {
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
            val cy = 62f + (1f - blink) * 2.2f  // the lid comes down from above, so a closing eye sinks a little
            for (x in listOf(38.5f, 61.5f)) {
                val ry = 7.8f * wide * blink
                drawOval(ink, topLeft = Offset(x - 6.2f, cy - ry), size = Size(12.4f, ry * 2))
                if (blink > 0.6f) drawCircle(Color.White, radius = 2.1f, center = Offset(x + 2.4f, cy - ry + 4.4f))
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
