package com.solobrain.superagents.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.ExperimentalTextApi
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.solobrain.superagents.R

/** The Super Agents palette (the desktop app's tokens), in dark and light. */
@Immutable
data class Palette(
    val bg: Color, val bg2: Color, val panel: Color, val panel2: Color, val line: Color, val line2: Color,
    val text: Color, val muted: Color, val faint: Color,
    val brick: Color, val onBrick: Color, val ok: Color, val bad: Color, val warn: Color, val plan: Color, val bubble: Color,
    val face: Color = Color(0xFFF4E6D8), val ink: Color = Color(0xFF18171B), val hoodBrick: Color = Color(0xFFA8443D),
)

val Dark = Palette(
    bg = Color(0xFF111013), bg2 = Color(0xFF161519), panel = Color(0xFF1C1B20), panel2 = Color(0xFF24222A),
    line = Color(0xFF2A2830), line2 = Color(0xFF38353F), text = Color(0xFFF3ECE0), muted = Color(0xFFA39B90), faint = Color(0xFF6F6960),
    brick = Color(0xFFD9675C), onBrick = Color(0xFF1A0E0C), ok = Color(0xFF4CC38A),
    bad = Color(0xFFF07A70), warn = Color(0xFFF2B32B), plan = Color(0xFF7FA6F0), bubble = Color(0xFF27252D),
)

val Light = Palette(
    bg = Color(0xFFF6F1E8), bg2 = Color(0xFFEFE8DC), panel = Color(0xFFFFFCF6), panel2 = Color(0xFFF3ECE1),
    line = Color(0xFFE6DDCF), line2 = Color(0xFFD6CBBB), text = Color(0xFF18171B), muted = Color(0xFF6B655D), faint = Color(0xFF9C948A),
    brick = Color(0xFFA8443D), onBrick = Color(0xFFFFF8F2), ok = Color(0xFF2C8A57),
    bad = Color(0xFFB84A40), warn = Color(0xFF9A6400), plan = Color(0xFF3D68B8), bubble = Color(0xFFEAE2D4),
)

val LocalPalette = staticCompositionLocalOf { Dark }

@OptIn(ExperimentalTextApi::class)
private fun variable(res: Int, weight: Int) =
    Font(res, FontWeight(weight), variationSettings = FontVariation.Settings(FontVariation.weight(weight)))

val Figtree = FontFamily(listOf(400, 500, 600, 700, 800).map { variable(R.font.figtree, it) })
val Bricolage = FontFamily(listOf(500, 600, 700, 800).map { variable(R.font.bricolage, it) })
val Mono = FontFamily(listOf(400, 500, 600, 700).map { variable(R.font.jetbrains_mono, it) })

@Composable
fun SuperAgentsTheme(dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val p = if (dark) Dark else Light
    val scheme = if (dark) darkColorScheme(
        primary = p.brick, onPrimary = p.onBrick, background = p.bg, onBackground = p.text, surface = p.bg, onSurface = p.text,
        surfaceVariant = p.panel, onSurfaceVariant = p.muted, surfaceContainer = p.bg2, surfaceContainerHigh = p.panel,
        surfaceContainerHighest = p.panel2, surfaceContainerLow = p.bg2, outline = p.line2, outlineVariant = p.line,
        secondaryContainer = p.panel2, onSecondaryContainer = p.text, error = p.bad,
    ) else lightColorScheme(
        primary = p.brick, onPrimary = p.onBrick, background = p.bg, onBackground = p.text, surface = p.bg, onSurface = p.text,
        surfaceVariant = p.panel, onSurfaceVariant = p.muted, surfaceContainer = p.bg2, surfaceContainerHigh = p.panel,
        surfaceContainerHighest = p.panel2, surfaceContainerLow = p.bg2, outline = p.line2, outlineVariant = p.line,
        secondaryContainer = p.panel2, onSecondaryContainer = p.text, error = p.bad,
    )
    // No colour in the styles: text takes its container's (a button's, a sheet's), and the palette's text everywhere else
    val base = TextStyle(fontFamily = Figtree)
    val type = Typography(
        displaySmall = TextStyle(fontFamily = Bricolage, fontWeight = FontWeight(800), fontSize = 30.sp, lineHeight = 34.sp, letterSpacing = (-0.5).sp),
        headlineSmall = TextStyle(fontFamily = Bricolage, fontWeight = FontWeight(750), fontSize = 24.sp, lineHeight = 28.sp, letterSpacing = (-0.3).sp),
        titleLarge = TextStyle(fontFamily = Bricolage, fontWeight = FontWeight(750), fontSize = 21.sp, lineHeight = 26.sp),
        titleMedium = base.copy(fontWeight = FontWeight(700), fontSize = 16.sp, lineHeight = 22.sp),
        bodyLarge = base.copy(fontSize = 16.sp, lineHeight = 24.sp),
        bodyMedium = base.copy(fontSize = 14.5.sp, lineHeight = 21.sp),
        bodySmall = base.copy(fontSize = 13.sp, lineHeight = 18.sp, color = p.muted),
        labelLarge = base.copy(fontWeight = FontWeight(650), fontSize = 15.sp),
        labelMedium = base.copy(fontWeight = FontWeight(650), fontSize = 12.5.sp),
        labelSmall = TextStyle(fontFamily = Mono, fontWeight = FontWeight(600), fontSize = 11.sp, letterSpacing = 1.sp),
    )
    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = scheme, typography = type) {
            CompositionLocalProvider(LocalContentColor provides p.text, content = content)
        }
    }
}
