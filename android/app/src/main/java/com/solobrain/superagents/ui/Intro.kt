package com.solobrain.superagents.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * The opening: Android's splash (the mascot on its brick circle) hands over to this. The brick circle settles, the
 * mascot drops in on a spring and squashes as it lands, blinks, and "Super Agents" rises under it. The first time
 * it plays in full; after that, a short version. A tap skips it.
 */
@Composable
fun Intro(short: Boolean, splashGone: StateFlow<Boolean>, onDone: () -> Unit) {
    val p = LocalPalette.current
    var landed by remember { mutableStateOf(false) }
    var started by remember { mutableStateOf(short) }
    val ring = remember { Animatable(if (short) 1f else 0.55f) }
    val words = remember { Animatable(0f) }
    val leave = remember { Animatable(1f) }
    var done by remember { mutableStateOf(false) }
    fun finish() { if (!done) { done = true; onDone() } }

    LaunchedEffect(Unit) {
        if (short) { landed = true; return@LaunchedEffect }
        withTimeoutOrNull(1200) { splashGone.first { it } }  // once Android's splash has gone: under it, the drop plays unseen
        started = true
        ring.animateTo(1f, tween(650, easing = FastOutSlowInEasing))
    }
    LaunchedEffect(landed) {
        if (!landed) return@LaunchedEffect
        launch { words.animateTo(1f, tween(if (short) 220 else 480, easing = FastOutSlowInEasing)) }
        delay(if (short) 260 else 900)
        leave.animateTo(0f, tween(260))
        finish()
    }
    Box(
        Modifier.fillMaxSize().background(p.bg).alpha(leave.value)
            .clickable(interactionSource = remember { MutableInteractionSource() }, indication = null) { finish() },
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Box(contentAlignment = Alignment.Center) {
                Box(Modifier.size(168.dp).graphicsLayer { scaleX = ring.value; scaleY = ring.value; alpha = 0.18f + 0.82f * ring.value }
                    .background(p.hoodBrick, CircleShape))
                if (started) Mascot(size = 112.dp, drop = !short, onLanded = { landed = true })
            }
            Spacer(Modifier.height(28.dp))
            Text("Super Agents", style = MaterialTheme.typography.displaySmall,
                modifier = Modifier.graphicsLayer { alpha = words.value; translationY = (1f - words.value) * 24f })
            Spacer(Modifier.height(6.dp))
            Text("Your agents, in your pocket", style = MaterialTheme.typography.bodyLarge, color = p.muted,
                modifier = Modifier.graphicsLayer { alpha = words.value; translationY = (1f - words.value) * 32f })
        }
    }
}
