package dev.busung.s25uroot

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Marks an auto-root run as pending after every boot. The actual install starts
 * the next time the app UI is opened (Android blocks background activity starts);
 * the pending flag is consumed once in RootApp.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (!AppPreferences.autoRootOnBoot(context)) return
        AppPreferences.markAutoRootPending(context)
        runCatching {
            context.startActivity(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
        }
    }
}
