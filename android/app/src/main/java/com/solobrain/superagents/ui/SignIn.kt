package com.solobrain.superagents.ui

import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import com.solobrain.superagents.remote
import com.solobrain.superagents.remote.Accounts
import com.solobrain.superagents.remote.Auth
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Sign in with the account from the desktop app: GitHub (in a browser tab that comes back here) or email. Skippable:
 * the laptop's pairing code is what connects a phone, with or without an account.
 */
@Composable
fun SignIn(finishing: Boolean, outerError: String?, onDone: () -> Unit, onSkip: () -> Unit) {
    val p = LocalPalette.current
    val ctx = LocalContext.current
    val auth = remember { Auth(ctx.remote.http) }
    val scope = rememberCoroutineScope()
    var withEmail by remember { mutableStateOf(false) }
    var creating by remember { mutableStateOf(false) }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf<String?>(null) }  // which button is working
    var error by remember { mutableStateOf<String?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }

    fun github() {
        busy = "github"; error = null
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { val hub = Accounts.hub(ctx); hub to auth.supabase(hub) } }
                .onSuccess { (hub, s) ->
                    val (verifier, challenge) = Auth.pkce()
                    Accounts.startPending(ctx, hub, verifier)
                    CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(ctx, Uri.parse(auth.authorizeUrl(s, challenge)))
                }
                .onFailure { error = it.message ?: "Couldn't reach the server." }
            busy = null
        }
    }

    fun submit() {
        if (email.isBlank() || password.length < 8 || (creating && name.isBlank())) {
            error = if (password.length < 8) "The password needs at least 8 characters." else "Fill in each field."
            return
        }
        busy = "email"; error = null; notice = null
        scope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val hub = Accounts.hub(ctx)
                    val s = auth.supabase(hub)
                    val token = if (creating) {
                        val (verifier, challenge) = Auth.pkce()
                        Accounts.startPending(ctx, hub, verifier)  // the confirmation link comes back here with a code for this
                        auth.signUp(s, email.trim(), password, name.trim(), challenge)
                    } else auth.password(s, email.trim(), password)
                    token?.let { auth.session(hub, it) }
                }
            }.onSuccess { account ->
                if (account == null) { notice = "Check your email and open the link on this phone: it signs you in here."; creating = false }
                else { Accounts.save(ctx, account); onDone() }
            }.onFailure { error = it.message ?: "Couldn't sign in." }
            busy = null
        }
    }

    Column(Modifier.fillMaxSize().background(p.bg).statusBarsPadding().navigationBarsPadding().imePadding().verticalScroll(rememberScrollState())
        .padding(horizontal = 24.dp, vertical = 32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Spacer(Modifier.height(24.dp))
        Mascot(size = 96.dp, mood = if (finishing) Mood.Think else Mood.Wave, interactive = true)
        Spacer(Modifier.height(20.dp))
        Text("Sign in to Super Agents", style = MaterialTheme.typography.headlineSmall, textAlign = TextAlign.Center)
        Spacer(Modifier.height(6.dp))
        Text(if (finishing) "Finishing your GitHub sign-in…" else "The same account as on your laptop.",
            style = MaterialTheme.typography.bodyMedium, color = p.muted, textAlign = TextAlign.Center)
        Spacer(Modifier.height(28.dp))
        Column(Modifier.widthIn(max = 420.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = ::github, enabled = busy == null && !finishing, modifier = Modifier.fillMaxWidth().height(54.dp).testTag("github"),
                shape = RoundedCornerShape(16.dp), colors = ButtonDefaults.buttonColors(containerColor = p.text, contentColor = p.bg)) {
                if (busy == "github" || finishing) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = p.bg)
                else Text("Continue with GitHub", style = MaterialTheme.typography.labelLarge)
            }
            if (!withEmail) OutlinedButton(onClick = { withEmail = true; error = null }, enabled = busy == null && !finishing,
                modifier = Modifier.fillMaxWidth().height(54.dp).testTag("email-start"), shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.outlinedButtonColors(contentColor = p.text)) { Text("Continue with email", style = MaterialTheme.typography.labelLarge) }
            AnimatedVisibility(withEmail, enter = expandVertically() + fadeIn()) {
                Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (creating) OutlinedTextField(name, { name = it }, Modifier.fillMaxWidth().testTag("name"), singleLine = true,
                        shape = RoundedCornerShape(14.dp), label = { Text("Your name") })
                    OutlinedTextField(email, { email = it }, Modifier.fillMaxWidth().testTag("email"), singleLine = true, shape = RoundedCornerShape(14.dp),
                        label = { Text("Email") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email))
                    OutlinedTextField(password, { password = it }, Modifier.fillMaxWidth().testTag("password"), singleLine = true, shape = RoundedCornerShape(14.dp),
                        label = { Text("Password") }, visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password))
                    Button(onClick = ::submit, enabled = busy == null, modifier = Modifier.fillMaxWidth().height(52.dp).testTag("signin"),
                        shape = RoundedCornerShape(16.dp), colors = ButtonDefaults.buttonColors(containerColor = p.brick, contentColor = p.onBrick)) {
                        if (busy == "email") CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = p.onBrick)
                        else Text(if (creating) "Create account" else "Sign in", style = MaterialTheme.typography.labelLarge)
                    }
                    TextButton(onClick = { creating = !creating; error = null }, modifier = Modifier.align(Alignment.CenterHorizontally).testTag("create")) {
                        Text(if (creating) "Have an account? Sign in" else "New here? Create an account", color = p.brick)
                    }
                }
            }
            (error ?: outerError)?.let { Text(it, color = p.bad, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().testTag("auth-error")) }
            notice?.let { Text(it, color = p.ok, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth()) }
        }
        Spacer(Modifier.height(20.dp))
        TextButton(onClick = onSkip, enabled = !finishing, modifier = Modifier.testTag("skip")) { Text("Skip for now", color = p.muted) }
        Text("Your laptop's pairing code connects this phone with or without an account.", style = MaterialTheme.typography.bodySmall,
            color = p.faint, textAlign = TextAlign.Center)
    }
}
