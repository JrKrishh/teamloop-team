package com.solobrain.superagents

import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricManager.Authenticators.BIOMETRIC_WEAK
import androidx.biometric.BiometricManager.Authenticators.DEVICE_CREDENTIAL
import androidx.biometric.BiometricPrompt
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.activity.SystemBarStyle
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.testTagsAsResourceId
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.splashscreen.SplashScreen.Companion.installSplashScreen
import androidx.fragment.app.FragmentActivity
import com.solobrain.superagents.remote.LinkService
import com.solobrain.superagents.remote.Pairings
import com.solobrain.superagents.ui.ChatOpen
import com.solobrain.superagents.ui.ChatScreen
import com.solobrain.superagents.ui.Connect
import com.solobrain.superagents.ui.Home
import com.solobrain.superagents.ui.Intro
import com.solobrain.superagents.ui.LocalPalette
import com.solobrain.superagents.ui.Mascot
import com.solobrain.superagents.ui.Mood
import com.solobrain.superagents.ui.Stage
import com.solobrain.superagents.ui.SuperAgentsTheme
import com.solobrain.superagents.ui.Tab
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import com.solobrain.superagents.remote.Accounts
import com.solobrain.superagents.remote.Auth
import com.solobrain.superagents.remote.AuthError
import com.solobrain.superagents.ui.SignIn
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class MainActivity : FragmentActivity() {
    private val incoming = MutableStateFlow<Intent?>(null)
    val lockNow = MutableStateFlow(false)
    val splashGone = MutableStateFlow(false)
    val theme = MutableStateFlow("system")  // "system", "light" or "dark": the top bar's button and Settings change it
    private var awayAt = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        val splash = installSplashScreen()
        super.onCreate(savedInstanceState)
        splash.setOnExitAnimationListener { view ->  // the splash's mascot zooms away into the intro
            view.iconView.animate().scaleX(1.6f).scaleY(1.6f).alpha(0f).setDuration(280).withEndAction { view.remove(); splashGone.value = true }.start()
        }
        enableEdgeToEdge()
        incoming.value = intent
        theme.value = Prefs.theme(this)
        setContent {
            val t by theme.collectAsState()
            val dark = when (t) { "light" -> false; "dark" -> true; else -> isSystemInDarkTheme() }
            LaunchedEffect(dark) {  // the status bar's icons follow the app's theme, not only the phone's
                val bars = if (dark) SystemBarStyle.dark(android.graphics.Color.TRANSPARENT)
                else SystemBarStyle.light(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT)
                enableEdgeToEdge(bars, bars)
            }
            SuperAgentsTheme(dark) { Root(this, incoming) }
        }
    }

    fun useTheme(t: String) {
        Prefs.setTheme(this, t)
        theme.value = t
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        incoming.value = intent
    }

    override fun onStart() {
        super.onStart()
        if (Prefs.lock(this) && awayAt > 0 && System.currentTimeMillis() - awayAt > 60_000) lockNow.value = true
        remote.start()
        LinkService.start(this)
    }

    override fun onStop() {
        super.onStop()
        awayAt = System.currentTimeMillis()
    }

    fun canLock(): Boolean = BiometricManager.from(this).canAuthenticate(BIOMETRIC_WEAK or DEVICE_CREDENTIAL) == BiometricManager.BIOMETRIC_SUCCESS

    fun authenticate(done: (Boolean) -> Unit) {
        val prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = done(true)
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) = done(false)
        })
        prompt.authenticate(BiometricPrompt.PromptInfo.Builder().setTitle("Super Agents").setSubtitle("Unlock to see your agents")
            .setAllowedAuthenticators(BIOMETRIC_WEAK or DEVICE_CREDENTIAL).build())
    }
}

private sealed interface Route {
    data object Intro : Route
    data object SignIn : Route
    data object Locked : Route
    data class Connecting(val stage: Stage) : Route
    data object Home : Route
    data class Chat(val open: ChatOpen) : Route
}

@OptIn(ExperimentalComposeUiApi::class)
@Composable
private fun Root(activity: MainActivity, incoming: StateFlow<Intent?>) {
    val ctx = LocalContext.current
    val r = ctx.remote
    var route by remember { mutableStateOf<Route>(Route.Intro) }
    var tab by remember { mutableStateOf(Tab.Needs) }
    var unlocked by remember { mutableStateOf(!Prefs.lock(ctx)) }
    var fresh by remember { mutableStateOf(false) }  // paired just now, by a link
    var waitingChat by remember { mutableStateOf<ChatOpen?>(null) }
    var finishing by remember { mutableStateOf(false) }  // back from GitHub, trading the code for a session
    var authError by remember { mutableStateOf<String?>(null) }
    fun next(): Route = when {
        !r.paired && !Accounts.signedIn(ctx) && !Prefs.signInSkipped(ctx) -> Route.SignIn  // new phones; paired ones sign in from Settings
        !r.paired -> Route.Connecting(Stage.Welcome)
        !unlocked -> Route.Locked
        fresh -> Route.Connecting(Stage.Connecting)
        else -> waitingChat?.let { waitingChat = null; Route.Chat(it) } ?: Route.Home
    }

    val intent by incoming.collectAsState()
    LaunchedEffect(intent) {
        val i = intent ?: return@LaunchedEffect
        i.getStringExtra("account_hub")?.let { Accounts.overrideHub(ctx, it) }  // debug builds only: tests sign in to a local hub
        val data = i.data
        if (data?.scheme == "superagents" && data.host == "auth") {  // back from GitHub or an email link: superagents://auth/callback?code=…
            finishing = true; authError = null
            if (route != Route.Intro) route = Route.SignIn
            runCatching {
                withContext(Dispatchers.IO) {
                    val (hub, verifier) = Accounts.takePending(ctx) ?: throw AuthError("That sign-in ran out. Try again.")
                    data.getQueryParameter("error_description")?.let { throw AuthError(it) }
                    val code = data.getQueryParameter("code") ?: throw AuthError("That sign-in didn't finish. Try again.")
                    val auth = Auth(r.http)
                    auth.session(hub, auth.exchange(auth.supabase(hub), code, verifier))
                }
            }.onSuccess { Accounts.save(ctx, it); finishing = false; if (route != Route.Intro) route = next() }
                .onFailure { finishing = false; authError = it.message; if (route != Route.Intro) route = Route.SignIn }
            return@LaunchedEffect
        }
        val link = i.dataString?.let(Pairings::parse)
        if (link != null) {  // a pairing link: superagents://pair#… or the laptop's https link
            r.pair(link); fresh = true
            if (route != Route.Intro) route = Route.Connecting(Stage.Connecting)
            return@LaunchedEffect
        }
        val chat = i.getStringExtra("chat")
        val turn = i.getStringExtra("turn")
        if (chat != null || turn != null) {  // a notification, tapped
            val open = ChatOpen(chat, r.laptop.value?.live?.firstOrNull { it.turn == turn })
            if (route == Route.Intro || route == Route.Locked) waitingChat = open else route = Route.Chat(open)
        }
    }
    val lockNow by activity.lockNow.collectAsState()
    LaunchedEffect(lockNow) {
        if (!lockNow) return@LaunchedEffect
        activity.lockNow.value = false
        unlocked = false
        if (route is Route.Home || route is Route.Chat) route = Route.Locked
    }
    BackHandler(enabled = route == Route.Home && tab != Tab.Needs) { tab = Tab.Needs }

    androidx.compose.foundation.layout.Box(Modifier.fillMaxSize().semantics { testTagsAsResourceId = true }) {
        AnimatedContent(route, transitionSpec = { fadeIn(tween(260)) togetherWith fadeOut(tween(200)) }, label = "route") { rt ->
            when (rt) {
                Route.Intro -> Intro(short = Prefs.introSeen(ctx), activity.splashGone) {
                    Prefs.setIntroSeen(ctx); route = if (finishing || authError != null) Route.SignIn else next()
                }
                Route.SignIn -> SignIn(finishing, authError, onDone = { authError = null; route = next() },
                    onSkip = { authError = null; Prefs.setSignInSkipped(ctx); route = next() })
                Route.Locked -> Locked { activity.authenticate { ok -> if (ok) { unlocked = true; route = next() } } }
                is Route.Connecting -> Connect(activity, rt.stage) { fresh = false; route = next() }
                Route.Home -> Home(activity, tab, { tab = it }, { route = Route.Chat(it) }, onForgotten = { route = Route.Connecting(Stage.Welcome) },
                    onSignIn = { route = Route.SignIn })
                is Route.Chat -> ChatScreen(rt.open) { route = Route.Home }
            }
        }
    }
}

@Composable
private fun Locked(onUnlock: () -> Unit) {
    val p = LocalPalette.current
    LaunchedEffect(Unit) { onUnlock() }
    Column(Modifier.fillMaxSize().background(p.bg).padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        Mascot(size = 96.dp, mood = Mood.Sleep)
        Spacer(Modifier.height(20.dp))
        Text("Locked", style = MaterialTheme.typography.headlineSmall)
        Spacer(Modifier.height(6.dp))
        Text("Unlock to see what your agents are doing.", color = p.muted)
        Spacer(Modifier.height(24.dp))
        Button(onClick = onUnlock, shape = RoundedCornerShape(16.dp), modifier = Modifier.testTag("unlock")) { Text("Unlock") }
    }
}
