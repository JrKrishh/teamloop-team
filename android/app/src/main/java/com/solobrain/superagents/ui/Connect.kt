package com.solobrain.superagents.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning
import com.solobrain.superagents.MainActivity
import com.solobrain.superagents.Prefs
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.LinkService
import com.solobrain.superagents.remote.Pairings
import kotlinx.coroutines.delay

enum class Stage { Welcome, Connecting, Connected, OptIns }

/**
 * Connect to your laptop: like Claude Code's or Codex's remote control, you prove you're at the laptop by scanning
 * the code it shows (Settings → Phone → Pair a phone). Then: connecting, paired, and two choices made here once.
 */
@Composable
fun Connect(activity: MainActivity, start: Stage, onDone: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val r = ctx.remote
    var stage by remember { mutableStateOf(start) }
    var error by remember { mutableStateOf<String?>(null) }
    var pasting by remember { mutableStateOf(false) }
    var pasted by remember { mutableStateOf("") }
    val laptop by r.laptop.collectAsState()

    fun pairWith(text: String) {
        val link = Pairings.parse(text)
        if (link == null) { error = "That isn't a Super Agents pairing code."; return }
        error = null
        r.pair(link)
        stage = Stage.Connecting
    }
    fun scan() {
        error = null
        GmsBarcodeScanning.getClient(ctx, GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).enableAutoZoom().build())
            .startScan()
            .addOnSuccessListener { code -> code.rawValue?.let(::pairWith) }
            .addOnFailureListener { error = "The scanner isn't ready on this phone yet. Paste the link instead." }
    }

    LaunchedEffect(stage, laptop) {
        if (stage == Stage.Connecting && laptop != null) { stage = Stage.Connected; LinkService.start(ctx) }
        if (stage == Stage.Connecting) {
            delay(40_000)
            if (stage == Stage.Connecting && r.laptop.value == null) { error = "Your laptop didn't answer. Is Super Agents open on it, with remote control on?"; stage = Stage.Welcome }
        }
        if (stage == Stage.Connected) { delay(1800); stage = Stage.OptIns }
    }

    Box(Modifier.fillMaxSize().background(p.bg).statusBarsPadding().navigationBarsPadding()) {
        AnimatedContent(stage, transitionSpec = { (fadeIn() + slideInVertically { it / 12 }) togetherWith fadeOut() }, label = "stage") { s ->
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = if (s == Stage.Welcome || s == Stage.OptIns) Arrangement.Top else Arrangement.Center,
            ) {
                when (s) {
                    Stage.Welcome -> {
                        Spacer(Modifier.height(24.dp))
                        Mascot(size = 104.dp, mood = Mood.Wave)
                        Spacer(Modifier.height(22.dp))
                        Text("Connect to your laptop", style = MaterialTheme.typography.displaySmall, textAlign = TextAlign.Center)
                        Spacer(Modifier.height(10.dp))
                        Text("Your agents keep working on the laptop. From here you answer them, start them and watch them work.",
                            style = MaterialTheme.typography.bodyLarge, color = p.muted, textAlign = TextAlign.Center)
                        Spacer(Modifier.height(26.dp))
                        StepRow(1, "Open Super Agents on your laptop.")
                        StepRow(2, "Go to Settings → Phone and press Pair a phone.")
                        StepRow(3, "Scan the code it shows.")
                        Spacer(Modifier.height(26.dp))
                        Button(onClick = ::scan, modifier = Modifier.fillMaxWidth().height(54.dp).testTag("scan"), shape = RoundedCornerShape(16.dp)) {
                            Icon(Glyph.Scan, null, Modifier.size(22.dp)); Spacer(Modifier.width(10.dp))
                            Text("Scan the pairing code", style = MaterialTheme.typography.labelLarge)
                        }
                        Spacer(Modifier.height(8.dp))
                        if (!pasting) TextButton(onClick = { pasting = true }) { Text("Paste a link instead", color = p.brick) }
                        else {
                            OutlinedTextField(pasted, { pasted = it }, Modifier.fillMaxWidth().testTag("paste"), singleLine = true,
                                placeholder = { Text("https://…/remote/#p=…") }, shape = RoundedCornerShape(14.dp))
                            Spacer(Modifier.height(8.dp))
                            OutlinedButton(onClick = { pairWith(pasted) }, Modifier.fillMaxWidth(), shape = RoundedCornerShape(14.dp), colors = ButtonDefaults.outlinedButtonColors(contentColor = LocalPalette.current.text)) { Text("Pair") }
                        }
                        error?.let { Spacer(Modifier.height(12.dp)); Text(it, color = p.bad, textAlign = TextAlign.Center, style = MaterialTheme.typography.bodyMedium) }
                        Spacer(Modifier.height(22.dp))
                        Row(Modifier.border(1.dp, p.line, RoundedCornerShape(999.dp)).padding(horizontal = 14.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Glyph.Lock, null, Modifier.size(16.dp), tint = p.ok); Spacer(Modifier.width(8.dp))
                            Text("End-to-end encrypted. Only this phone and your laptop hold the key.", style = MaterialTheme.typography.bodySmall)
                        }
                    }
                    Stage.Connecting -> {
                        Mascot(size = 112.dp, mood = Mood.Think)
                        Spacer(Modifier.height(24.dp))
                        Text("Connecting to your laptop…", style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
                        Spacer(Modifier.height(8.dp))
                        Text("Super Agents has to be open on it.", style = MaterialTheme.typography.bodyLarge, color = p.muted)
                    }
                    Stage.Connected -> {
                        Mascot(size = 120.dp, mood = Mood.Celebrate)
                        Spacer(Modifier.height(24.dp))
                        Text("Paired with ${laptop?.name ?: "your laptop"}", style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center,
                            modifier = Modifier.testTag("paired"))
                        Spacer(Modifier.height(8.dp))
                        Text("Your agents can reach you now.", style = MaterialTheme.typography.bodyLarge, color = p.muted)
                    }
                    Stage.OptIns -> OptIns(activity, onDone)
                }
            }
        }
    }
}

@Composable
private fun StepRow(n: Int, text: String) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(30.dp).background(p.panel2, CircleShape), contentAlignment = Alignment.Center) {
            Text("$n", style = MaterialTheme.typography.labelLarge, color = p.brick)
        }
        Spacer(Modifier.width(14.dp))
        Text(text, style = MaterialTheme.typography.bodyLarge)
    }
}

/** Two choices, made once: a fingerprint lock, and letting the agents reach you (Android's permission, asked with
 *  the reason first). */
@Composable
private fun OptIns(activity: MainActivity, onDone: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    var lock by remember { mutableStateOf(Prefs.lock(ctx)) }
    var allowed by remember {
        mutableStateOf(Build.VERSION.SDK_INT < 33 || ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED)
    }
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed = it }
    Spacer(Modifier.height(20.dp))
    Mascot(size = 84.dp, mood = Mood.Idle)
    Spacer(Modifier.height(18.dp))
    Text("Two quick choices", style = MaterialTheme.typography.headlineSmall)
    Spacer(Modifier.height(20.dp))
    if (activity.canLock()) Choice("Lock with fingerprint", "Ask for it when Super Agents opens, and after a minute away.") {
        Switch(lock, onCheckedChange = { on ->
            if (!on) { lock = false; Prefs.setLock(ctx, false) }
            else activity.authenticate { ok -> if (ok) { lock = true; Prefs.setLock(ctx, true) } }
        })
    }
    Choice("Let your agents reach you", "When an agent needs your yes, or answers, while the app is closed. Approve right from the notification.") {
        if (allowed) Text("On", color = p.ok, fontWeight = FontWeight.Bold)
        else OutlinedButton(onClick = { if (Build.VERSION.SDK_INT >= 33) ask.launch(Manifest.permission.POST_NOTIFICATIONS) }, colors = ButtonDefaults.outlinedButtonColors(contentColor = LocalPalette.current.text)) { Text("Allow") }
    }
    Spacer(Modifier.height(26.dp))
    Button(onClick = onDone, modifier = Modifier.fillMaxWidth().height(54.dp).testTag("done"), shape = RoundedCornerShape(16.dp),
        colors = ButtonDefaults.buttonColors(containerColor = p.brick)) { Text("Done", style = MaterialTheme.typography.labelLarge) }
}

@Composable
private fun Choice(title: String, sub: String, control: @Composable () -> Unit) {
    val p = LocalPalette.current
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp).background(p.panel, RoundedCornerShape(18.dp)).border(1.dp, p.line, RoundedCornerShape(18.dp))
        .padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(3.dp))
            Text(sub, style = MaterialTheme.typography.bodySmall)
        }
        Spacer(Modifier.width(12.dp))
        control()
    }
}
