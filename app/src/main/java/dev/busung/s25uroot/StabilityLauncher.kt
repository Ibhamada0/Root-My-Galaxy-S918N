package dev.busung.s25uroot

import android.os.SystemClock
import java.io.File
import kotlinx.coroutines.delay

/**
 * BOPE-style "Stability Launcher".
 *
 * The idea is ported from the reference Root My Galaxy (SM-S918B) project: instead of
 * hammering the kernel the moment the user taps, watch the device and only start the
 * exploit once it is genuinely idle. The launcher samples uptime, runnable tasks, free
 * memory and thermal headroom, and only turns green after several consecutive clean
 * samples. Any noisy sample resets the streak, so a busy device is never handed the
 * "fast lane".
 */
object StabilityLauncher {

    enum class Lane { Fast, Normal }

    data class Sample(
        val uptimeSec: Long,
        val runnableTasks: Int,
        val memAvailableKb: Long,
        val maxTempC: Int,
        val clean: Boolean,
        val reason: String,
    )

    data class Readiness(
        val ready: Boolean,
        val samples: Int,
        val last: Sample?,
        val lane: Lane,
    )

    private const val REQUIRED_CLEAN_SAMPLES = 3
    private const val POLL_INTERVAL_MS = 700L
    private const val MIN_UPTIME_SEC = 90L
    private const val MAX_RUNNABLE = 6
    private const val MIN_MEM_AVAILABLE_KB = 900_000L
    private const val MAX_TEMP_C = 43

    private val thermalZones: List<File> by lazy {
        (0..15).map { File("/sys/class/thermal/thermal_zone$it/temp") }.filter { it.canRead() }
    }

    fun sample(): Sample {
        val uptimeSec = readUptimeSec()
        val runnable = readRunnableTasks()
        val memKb = readMemAvailableKb()
        val tempC = readMaxTempC()

        val problems = buildList {
            if (uptimeSec in 1 until MIN_UPTIME_SEC) add("uptime=${uptimeSec}s")
            if (runnable > MAX_RUNNABLE) add("runnable=$runnable")
            if (memKb in 1 until MIN_MEM_AVAILABLE_KB) add("mem=${memKb}kB")
            if (tempC > MAX_TEMP_C) add("temp=${tempC}C")
        }

        return Sample(
            uptimeSec = uptimeSec,
            runnableTasks = runnable,
            memAvailableKb = memKb,
            maxTempC = tempC,
            clean = problems.isEmpty(),
            reason = if (problems.isEmpty()) "idle" else problems.joinToString(","),
        )
    }

    /** Cooperative wait until the device looks idle, or the timeout elapses. */
    suspend fun awaitReady(timeoutMs: Long = 60_000L): Readiness {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        var clean = 0
        var last: Sample? = null
        while (SystemClock.elapsedRealtime() < deadline) {
            val s = sample()
            last = s
            clean = if (s.clean) clean + 1 else 0
            if (clean >= REQUIRED_CLEAN_SAMPLES) {
                return Readiness(true, clean, s, Lane.Fast)
            }
            delay(POLL_INTERVAL_MS)
        }
        return Readiness(false, clean, last, Lane.Normal)
    }

    private fun readUptimeSec(): Long = try {
        File("/proc/uptime").readText().trim().substringBefore(' ').toDouble().toLong()
    } catch (_: Throwable) { 0L }

    private fun readRunnableTasks(): Int = try {
        val field = File("/proc/loadavg").readText().trim().split(' ').getOrNull(3) ?: return 0
        field.substringBefore('/').toInt()
    } catch (_: Throwable) { 0 }

    private fun readMemAvailableKb(): Long = try {
        File("/proc/meminfo").readLines()
            .firstOrNull { it.startsWith("MemAvailable:") }
            ?.split(Regex("\\s+"))?.getOrNull(1)?.toLong() ?: 0L
    } catch (_: Throwable) { 0L }

    private fun readMaxTempC(): Int {
        var max = 0
        for (z in thermalZones) {
            val raw = try { z.readText().trim().toLong() } catch (_: Throwable) { continue }
            val c = if (raw > 1000) (raw / 1000).toInt() else raw.toInt()
            if (c in 1..150 && c > max) max = c
        }
        return max
    }
}
