# Super Agents for Android

The phone remote as a native app: Kotlin, Jetpack Compose, Material 3. It pairs with Super Agents on the laptop
(Settings → Phone) and speaks the same sealed messages as the web app (`cloud/cloud/site/remote/`). Why native, and
what it does: `docs/research/android-native-20261014.md`. How to use it: `docs/app.md`, Phone remote.

## Build
JDK 21 and the Android SDK 36, with `ANDROID_HOME` set (or `sdk.dir` in `local.properties`). From this folder:

    ./gradlew testDebugUnitTest assembleRelease

The APK is `app/build/outputs/apk/release/app-release.apk`, about 3 MB (shrunk with R8). It's signed with the debug
key until there's a release key, so it installs by hand (`adb install`, or open the file on the phone), not from a
store. CI builds the same APK (the `apk` job).

## Against a dev hub
The app talks HTTPS, except to loopback: after `adb reverse tcp:8811 tcp:8811` the phone reaches a hub on the laptop
at `http://127.0.0.1:8811`. Debug builds also allow `10.0.2.2`, the emulator's name for the laptop. A pairing link
names its hub: `superagents://pair#p=<channel>&k=<key>&h=http://127.0.0.1:8811`.

## Icons
`python android/scripts/icons.py`, from the repo root, renders the SVGs in `brand/` to the launcher and notification
icons (needs Playwright).
