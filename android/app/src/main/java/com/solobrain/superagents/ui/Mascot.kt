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
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.cos
import kotlin.math.sin
import kotlin.random.Random

/** The mascot's moods: it breathes and blinks; waves hello; thinks (eyes dart) while a turn runs; hops when a question
 *  arrives; sleeps when the laptop is away; celebrates a pairing. */
enum class Mood { Idle, Wave, Think, Hop, Sleep, Celebrate }

// brand/mark.svg, on its 100 × 100 canvas
private const val HOOD = "M50 95C30 95 14 93 11 86C8.5 80 9 68 9.5 56C11 31 27 14 48 12.5C56 12 63 9.5 70 3.5C71.2 9.5 69.8 14.5 66.5 17.8" +
    "C81 25 90 39 90.5 56C91 68 91.5 80 89 86C86 93 70 95 50 95Z"

/**
 * The Super Agents mascot, drawn from its own vector paths (sharp at any size) and alive: [drop] brings it in from
 * above on a spring, with a squash as it lands, then [onLanded].
 */
@Composable
fun Mascot(modifier: Modifier = Modifier, mood: Mood = Mood.Idle, size: Dp = 96.dp, drop: Boolean = false, onLanded: () -> Unit = {}) {
    val p = LocalPalette.current
    val hood = remember { PathParser().parsePathString(HOOD).toPath() }
    val loop = rememberInfiniteTransition(label = "mascot")
    val breath by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2400, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "breath")
    val dart by loop.animateFloat(0f, 1f, infiniteRepeatable(keyframes {
        durationMillis = 2200; 0f at 0; -1f at 300; -1f at 800; 1f at 1100; 1f at 1700; 0f at 2000
    }), label = "dart")
    val wave by loop.animateFloat(-1f, 1f, infiniteRepeatable(tween(520, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "wave")
    val zz by loop.animateFloat(0f, 1f, infiniteRepeatable(tween(2600, easing = LinearEasing)), label = "zz")

    val dropY = remember { Animatable(if (drop) -150f else 0f) }
    val hop = remember { Animatable(0f) }
    val squash = remember { Animatable(1f) }
    val blink = remember { Animatable(1f) }
    val joy = remember { Animatable(0f) }

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
        if (mood == Mood.Hop || mood == Mood.Celebrate) {
            repeat(if (mood == Mood.Celebrate) 3 else 2) {
                hop.animateTo(-15f, tween(180, easing = FastOutSlowInEasing))
                launch { squash.snapTo(0.86f); squash.animateTo(1f, spring(dampingRatio = 0.35f, stiffness = 500f)) }
                hop.animateTo(0f, spring(dampingRatio = 0.5f, stiffness = Spring.StiffnessMediumLow))
                delay(120)
            }
        }
        if (mood == Mood.Celebrate) { joy.snapTo(0f); joy.animateTo(1f, tween(900)) } else joy.snapTo(0f)
    }

    Canvas(modifier.size(size).semantics { contentDescription = "Super Agents mascot" }) {
        val k = this.size.minDimension / 100f
        scale(k, pivot = Offset.Zero) {
            val sleeping = mood == Mood.Sleep
            val bob = if (sleeping) 0f else (breath - 0.5f) * 3f
            val breathe = if (sleeping) 1f + breath * 0.03f else 1f
            val tilt = if (mood == Mood.Wave) wave * 7f else 0f
            translate(0f, dropY.value + hop.value + bob) {
                rotate(tilt, pivot = Offset(50f, 92f)) {
                    scale(scaleX = (2f - squash.value) * breathe, scaleY = squash.value * breathe, pivot = Offset(50f, 95f)) {
                        drawPath(hood, p.ink)
                        drawOval(p.face, topLeft = Offset(20f, 34f), size = Size(60f, 54f))
                        eyes(p.ink, mood, blink.value, if (mood == Mood.Think) dart * 3f else 0f)
                    }
                }
            }
            if (sleeping) snores(p.muted, zz)
            if (mood == Mood.Celebrate && joy.value in 0.01f..0.99f) confetti(listOf(p.brick, p.warn, p.ok, p.plan), joy.value)
        }
    }
}

private fun DrawScope.eyes(ink: Color, mood: Mood, blink: Float, look: Float) {
    when (mood) {
        Mood.Sleep -> for (x in listOf(38.5f, 61.5f)) {  // closed: two gentle arcs
            val arc = Path().apply { moveTo(x - 6f, 62f); quadraticTo(x, 67f, x + 6f, 62f) }
            drawPath(arc, ink, style = Stroke(width = 2.6f, cap = StrokeCap.Round))
        }
        Mood.Celebrate -> for (x in listOf(38.5f, 61.5f)) {  // happy: ^ ^
            val arc = Path().apply { moveTo(x - 6f, 64f); quadraticTo(x, 55f, x + 6f, 64f) }
            drawPath(arc, ink, style = Stroke(width = 2.8f, cap = StrokeCap.Round))
        }
        else -> {
            val wide = if (mood == Mood.Hop) 1.12f else 1f
            for (x in listOf(38.5f, 61.5f)) {
                val ry = 7.8f * wide * blink
                drawOval(ink, topLeft = Offset(x + look - 6.2f, 62f - ry), size = Size(12.4f, ry * 2))
                if (blink > 0.5f) drawCircle(Color.White, radius = 2.1f, center = Offset(x + look + 2.4f, 58.6f))
            }
        }
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
