package com.solobrain.superagents.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp

/** An agent's answer: paragraphs, headings, lists, code blocks; bold, italic, code and links inline. Only text is
 *  drawn: nothing an agent writes can run here. */
@Composable
fun Markdown(text: String) {
    val p = LocalPalette.current
    val lines = text.lines()
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        var i = 0
        while (i < lines.size) {
            val l = lines[i]
            when {
                l.trimStart().startsWith("```") -> {
                    val code = mutableListOf<String>(); i++
                    while (i < lines.size && !lines[i].trimStart().startsWith("```")) code.add(lines[i++])
                    i++
                    Text(code.joinToString("\n"), style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text),
                        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.bg2).border(1.dp, p.line, RoundedCornerShape(12.dp))
                            .horizontalScroll(rememberScrollState()).padding(12.dp))
                }
                Regex("^#{1,4}\\s+").containsMatchIn(l) -> { Text(inline(l.replace(Regex("^#{1,4}\\s+"), ""), p), style = MaterialTheme.typography.titleLarge); i++ }
                Regex("^\\s*([-*]|\\d+\\.)\\s+").containsMatchIn(l) -> {
                    val m = Regex("^\\s*([-*]|\\d+\\.)\\s+(.*)$").find(l)!!
                    val mark = if (m.groupValues[1].endsWith(".")) m.groupValues[1] else "•"
                    Row { Text(mark, color = p.muted, modifier = Modifier.width(22.dp)); Text(inline(m.groupValues[2], p), style = MaterialTheme.typography.bodyLarge) }
                    i++
                }
                l.isBlank() -> i++
                else -> {
                    val para = mutableListOf(l); i++
                    while (i < lines.size && lines[i].isNotBlank() && !Regex("^(\\s*```|#{1,4}\\s|\\s*([-*]|\\d+\\.)\\s)").containsMatchIn(lines[i])) para.add(lines[i++])
                    Text(inline(para.joinToString(" "), p), style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }
}

private val INLINE = Regex("(`[^`]+`)|(\\*\\*[^*]+\\*\\*)|(\\*[^*\\s][^*]*\\*)|(\\[([^\\]]+)]\\((https?://[^\\s)]+)\\))")

private fun inline(s: String, p: Palette): AnnotatedString = buildAnnotatedString {
    var last = 0
    for (m in INLINE.findAll(s)) {
        append(s.substring(last, m.range.first))
        val g = m.groupValues
        when {
            g[1].isNotEmpty() -> withStyle(SpanStyle(fontFamily = Mono, background = p.panel2)) { append(g[1].drop(1).dropLast(1)) }
            g[2].isNotEmpty() -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(g[2].drop(2).dropLast(2)) }
            g[3].isNotEmpty() -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(g[3].drop(1).dropLast(1)) }
            else -> withLink(LinkAnnotation.Url(g[6], TextLinkStyles(SpanStyle(color = p.brick)))) { append(g[5]) }
        }
        last = m.range.last + 1
    }
    append(s.substring(last))
}
