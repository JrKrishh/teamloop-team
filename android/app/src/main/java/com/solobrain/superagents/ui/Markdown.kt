package com.solobrain.superagents.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.os.Build
import android.widget.Toast
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp

/** An answer's blocks, parsed apart from drawing them so the parser can be tested on its own. */
sealed interface Md {
    data class Para(val text: String) : Md
    data class Heading(val level: Int, val text: String) : Md
    data class Item(val mark: String, val depth: Int, val text: String) : Md
    data class Code(val lang: String, val text: String) : Md
    data class Quote(val text: String) : Md
    data object Rule : Md
    data class Table(val head: List<String>, val align: List<Char>, val rows: List<List<String>>) : Md
}

private val BR = Regex("<br\\s*/?>", RegexOption.IGNORE_CASE)
// citation marks some models leave in answers (the laptop takes them out of new ones): 【3†source】, 【38aaba8c…】
private val CITE = Regex("\\s?【(?:\\{[^】]*\\}|\\d+†[^】]*|[0-9a-f]{8,64})】")
private val HEADING = Regex("^(#{1,6})\\s+(.*?)\\s*#*\\s*$")
private val ITEM = Regex("^(\\s*)([-*+]|\\d+[.)])\\s+(.*)$")
private val RULE = Regex("^\\s*([-*_])(\\s*\\1){2,}\\s*$")
private val TABLE_SEP = Regex("^\\s*\\|?\\s*:?-+:?\\s*(\\|\\s*:?-+:?\\s*)*\\|?\\s*$")

private fun fence(l: String) = l.trimStart().let { it.startsWith("```") || it.startsWith("~~~") }
private fun tableAt(lines: List<String>, i: Int) =
    i + 1 < lines.size && '|' in lines[i] && '|' in lines[i + 1] && TABLE_SEP.matches(lines[i + 1])

/** A table row's cells: the outer pipes dropped, "\|" kept as a pipe. */
internal fun cells(line: String): List<String> {
    var s = line.trim()
    if (s.startsWith("|")) s = s.drop(1)
    if (s.endsWith("|") && !s.endsWith("\\|")) s = s.dropLast(1)
    return s.split(Regex("(?<!\\\\)\\|")).map { it.trim().replace("\\|", "|") }
}

/** Markdown as agents write it (GitHub's flavour): paragraphs, headings, lists (nested, numbered, tasks), code fences,
 *  quotes, rules and tables, with <br> as a line break. */
internal fun parseMarkdown(text: String): List<Md> {
    val lines = text.replace("\r\n", "\n").replace(CITE, "").lines()
    val out = mutableListOf<Md>()
    fun startsBlock(at: Int): Boolean {
        val l = lines[at]
        return fence(l) || HEADING.matches(l) || RULE.matches(l) || ITEM.matches(l) || l.trimStart().startsWith(">") || tableAt(lines, at)
    }
    var i = 0
    while (i < lines.size) {
        val l = lines[i]
        when {
            l.isBlank() -> i++
            fence(l) -> {
                val mark = l.trimStart().take(3)
                val lang = l.trimStart().drop(3).trim().substringBefore(' ')
                val code = mutableListOf<String>(); i++
                while (i < lines.size && !lines[i].trimStart().startsWith(mark)) code.add(lines[i++])
                i++  // the closing fence
                out.add(Md.Code(lang, code.joinToString("\n")))
            }
            tableAt(lines, i) -> {
                val head = cells(l).map { it.replace(BR, "\n") }
                val align = cells(lines[i + 1]).map { c -> if (c.startsWith(":") && c.endsWith(":")) 'c' else if (c.endsWith(":")) 'r' else 'l' }
                i += 2
                val rows = mutableListOf<List<String>>()
                while (i < lines.size && lines[i].isNotBlank() && '|' in lines[i]) {
                    val r = cells(lines[i++])
                    rows.add(List(head.size) { k -> r.getOrElse(k) { "" }.replace(BR, "\n") })
                }
                out.add(Md.Table(head, List(head.size) { k -> align.getOrElse(k) { 'l' } }, rows))
            }
            HEADING.matches(l) -> { val m = HEADING.find(l)!!; out.add(Md.Heading(m.groupValues[1].length, m.groupValues[2])); i++ }
            RULE.matches(l) -> { out.add(Md.Rule); i++ }
            l.trimStart().startsWith(">") -> {
                val q = mutableListOf<String>()
                while (i < lines.size && lines[i].trimStart().startsWith(">")) q.add(lines[i++].trimStart().removePrefix(">").removePrefix(" "))
                out.add(Md.Quote(q.joinToString("\n").replace(BR, "\n")))
            }
            ITEM.matches(l) -> {
                val m = ITEM.find(l)!!
                val depth = (m.groupValues[1].replace("\t", "    ").length / 2).coerceAtMost(3)
                var body = m.groupValues[3]
                val mark = when {
                    body.startsWith("[ ] ") -> { body = body.drop(4); "☐" }
                    body.startsWith("[x] ", ignoreCase = true) -> { body = body.drop(4); "☑" }
                    m.groupValues[2].first().isDigit() -> m.groupValues[2].dropLast(1) + "."
                    else -> "•"
                }
                i++
                while (i < lines.size && lines[i].isNotBlank() && lines[i].startsWith("  ") && !startsBlock(i)) body += " " + lines[i++].trim()
                out.add(Md.Item(mark, depth, body.replace(BR, "\n")))
            }
            else -> {
                val para = mutableListOf(l.trim()); i++
                while (i < lines.size && lines[i].isNotBlank() && !startsBlock(i)) para.add(lines[i++].trim())
                out.add(Md.Para(para.joinToString(" ").replace(BR, "\n")))
            }
        }
    }
    return out
}

/** An agent's answer, drawn the way Claude draws one. Only text is drawn: nothing an agent writes can run here. */
@Composable
fun Markdown(text: String) {
    val p = LocalPalette.current
    val blocks = remember(text) { parseMarkdown(text) }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        for (b in blocks) when (b) {
            is Md.Para -> Text(inline(b.text, p), style = MaterialTheme.typography.bodyLarge)
            is Md.Heading -> Text(inline(b.text, p), Modifier.padding(top = 6.dp), style = when (b.level) {
                1 -> MaterialTheme.typography.headlineSmall
                2 -> MaterialTheme.typography.titleLarge
                else -> MaterialTheme.typography.titleMedium
            })
            is Md.Item -> Row(Modifier.padding(start = 18.dp * b.depth)) {
                Text(b.mark, color = p.muted, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.width(if (b.mark.length > 2) 30.dp else 22.dp))
                Text(inline(b.text, p), style = MaterialTheme.typography.bodyLarge)
            }
            is Md.Code -> CodeBlock(b)
            is Md.Quote -> Row(Modifier.height(IntrinsicSize.Min)) {
                Box(Modifier.width(3.dp).fillMaxHeight().clip(RoundedCornerShape(2.dp)).background(p.line2))
                Spacer(Modifier.width(12.dp))
                Text(inline(b.text, p), style = MaterialTheme.typography.bodyLarge, color = p.muted)
            }
            Md.Rule -> HorizontalDivider(Modifier.padding(vertical = 4.dp), color = p.line)
            is Md.Table -> TableView(b)
        }
    }
}

@Composable
private fun CodeBlock(b: Md.Code) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(p.bg2).border(1.dp, p.line, RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(b.lang.ifEmpty { "code" }, style = MaterialTheme.typography.labelSmall, color = p.faint, modifier = Modifier.weight(1f))
            Text("Copy", style = MaterialTheme.typography.labelMedium, color = p.brick, modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable {
                ctx.getSystemService(ClipboardManager::class.java)?.setPrimaryClip(ClipData.newPlainText("code", b.text))
                if (Build.VERSION.SDK_INT < 33) Toast.makeText(ctx, "Copied", Toast.LENGTH_SHORT).show()  // Android 13+ says so itself
            }.padding(horizontal = 10.dp, vertical = 8.dp))
        }
        Text(b.text, style = MaterialTheme.typography.bodySmall.copy(fontFamily = Mono, color = p.text),
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(start = 12.dp, end = 12.dp, bottom = 12.dp))
    }
}

/** A table: columns sized to what's in them, the header shaded, rows apart by a line. It fits the screen when every
 *  column keeps a readable width; a wider one scrolls sideways, as in Claude's app, fading at the edge to say so. */
@Composable
private fun TableView(t: Md.Table) {
    val p = LocalPalette.current
    val scroll = rememberScrollState()
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val natural = t.head.indices.map { k ->
            val longest = (listOf(t.head) + t.rows).maxOf { r -> r[k].lines().maxOfOrNull { plain(it).length } ?: 0 }
            (longest * 7.6f + 24f).coerceIn(84f, 240f)
        }
        val widths = fit(natural, maxWidth.value - 2f, readable = 100f)
        Box {
            Column(Modifier.clip(RoundedCornerShape(12.dp)).border(1.dp, p.line, RoundedCornerShape(12.dp)).horizontalScroll(scroll)) {
                TableRow(t.head, t.align, widths, p.panel2, head = true)
                t.rows.forEachIndexed { i, r ->
                    HorizontalDivider(Modifier.width(widths.sum().dp), color = p.line)
                    TableRow(r, t.align, widths, if (i % 2 == 1) p.bg2 else Color.Transparent, head = false)
                }
            }
            if (scroll.canScrollForward) Box(Modifier.matchParentSize().clip(RoundedCornerShape(12.dp))) {
                Box(Modifier.align(Alignment.CenterEnd).width(32.dp).fillMaxHeight().background(Brush.horizontalGradient(listOf(Color.Transparent, p.bg))))
            }
        }
    }
}

/** Column widths for the room there is: stretched to fill it, squeezed into it while every column stays [readable], or
 *  left as they are to scroll. */
internal fun fit(natural: List<Float>, room: Float, readable: Float): List<Float> {
    val total = natural.sum()
    if (total <= room) return natural.map { it * room / total }
    if (natural.size * readable > room) return natural
    val squeezed = natural.map { maxOf(readable, it * room / total) }
    val flexible = squeezed.filter { it > readable }.sum()
    val over = squeezed.sum() - room
    return squeezed.map { if (it > readable) it - over * it / flexible else it }
}

@Composable
private fun TableRow(cells: List<String>, align: List<Char>, widths: List<Float>, shade: Color, head: Boolean) {
    val p = LocalPalette.current
    Row(Modifier.height(IntrinsicSize.Min).background(shade)) {
        cells.forEachIndexed { k, c ->
            Text(inline(c, p), Modifier.width(widths[k].dp).fillMaxHeight().padding(horizontal = 12.dp, vertical = 9.dp),
                style = if (head) MaterialTheme.typography.labelLarge else MaterialTheme.typography.bodyMedium,
                textAlign = when (align[k]) { 'c' -> TextAlign.Center; 'r' -> TextAlign.End; else -> TextAlign.Start })
        }
    }
}

private fun plain(s: String) = s.replace(Regex("\\*\\*|~~|`"), "").replace(Regex("\\[([^\\]]+)]\\([^)]*\\)"), "$1")

private val INLINE = Regex("(`[^`]+`)|(\\*\\*[^*]+\\*\\*)|(~~[^~]+~~)|(\\*[^*\\s][^*]*\\*)|(\\[([^\\]]+)]\\((https?://[^\\s)]+)\\))")

private fun inline(s: String, p: Palette): AnnotatedString = buildAnnotatedString {
    var last = 0
    for (m in INLINE.findAll(s)) {
        append(s.substring(last, m.range.first))
        val g = m.groupValues
        when {
            g[1].isNotEmpty() -> withStyle(SpanStyle(fontFamily = Mono, background = p.panel2)) { append(g[1].drop(1).dropLast(1)) }
            g[2].isNotEmpty() -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(g[2].drop(2).dropLast(2)) }
            g[3].isNotEmpty() -> withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) { append(g[3].drop(2).dropLast(2)) }
            g[4].isNotEmpty() -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append(g[4].drop(1).dropLast(1)) }
            else -> withLink(LinkAnnotation.Url(g[7], TextLinkStyles(SpanStyle(color = p.brick)))) { append(g[6]) }
        }
        last = m.range.last + 1
    }
    append(s.substring(last))
}
