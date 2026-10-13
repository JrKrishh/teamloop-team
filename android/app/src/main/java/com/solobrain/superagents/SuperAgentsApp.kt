package com.solobrain.superagents

import android.app.Application
import android.content.Context
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import com.solobrain.superagents.remote.Notifications
import com.solobrain.superagents.remote.Remote

class SuperAgentsApp : Application() {
    lateinit var remote: Remote
        private set

    override fun onCreate() {
        super.onCreate()
        Notifications.channels(this)
        remote = Remote(this)
        // on screen or not: questions become notifications only when the app isn't in front of you
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) { remote.inForeground = true }
            override fun onStop(owner: LifecycleOwner) { remote.inForeground = false }
        })
    }
}

val Context.remote: Remote get() = (applicationContext as SuperAgentsApp).remote
