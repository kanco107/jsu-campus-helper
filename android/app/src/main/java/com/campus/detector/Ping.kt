package com.campus.detector

import java.net.InetSocketAddress
import java.net.Socket

/**
 * ping 封装：调用 Android 自带的 /system/bin/ping 子进程。
 *
 * 与桌面版一致：成功标准是收到 echo 回复（含 ttl=）；
 * 部分 campus 网络禁 ICMP 时调用方应回退 tcpProbe() 做端口连通性探测。
 */
object Ping {
    data class Result(val ok: Boolean, val detail: String)

    fun ping(host: String, count: Int = 2, timeoutSec: Int = 2): Result {
        return try {
            val proc = ProcessBuilder(
                "/system/bin/ping", "-c", count.toString(), "-W", timeoutSec.toString(), host
            ).redirectErrorStream(true).start()
            val out = proc.inputStream.bufferedReader().use { it.readText() }
            val code = proc.waitFor()
            if (code == 0 && out.contains("ttl=", ignoreCase = true)) {
                val time = Regex("""time[=<]([\d.]+)\s*ms""").findAll(out)
                    .lastOrNull()?.groupValues?.get(1)
                Result(true, if (time != null) "连通，延迟 ${time}ms" else "连通")
            } else {
                Result(false, failReason(out))
            }
        } catch (e: Exception) {
            Result(false, "ping 无法执行：${e.message}")
        }
    }

    /** TCP 回退探测：ICMP 被禁时用端口连通性近似判断（网关 80/443 通常开放） */
    fun tcpProbe(host: String, port: Int, timeoutMs: Int = 2000): Boolean {
        return try {
            Socket().use { s ->
                s.connect(InetSocketAddress(host, port), timeoutMs)
                true
            }
        } catch (_: Exception) {
            false
        }
    }

    private fun failReason(out: String): String {
        val low = out.lowercase()
        return when {
            "unreachable" in low || "不可达" in out -> "目标不可达"
            "timed out" in low || "timeout" in low || "超时" in out -> "请求超时"
            "100% packet loss" in low || "100.0% packet loss" in low -> "全部丢包"
            "unknown host" in low || "未知主机" in out -> "主机不可解析"
            "network is down" in low || "network unreachable" in low -> "网络未连接"
            else -> "不可达"
        }
    }
}
