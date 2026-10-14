package com.solobrain.superagents

import com.solobrain.superagents.ui.Md
import com.solobrain.superagents.ui.Mood
import com.solobrain.superagents.ui.fit
import com.solobrain.superagents.ui.moodFor
import com.solobrain.superagents.ui.parseMarkdown
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Answers read as they were written: tables as tables, <br> as a new line, and the rest of GitHub's Markdown. */
class MarkdownTest {
    @Test fun readsATableWithLineBreaksInItsCells() {
        // the shape of a real Agent S answer that used to show as one paragraph of pipes
        val b = parseMarkdown("""
            ## How to unblock

            | Option | What to do | Pros | Cons |
            |--------|------------|------|------|
            | 1. **Grant ALTER** | Ask the DBA to run:<br>`GRANT ALTER ON demo_db.* TO 'hub_user'@'%';` | Runs as-is. | Needs approval. |
            | 2. **Use a migrator** | Create a user | Keeps hub read-only. | More to manage. |
            Then pick one.
        """.trimIndent())
        assertEquals(Md.Heading(2, "How to unblock"), b[0])
        val t = b[1] as Md.Table
        assertEquals(listOf("Option", "What to do", "Pros", "Cons"), t.head)
        assertEquals(2, t.rows.size)
        assertEquals("1. **Grant ALTER**", t.rows[0][0])
        assertEquals("Ask the DBA to run:\n`GRANT ALTER ON demo_db.* TO 'hub_user'@'%';`", t.rows[0][1])
        assertEquals(Md.Para("Then pick one."), b[2])
    }

    @Test fun alignsColumnsKeepsEscapedPipesAndPadsShortRows() {
        val t = parseMarkdown("| a | b | c |\n|:--|:-:|--:|\n| x \\| y | 2 |")[0] as Md.Table
        assertEquals(listOf('l', 'c', 'r'), t.align)
        assertEquals(listOf("x | y", "2", ""), t.rows[0])
    }

    @Test fun readsTheOtherBlocks() {
        val b = parseMarkdown("# Title\n\nSome text\nwraps here.<br>New line.\n\n- one\n  - nested\n1. first\n- [x] done\n\n> quoted\n\n---\n\n```kotlin\nval x = 1\n```")
        assertEquals(listOf(
            Md.Heading(1, "Title"), Md.Para("Some text wraps here.\nNew line."), Md.Item("•", 0, "one"), Md.Item("•", 1, "nested"),
            Md.Item("1.", 0, "first"), Md.Item("☑", 0, "done"), Md.Quote("quoted"), Md.Rule, Md.Code("kotlin", "val x = 1")), b)
    }

    @Test fun leavesOutCitationMarks() {
        assertEquals(listOf(Md.Para("T-11 is blocked. All else is moving.")),
            parseMarkdown("T-11 is blocked 【38aaba8cab3c470287a8571e7d5b25f7】. All else is moving."))
    }

    @Test fun aRuleIsNotATable() {
        assertEquals(listOf(Md.Para("a | b"), Md.Rule), parseMarkdown("a | b\n\n---"))
    }

    @Test fun fitsColumnsToTheScreenWhileTheyStayReadable() {
        val stretched = fit(listOf(80f, 90f), room = 380f, readable = 100f)
        assertEquals(380f, stretched.sum(), 0.01f)
        val squeezed = fit(listOf(168f, 240f), room = 380f, readable = 100f)  // two columns: no sideways scrolling
        assertEquals(380f, squeezed.sum(), 0.01f)
        assertTrue(squeezed.all { it >= 100f })
        val wide = listOf(240f, 240f, 240f, 240f)  // four full columns can't fit readably: they scroll
        assertEquals(wide, fit(wide, room = 380f, readable = 100f))
    }

    @Test fun theMascotActsOutTheStep() {
        assertEquals(Mood.Read, moodFor("read_file"))
        assertEquals(Mood.Run, moodFor("run_command"))
        assertEquals(Mood.Run, moodFor("git_push"))
        assertEquals(Mood.Write, moodFor("write_file"))
        assertEquals(Mood.Search, moodFor("browser_open"))
        assertEquals(Mood.Think, moodFor(null))
        assertEquals(Mood.Think, moodFor("mcp__linear__get_issue"))
    }
}
