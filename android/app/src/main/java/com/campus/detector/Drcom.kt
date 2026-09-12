package com.campus.detector

import android.content.Context
import android.net.Network
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.Proxy
import java.net.URL
import java.net.URLEncoder

/**
 * drcom 校园网认证协议（与桌面版 core.py 的 chkstatus/login 逻辑一致）。
 *
 * 关键点：
 * 1. 必须 Proxy.NO_PROXY 直连——如果吃系统代理，认证请求会被代理劫持，
 *    表现为"永远检测不到认证状态/登录失败"，这是桌面版踩过的坑。
 * 2. 移动数据劫持场景下,必须绑定到 WiFi Network 发请求,
 *    否则系统默认路由会把认证请求导向移动数据通道,导致请求到不了校园网认证服务器。
 *    典型场景:用户连校园 WiFi(未认证) + 开了移动数据,系统 activeNetwork 是移动数据。
 */
object Drcom {

    data class AuthStatus(
        val reachable: Boolean,   // 认证服务器是否可达（区分非校园网）
        val online: Boolean?,     // null=无法判断；true=已认证；false=未认证
        val account: String,
        val carrier: String,
        val message: String
    )

    data class LoginResult(val ok: Boolean, val message: String)

    private val userAgents = listOf(
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile Safari/604.1"
    )

    /**
     * 从 JSONP 响应中提取第一个 JSON 对象：括号深度计数，
     * 能正确跳过字符串内的花括号（移植自桌面版 core.py 的 _extract_json_object）。
     */
    fun extractJsonObject(text: String): String? {
        val start = text.indexOf('{')
        if (start < 0) return null
        var depth = 0
        var inString = false
        var escape = false
        for (i in start until text.length) {
            val ch = text[i]
            if (inString) {
                when {
                    escape -> escape = false
                    ch == '\\' -> escape = true
                    ch == '"' -> inString = false
                }
            } else {
                when (ch) {
                    '"' -> inString = true
                    '{' -> depth++
                    '}' -> {
                        depth--
                        if (depth == 0) return text.substring(start, i + 1)
                    }
                }
            }
        }
        return null
    }

    /**
     * 强制直连的 HTTP GET,返回 (状态码, 响应体)；网络异常向上抛出。
     *
     * 可选绑定到指定 Network(绕过系统默认路由,避免移动数据劫持)。
     * network 为 null 时退化为 Proxy.NO_PROXY(与原逻辑一致)。
     */
    private fun httpGet(
        urlStr: String, referer: String, timeoutMs: Int,
        network: Network? = null
    ): Pair<Int, String> {
        var conn: HttpURLConnection? = null
        try {
            val url = URL(urlStr)
            // 绑定到 WiFi Network 时,URL.openConnection(network, proxy)
            // 强制让请求走指定 Network,系统默认路由(可能是移动数据)被绕过
            conn = if (network != null) {
                network.openConnection(url, Proxy.NO_PROXY) as HttpURLConnection
            } else {
                url.openConnection(Proxy.NO_PROXY) as HttpURLConnection
            }
            conn.connectTimeout = timeoutMs
            conn.readTimeout = timeoutMs
            conn.instanceFollowRedirects = true
            conn.setRequestProperty("User-Agent", userAgents.random())
            conn.setRequestProperty("Referer", referer)
            conn.setRequestProperty("Accept", "*/*")
            val code = conn.responseCode
            val stream = if (code in 200..399) conn.inputStream else conn.errorStream
            val body = stream?.bufferedReader()?.use { it.readText() } ?: ""
            return Pair(code, body)
        } finally {
            conn?.disconnect()
        }
    }

    /**
     * 查询认证状态：GET chkstatus?callback=dr1003&jsVersion=4.X&v=随机数
     *
     * 自动检测是否处于移动数据劫持场景,如果是则绑定到 WiFi Network 发请求。
     * ctx 为 null 时退化为不绑定(用于单元测试或旧调用方)。
     */
    fun checkStatus(cfg: JSONObject, timeoutMs: Int = 4000, ctx: Context? = null): AuthStatus {
        val statusUrl = cfg.optString("status_url")
        val portalUrl = cfg.optString("portal_url")
        // 如果检测到移动数据劫持 WiFi,绑定到 WiFi Network 发请求
        val wifiNet = ctx?.let { NetChecks.wifiNetwork(it) }
        return try {
            val url = "$statusUrl?callback=dr1003&jsVersion=4.2&v=${(1000..9999).random()}"
            val (code, body) = httpGet(url, portalUrl, timeoutMs, wifiNet)
            if (code != 200) {
                return AuthStatus(true, null, "", "", "认证服务器响应异常（HTTP $code）")
            }
            parseChkstatus(body)
        } catch (e: Exception) {
            AuthStatus(false, null, "", "", "认证服务器无法访问（${e.message ?: "网络错误"}）")
        }
    }

    /** 解析 chkstatus 的 JSONP 响应（字段名兼容多个 drcom 版本） */
    fun parseChkstatus(body: String): AuthStatus {
        val jsonStr = extractJsonObject(body)
            ?: return AuthStatus(true, null, "", "", "响应不是预期的 JSONP 格式")
        return try {
            val obj = JSONObject(jsonStr)
            val account = listOf("uid", "account", "user", "DDDDD", "username")
                .firstOrNull { obj.has(it) && !obj.optString(it).isNullOrEmpty() }
                ?.let { obj.optString(it) } ?: ""
            val carrier = if (account.contains('@')) account.substringAfter('@') else ""
            val msg = obj.optString("error", "").ifEmpty { obj.optString("msg", "") }

            // 在线判断分两级，必须同时识别"在线"和"明确离线"，
            // 否则未登录响应（如 {"result":1,"online":0,"msg":"not online"}）
            // 会被报成"无法确定认证状态"。
            // 1) 显式在线标志：不同固件字段名不同，只取第一个出现的字段
            //    （与桌面端 core.py 语义一致，兼容 1/yes/true/ok 与 0/no/false）
            var online: Boolean? = null
            for (key in listOf("is_authorized", "online", "is_login", "islogon")) {
                if (obj.has(key)) {
                    val v = obj.optString(key).trim().lowercase()
                    online = v in setOf("1", "yes", "true", "ok")
                    break
                }
            }
            // 2) 没有布尔字段时看结果码：
            //    真实 drcom 在线通常 result=0；未登录常见 result=1/ret_code=2
            if (online == null) {
                val result = obj.optString("result", "")
                val retCode = obj.optString("ret_code", "")
                val code = obj.optString("code", "")
                online = when {
                    result == "0" || retCode == "0" || code == "0" -> true
                    result == "1" || retCode in setOf("1", "2") || code == "1" -> false
                    msg.contains("not online", ignoreCase = true) -> false
                    else -> null
                }
            }
            AuthStatus(true, online, account.removeSuffix("@$carrier"), carrier, msg)
        } catch (_: Exception) {
            AuthStatus(true, null, "", "", "JSONP 解析失败")
        }
    }

    /**
     * 登录：GET login?DDDDD=学号@运营商&upass=密码&...
     *
     * 参数优先从配置的 drcom_params 读取（与桌面版 config.json 对齐，便于两端统一维护），
     * 缺失时回退内置默认值。
     *
     * 自动检测移动数据劫持场景并绑定到 WiFi Network,
     * 保证认证请求一定走 WiFi 通道到达校园网认证服务器。
     */
    fun login(
        cfg: JSONObject,
        account: String,
        carrier: String,
        password: String,
        timeoutMs: Int = 5000,
        ctx: Context? = null
    ): LoginResult {
        val loginUrl = cfg.optString("login_url")
        val portalUrl = cfg.optString("portal_url")
        val fullAccount = if (carrier.isNotEmpty() && !account.contains('@')) "$account@$carrier" else account

        // 优先读配置中的 drcom_params，缺失键用默认值补齐
        val p = cfg.optJSONObject("drcom_params") ?: JSONObject()
        val params = mapOf(
            "callback" to p.optString("callback", "dr1003"),
            "DDDDD" to fullAccount,
            "upass" to password,
            "0MKKey" to p.optString("0MKKey", "123456"),
            "R1" to p.optString("R1", "0"),
            "R2" to p.optString("R2", ""),
            "R3" to p.optString("R3", "0"),
            "R6" to p.optString("R6", "0"),
            "para" to p.optString("para", "00"),
            "v6ip" to p.optString("v6ip", ""),
            "terminal_type" to p.optString("terminal_type", "1"),
            "lang" to p.optString("lang", "zh-cn"),
            "jsVersion" to p.optString("jsVersion", "4.2"),
            "v" to p.optString("v", "7081")
        )
        val qs = params.entries.joinToString("&") {
            "${it.key}=${URLEncoder.encode(it.value, "UTF-8")}"
        }
        // 移动数据劫持场景下绑定到 WiFi Network,确保认证请求不走移动数据
        val wifiNet = ctx?.let { NetChecks.wifiNetwork(it) }
        return try {
            val (code, body) = httpGet("$loginUrl?$qs", portalUrl, timeoutMs, wifiNet)
            if (code != 200) {
                return LoginResult(false, "认证服务器响应异常（HTTP $code）")
            }
            parseLoginResponse(body)
        } catch (e: Exception) {
            LoginResult(false, "无法连接认证服务器（${e.message ?: "网络错误"}）")
        }
    }

    /** 解析登录响应：result==1 成功；失败时优先展示服务器给出的提示 */
    fun parseLoginResponse(body: String): LoginResult {
        val jsonStr = extractJsonObject(body)
            ?: return LoginResult(false, "响应不是预期的 JSONP 格式")
        return try {
            val obj = JSONObject(jsonStr)
            val result = obj.optString("result", obj.optString("ret", obj.optString("code", "")))
            val ok = result == "1" || obj.optBoolean("success", false)
            val serverMsg = obj.optString("error", "")
                .ifEmpty { obj.optString("error_msg", "") }
                .ifEmpty { obj.optString("msg", "") }
                .ifEmpty { obj.optString("loadErrorPrompt", "") }
            if (ok) {
                LoginResult(true, "登录成功")
            } else {
                LoginResult(false, serverMsg.ifEmpty { "登录失败（服务器未确认，账号密码错误或已在线）" })
            }
        } catch (_: Exception) {
            LoginResult(false, "响应解析失败")
        }
    }
}
