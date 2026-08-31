package dev.busung.s25uroot

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

private data class RootState(
    val checking: Boolean = true,
    val root: Boolean = false,
    val id: String = "",
    val ksudVersion: String = "",
    val modules: List<String> = emptyList(),
    val apps: List<String> = emptyList(),
    val kernelVersion: String = "",
    val selinux: String = "",
    val note: String = "",
)

/** Run a command through KernelSU's `su`. Empty string on any failure. */
private fun runRoot(cmd: String): String {
    return try {
        val p = ProcessBuilder("su", "-c", cmd).redirectErrorStream(true).start()
        if (!p.waitFor(4, TimeUnit.SECONDS)) {
            p.destroy()
            return ""
        }
        p.inputStream.bufferedReader().readText().trim()
    } catch (e: Exception) {
        ""
    }
}

private fun queryRoot(): RootState {
    val id = runRoot("id")
    val rooted = id.contains("uid=0")
    val v = runRoot("/data/local/tmp/ksud-selected --version")
        .ifEmpty { runRoot("ksud -V") }
        .ifEmpty { runRoot("ksud version") }
    val modsRaw = runRoot("/data/local/tmp/ksud-selected module list")
        .ifEmpty { runRoot("ksud module list") }
    val appsRaw = runRoot("/data/local/tmp/ksud-selected app_list")
        .ifEmpty { runRoot("ksud app_list") }
    val kernelVersion = runRoot("uname -r")
    val selinux = runRoot("getenforce").ifEmpty { runRoot("cat /sys/fs/selinux/enforce") }
    val note = if (rooted) {
        ""
    } else {
        "No root access from this app yet. Run the install flow first, or su is not in PATH after reboot."
    }
    return RootState(
        checking = false,
        root = rooted,
        id = id,
        ksudVersion = v.ifEmpty { "unknown" },
        modules = modsRaw.lines().filter { it.isNotBlank() }.take(20),
        apps = appsRaw.lines().filter { it.isNotBlank() }.take(30),
        kernelVersion = kernelVersion,
        selinux = selinux,
        note = note,
    )
}

private fun startShizuku() {
    val dd = "/data/local/tmp/rmg-shizuku/shizuku_server.apk"
    val cmd = "nohup sh -c 'CLASSPATH=" + dd + " app_process /system/bin --nice-name=shizuku_server moe.shizuku.server.ShizukuServer' >/dev/null 2>&1 &"
    runCatching {
        val p = ProcessBuilder("su", "-c", cmd).redirectErrorStream(true).start()
        p.waitFor(3, TimeUnit.SECONDS)
    }
}

private fun openManagerApp(context: Context) {
    val pm = context.packageManager
    val intent = pm.getLaunchIntentForPackage("me.weishu.kernelsu")
        ?: pm.getLaunchIntentForPackage("com.rifsxd.ksunext")
    if (intent != null) {
        runCatching { context.startActivity(intent) }
    }
}

@Composable
private fun ManagerCard(title: String, content: @Composable () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(14.dp)) {
            Text(text = title, style = MaterialTheme.typography.titleMedium)
            Spacer(modifier = Modifier.height(8.dp))
            content()
        }
    }
}

@Composable
fun RootManagerPage(padding: PaddingValues) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var state by remember { mutableStateOf(RootState()) }
    var refreshKey by remember { mutableStateOf(0) }

    LaunchedEffect(refreshKey) {
        state = RootState(checking = true)
        state = withContext(Dispatchers.IO) { queryRoot() }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(padding)
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(
            text = "Root Manager",
            style = MaterialTheme.typography.headlineSmall,
        )
        Text(
            text = "In-app root manager — status, permissions and modules via KernelSU su.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        // status card
        ManagerCard(title = "Root status") {
            if (state.checking) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp), strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.width(10.dp))
                    Text("Checking root access…")
                }
            } else if (state.root) {
                Text(
                    text = "ACTIVE",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.primary,
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = state.id,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            } else {
                Text(
                    text = "INACTIVE",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.error,
                )
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = state.note,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        // ksud / kernel card
        ManagerCard(title = "KernelSU / ksud") {
            Text(
                text = state.ksudVersion,
                style = MaterialTheme.typography.bodyMedium,
                fontFamily = FontFamily.Monospace,
            )
            if (state.kernelVersion.isNotBlank()) {
                Spacer(modifier = Modifier.height(4.dp))
                Text(
                    text = "kernel: " + state.kernelVersion,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            }
            if (state.selinux.isNotBlank()) {
                Spacer(modifier = Modifier.height(2.dp))
                Text(
                    text = "selinux: " + state.selinux,
                    style = MaterialTheme.typography.bodySmall,
                    fontFamily = FontFamily.Monospace,
                )
            }
        }

        // permissions card
        ManagerCard(title = "Allowed apps (ksud app_list)") {
            if (state.apps.isEmpty()) {
                Text(
                    text = "No output. The ksud CLI may not expose app_list on this build.",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                state.apps.forEach { app ->
                    Text(
                        text = app,
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }

        // modules card
        ManagerCard(title = "Modules (ksud module list)") {
            if (state.modules.isEmpty()) {
                Text(
                    text = "No modules installed (or list not exposed).",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            } else {
                state.modules.forEach { mod ->
                    Text(
                        text = mod,
                        style = MaterialTheme.typography.bodySmall,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }

        // actions
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(onClick = { scope.launch { refreshKey++ } }) {
                Icon(Icons.Outlined.Refresh, contentDescription = null, modifier = Modifier.size(18.dp))
                Spacer(modifier = Modifier.width(6.dp))
                Text("Refresh")
            }
            OutlinedButton(onClick = { openManagerApp(context) }) {
                Text("Open manager app")
            }
            OutlinedButton(onClick = { scope.launch { startShizuku() } }) {
                Text("Start Shizuku server (standalone)")
            }
        }
    }
}
