# The libraries (Compose, OkHttp, coroutines, ML Kit) bring their own rules. Nothing of ours is reached by reflection.

# Debug logging (the kind of each message, never what it says) stays out of release builds.
-assumenosideeffects class android.util.Log { public static int d(...); }
