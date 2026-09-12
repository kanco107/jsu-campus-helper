package com.campus.detector

import android.content.Context
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean

/**
 * 检测引擎：并行执行 9 项检测，逐项把结果推送给前端（卡片逐个翻牌）。
 *
 * 纯只读检测——不修改任何系统网络配置（这是安卓版与桌面版的根本区别）。
 * 慢项（ping 超时 2 秒）不阻塞快项；全部结束后汇总一份报告推送 done 事件。
 */
class Engine(private val ctx: Context) {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val running = AtomicBoolean(false)

    /** 9 项检测的固定定义（顺序即 UI 卡片展示顺序） */
    private val checkDefs = listOf(
        "connection" to "网络连接",
        "wifi" to "校园 WiFi",
        "signal" to "WiFi 信号强度",
        "intranet" to "校园网内网",
        "external" to "外网连通",
        "auth" to "校园网认证",
        "dns" to "域名解析",
        "proxy" to "系统代理",
        "linklocal" to "IP 获取状态"
    )

    /** 预计算 key→title 映射，runCheck 中 O(1) 查找（避免每次 first{} 线性扫描） */
    private val titleMap: Map<String, String> = checkDefs.toMap()

    fun runDetection() {
        if (!running.compareAndSet(false, true)) {
            Events.post("log", mapOf("text" to "已有一次检测在进行中，请稍候…"))
            return
        }
        scope.launch {
            try {
                val cfg = ConfigStore.load(ctx)
                val results = ConcurrentHashMap<String, JSONObject>()

                Events.post("busy", mapOf("running" to true))
                Events.post("log", mapOf("text" to "开始网络诊断…"))

                // 先把 9 张卡片以"检测中"状态推给前端
                val initArr = JSONArray()
                for ((key, title) in checkDefs) {
                    initArr.put(
                        JSONObject().put("key", key).put("title", title)
                            .put("status", "wait").put("detail", "检测中…")
                    )
                }
                Events.post("checksInit", mapOf("checks" to initArr))

                // 应用层互联网验证（204/HTTPS，绑定 WiFi）只执行一次，
                // “网络连接/外网连通/域名解析”三项共用同一份结果，避免重复探测
                val internetDef = async { NetChecks.checkInternet(ctx) }

                // 并行执行基础检测，各检查项完成后立即推送自己的结果
                val baseJobs = listOf(
                    async { runCheck(results, "connection") { checkConnection(ctx, internetDef.await()) } },
                    async { runCheck(results, "wifi") { checkWifi(ctx, cfg) } },
                    async { runCheck(results, "signal") { checkSignal(ctx) } },
                    async { runCheck(results, "intranet") { checkIntranet(ctx, cfg) } },
                    async { runCheck(results, "external") { checkExternal(ctx, cfg, internetDef.await()) } },
                    async { runCheck(results, "dns") { checkDns(cfg, internetDef.await()) } },
                    async { runCheck(results, "proxy") { checkProxy(ctx) } },
                    async { runCheck(results, "linklocal") { checkLinkLocal() } }
                )
                baseJobs.awaitAll()
                // 认证检测依赖 intranet/linklocal 结果，基础检测完成后才执行
                runCheck(results, "auth") { checkAuth(cfg, results) }

                // 汇总报告（此时所有协程已结束，results 读取安全）
                val report = buildReport(results, cfg)
                Events.post("done", mapOf("report" to report))
                Events.post("busy", mapOf("running" to false))
                Events.post(
                    "log",
                    mapOf("text" to "诊断完成：${report.optString("summary")}")
                )
            } catch (e: Exception) {
                Events.post("log", mapOf("text" to "诊断过程出现异常：${e.message}"))
                Events.post("busy", mapOf("running" to false))
            } finally {
                running.set(false)
            }
        }
    }

    /** 单项检测执行器：捕获所有异常，保证一项失败不影响其它项 */
    private suspend fun runCheck(
        results: ConcurrentHashMap<String, JSONObject>,
        key: String,
        body: suspend () -> Pair<String, String>
    ) {
        val title = titleMap[key] ?: key
        val card = try {
            val (status, detail) = body()
            JSONObject().put("key", key).put("title", title)
                .put("status", status).put("detail", detail)
        } catch (e: Exception) {
            JSONObject().put("key", key).put("title", title)
                .put("status", "warn").put("detail", "检测执行异常：${e.message}")
        }
        results[key] = card
        Events.post("checkDone", mapOf("check" to card))
    }

    // ---------- 各检测项 ----------

    private fun checkConnection(
        ctx: Context,
        internet: NetChecks.InternetState
    ): Pair<String, String> {
        val s = NetChecks.connectionState(ctx)
        if (s.status != "ok") return Pair(s.status, s.detail)
        // 移动数据劫持提示已独立为顶部警告条，不塞进本卡片，避免"绿色对勾+警告文字"误判。
        // 能否上互联网只认应用层验证（204/HTTPS）：未认证时网关会 ACK 任意 IP 的
        // 80 端口连接，TCP 握手成功不代表能上网，旧逻辑因此把未登录报成"通过"。
        return if (internet.ok) {
            Pair("ok", "${s.detail}；互联网访问正常（${internet.via}）")
        } else {
            Pair("warn", "${s.detail}；但实测无法访问互联网。${internet.detail}")
        }
    }

    private fun checkWifi(ctx: Context, cfg: JSONObject): Pair<String, String> {
        val (ssid, detail) = NetChecks.wifiSsid(ctx)
        if (ssid.isEmpty()) return Pair("skip", detail)
        // 是否校园网以"能否连通校园网网关"为准，避免连了任意 WiFi 都判为通过
        val gateway = cfg.optString("gateway")
        // TCP 回退优先绑定 WiFi 网络：移动数据劫持时默认路由走流量，
        // 未绑定的 tcpProbe 到校园网关必然超时
        val gwTcpOk = NetChecks.wifiNetwork(ctx)?.let {
            NetChecks.tcpProbeOnNetwork(it, gateway, 80)
        } ?: Ping.tcpProbe(gateway, 80)
        val gwReachable = Ping.ping(gateway, 2, 2).ok || gwTcpOk
        val keyword = cfg.optString("wifi_keyword", "DORM").uppercase()
        val isCampusSsid = keyword.isNotEmpty() && ssid.uppercase().contains(keyword)
        return when {
            gwReachable && isCampusSsid ->
                Pair("ok", "已连接校园网 SSID：$ssid（含关键字 $keyword，网关可达）")
            gwReachable ->
                Pair("ok", "已连接：$ssid（网关可达，疑似校园网）")
            isCampusSsid ->
                Pair("warn", "已连接 $ssid（含校园网关键字但网关不可达，可能未认证或信号异常）")
            else ->
                Pair("warn", "已连接：$ssid（不是校园网 WiFi）")
        }
    }

    /**
     * WiFi 信号强度检测：校园网一般每间宿舍部署一个 AP，信号弱说明连到隔壁宿舍 AP。
     *
     * Android 的 rssi 单位是 dBm，通常范围 -40（极好）到 -100（极差）。
     * - ≥-60：信号良好，连接的是附近 AP
     * - -60~-75：信号一般，可能离 AP 较远
     * - <-75：信号弱，很可能连到隔壁宿舍或更远的 AP
     */
    private fun checkSignal(ctx: Context): Pair<String, String> {
        val (_, rssi, detail) = NetChecks.wifiSsidAndRssi(ctx)
        if (rssi == Int.MIN_VALUE) return Pair("skip", detail)
        return when {
            rssi >= -60 -> Pair("ok", "信号良好（$rssi dBm），连接的是附近 AP")
            rssi >= -75 -> Pair(
                "warn",
                "信号一般（$rssi dBm），可能离 AP 较远。本宿舍 AP 故障或过载时会导致此现象，" +
                    "信号弱可能引起网速慢、延迟高或掉线。建议检查本宿舍 AP 是否正常工作，" +
                    "可尝试关闭再开启 WiFi 重新连接最近的 AP"
            )
            else -> Pair(
                "warn",
                "信号较弱（$rssi dBm），连接的可能是远端 AP。很可能连接的是隔壁宿舍或更远的 AP，" +
                    "本宿舍 AP 可能故障或被关闭。建议尝试关闭 WiFi 再重新开启，让设备重新连接最近的 AP；" +
                    "如反复出现信号弱，请联系网络管理员检查本宿舍 AP"
            )
        }
    }

    private fun checkIntranet(ctx: Context, cfg: JSONObject): Pair<String, String> {
        // 预检：没拿到有效 IPv4 时 ping 网关必然失败，应短路给出明确诊断，
        // 而不是误报"非校园网环境"（与桌面版 core.py 的 IP 状态短路逻辑一致）
        if (!NetChecks.hasValidIpv4()) {
            return Pair(
                "fail",
                "本机未获取到 IPv4 地址，无法连通校园网网关。可能原因：WiFi 未连接/DHCP 未分配地址/网卡驱动异常。建议在「引导」页查看处理方法"
            )
        }
        val gateway = cfg.optString("gateway")
        val count = cfg.optInt("ping_count", 2)
        val timeout = cfg.optInt("ping_timeout", 2)
        val r = Ping.ping(gateway, count, timeout)
        if (r.ok) return Pair("ok", "网关 $gateway ${r.detail}")
        // ICMP 被禁时回退 TCP 探测（网关 80 端口）
        if (Ping.tcpProbe(gateway, 80)) {
            return Pair("ok", "网关 $gateway 可达（ICMP 被禁用，经 TCP 80 端口确认）")
        }
        // 关键:移动数据劫持场景下,系统默认路由走移动数据,ping 和默认 TCP 都到不了校园网网关。
        // 此时若能找到 WiFi Network,绑定到它做 TCP 探测可以确认 WiFi 通道能否访问网关。
        // 这样就不会把"已连校园 WiFi + 开了移动数据"误判为"非校园网环境"。
        val wifiNet = NetChecks.wifiNetwork(ctx)
        if (wifiNet != null && NetChecks.tcpProbeOnNetwork(wifiNet, gateway, 80)) {
            return Pair(
                "ok",
                "网关 $gateway 经 WiFi 网络可达（系统默认走移动数据,但 WiFi 通道可达校园网关）。建议关闭移动数据后重新检测"
            )
        }
        val sysGw = NetChecks.gatewayIp(ctx)
        val note = if (sysGw.isNotEmpty() && sysGw != gateway) {
            "；本机当前网关为 $sysGw（与配置的 $gateway 不一致，如需检测其它网络请在设置中修改网关）"
        } else ""
        return Pair(
            "fail",
            "无法连通网关 $gateway（若当前不在校园网内属正常现象$note）"
        )
    }

    private fun checkExternal(
        ctx: Context,
        cfg: JSONObject,
        internet: NetChecks.InternetState
    ): Pair<String, String> {
        val host = cfg.optString("public_test_host")
        // ICMP 成功是可靠的联网证据；但移动数据劫持场景下 ping 走流量通道，
        // 会把"流量能上网"误判成"校园 WiFi 已通"，此时跳过默认路由的 ping，
        // 只认绑定 WiFi 的应用层验证结果
        if (!NetChecks.isCellularHijackingWifi(ctx)) {
            val count = cfg.optInt("ping_count", 2)
            val timeout = cfg.optInt("ping_timeout", 2)
            val r = Ping.ping(host, count, timeout)
            if (r.ok) return Pair("ok", "互联网可达（$host ${r.detail}）")
        }
        // ICMP 不通时绝不能用裸 TCP 80 握手兜底：未认证网关会透明劫持 80 端口，
        // 对任意 IP 的连接都 ACK，旧逻辑因此把未登录报成"互联网可达"。
        // 改用真实 HTTP 204 / HTTPS 证书验证（已绑定 WiFi 网络）。
        return if (internet.ok) {
            Pair("ok", "互联网可达（${internet.via}，ICMP 可能被禁）")
        } else {
            Pair("fail", "无法访问互联网：${internet.detail}")
        }
    }

    private fun checkAuth(cfg: JSONObject, results: ConcurrentHashMap<String, JSONObject>): Pair<String, String> {
        // 非校园网或没拿到 IP 时直接跳过认证检测，避免 4 秒超时浪费
        val gwOk = results["intranet"]?.optString("status") == "ok"
        // linklocal 对 169.254（DHCP 失败）返回 warn、对完全无 IPv4 返回 fail，
        // 两种情况都访问不到认证服务器，统一视为"未获取到 IP"
        val llStatus = results["linklocal"]?.optString("status")
        val noIp = llStatus == "fail" || llStatus == "warn"
        if (noIp) return Pair("skip", "本机未获取到有效 IP，无法检测认证状态")
        if (!gwOk) return Pair("skip", "校园网网关不可达，认证检测已跳过（当前可能不在校园网内）")
        // 把 ctx 传给 Drcom,让它在移动数据劫持场景下绑定 WiFi Network 发请求
        val st = Drcom.checkStatus(cfg, ctx = ctx)
        if (!st.reachable) {
            return Pair("skip", "认证服务器不可达（当前可能不在校园网内，已跳过）")
        }
        return when (st.online) {
            true -> {
                val who = if (st.account.isNotEmpty()) {
                    if (st.carrier.isNotEmpty()) "（${st.account}@${st.carrier}）" else "（${st.account}）"
                } else ""
                Pair("ok", "已认证$who")
            }
            false -> Pair("fail", "校园网已连接但未认证，请在「登录」页完成认证")
            null -> Pair("warn", "无法确定认证状态（${st.message.ifEmpty { "服务器响应未包含在线标志" }}）")
        }
    }

    private fun checkDns(
        cfg: JSONObject,
        internet: NetChecks.InternetState
    ): Pair<String, String> {
        // 关键：DNS“能解析”不等于“能上网”。校园网未认证时网关的 DNS 仍然
        // 会应答（甚至代答），InetAddress.getByName 照样返回真实 IP，旧逻辑
        // 据此把未登录场景报成“域名解析通过”。必须结合应用层联网验证解读：
        val domain = cfg.optString("test_domain")
        val ip = NetChecks.resolveIp(domain)
        return when {
            internet.ok && ip != null ->
                Pair("ok", "$domain 解析正常 → $ip，网站可实际访问")
            internet.ok ->
                Pair(
                    "fail",
                    "互联网可达但无法解析 $domain（DNS 服务异常，可尝试切换 DNS 或重启 WiFi）"
                )
            ip != null ->
                Pair(
                    "warn",
                    "$domain 能解析出 IP（$ip），但未认证时网关会代答 DNS，" +
                        "解析成功不代表能上网，请先完成校园网登录"
                )
            else ->
                Pair("skip", "无法解析域名（当前无法访问互联网，认证后再试）")
        }
    }

    private fun checkProxy(ctx: Context): Pair<String, String> = NetChecks.systemProxy(ctx)

    private fun checkLinkLocal(): Pair<String, String> = NetChecks.linkLocal()

    // ---------- 报告汇总 ----------

    private fun buildReport(
        results: ConcurrentHashMap<String, JSONObject>,
        cfg: JSONObject
    ): JSONObject {
        val checksArr = JSONArray()
        for ((key, _) in checkDefs) checksArr.put(results[key] ?: JSONObject())

        val connFail = results["connection"]?.optString("status") == "fail"
        val gwOk = results["intranet"]?.optString("status") == "ok"
        val gwFail = results["intranet"]?.optString("status") == "fail"
        // 169.254（DHCP 失败）linklocal 返回 warn、完全无 IPv4 返回 fail。
        // 连着校园 WiFi 但 DHCP 失败是校园网内极常见故障，此时网关必然 ping 不通，
        // 若只认 fail 会把 warn 漏判成"非校园网"，错误显示红色警告并停用登录，
        // 因此两种状态都归入"未获取到 IP"
        val llStatus = results["linklocal"]?.optString("status")
        val linkLocalBad = llStatus == "fail" || llStatus == "warn"
        val extOk = results["external"]?.optString("status") == "ok"
        // 没拿到 IP 时不应判为"非校园网"，应判为"无 IP"独立状态
        val noIp = linkLocalBad && !gwOk
        // 移动数据劫持场景:WiFi 已连但流量被移动数据劫持。
        // 此时 intranet 检测通过(绑定 WiFi 探测成功) → gwOk=true → 不会误判为非校园网。
        // 但若 WiFi 通道也访问不到网关(真不在校园网),仍应判为 nonCampus。
        val nonCampus = !connFail && !gwOk && !noIp
        val failCount = results.values.count { it.optString("status") == "fail" }
        val warnCount = results.values.count { it.optString("status") == "warn" }

        val state = when {
            connFail -> "nonet"
            noIp -> "noip"
            nonCampus -> "noncampus"
            !extOk -> "unauth"
            failCount > 0 -> "bad"
            else -> "ok"
        }
        val summary = when (state) {
            "nonet" -> "当前无网络连接"
            "noip" -> "本机未获取到 IPv4 地址（DHCP 失败或网卡未连接）"
            "noncampus" -> "当前不在校园网环境（无法连通校园网网关）"
            "unauth" -> "校园网已连接，但尚未认证上网"
            "bad" -> "可上网，但发现 $failCount 个问题需要关注"
            else -> if (warnCount > 0) "一切正常（另有 $warnCount 项提醒）" else "一切正常，校园网认证有效"
        }

        // 移动数据劫持 WiFi 检测:独立于 9 项检测,作为顶部警告条展示。
        // 不放进 checkConnection 卡片,避免"绿色对勾+警告文字"造成误判。
        val cellularHijack = NetChecks.isCellularHijackingWifi(ctx)

        return JSONObject()
            .put("ok", state == "ok")
            .put("state", state)
            .put("summary", summary)
            .put("non_campus", nonCampus)
            .put("no_ip", noIp)
            .put("cellular_hijack", cellularHijack)
            .put("gateway_reachable", gwOk)
            .put("fail_count", failCount)
            .put("warn_count", warnCount)
            .put("gateway", cfg.optString("gateway"))
            .put("checks", checksArr)
    }

    // ---------- 认证登录 ----------

    /** 登录校园网。结果通过 loginResult 事件推送（reqId 与请求配对） */
    fun login(reqId: Int, account: String, carrier: String, password: String) {
        scope.launch {
            try {
                val cfg = ConfigStore.load(ctx)
                val carrierName = carrierName(carrier)
                Events.post("log", mapOf("text" to "正在通过${carrierName}线路登录（账号 $account）…"))

                // 记住账号/运营商/密码（记住密码开启时才存密码，与桌面版行为一致）
                val patch = mutableMapOf<String, Any>(
                    "last_account" to account,
                    "carrier" to carrier
                )
                if (cfg.optBoolean("remember_password")) patch["saved_password"] = password
                ConfigStore.patch(ctx, patch)

                val r = Drcom.login(cfg, account, carrier, password, ctx = ctx)
                if (r.ok) {
                    Events.post("log", mapOf("text" to "登录成功，正在复核认证状态…"))
                    val st = Drcom.checkStatus(cfg, ctx = ctx)
                    if (st.reachable && st.online == false) {
                        Events.post(
                            "log",
                            mapOf("text" to "提示：服务器显示仍未在线，可稍后在「检测」页重新诊断确认")
                        )
                    }
                } else {
                    Events.post("log", mapOf("text" to "登录失败：${r.message}"))
                }
                Events.post(
                    "loginResult",
                    mapOf(
                        "reqId" to reqId,
                        "ok" to r.ok,
                        "message" to r.message,
                        "account" to account,
                        "carrier" to carrier
                    )
                )
            } catch (e: Exception) {
                Events.post(
                    "loginResult",
                    mapOf(
                        "reqId" to reqId,
                        "ok" to false,
                        "message" to "登录过程出现异常：${e.message}",
                        "account" to account,
                        "carrier" to carrier
                    )
                )
            }
        }
    }

    /** 单独刷新认证状态（登录页/检测页复用） */
    fun checkAuthStatus(reqId: Int) {
        scope.launch {
            try {
                val cfg = ConfigStore.load(ctx)
                val st = Drcom.checkStatus(cfg, ctx = ctx)
                Events.post(
                    "authStatus",
                    mapOf(
                        "reqId" to reqId,
                        "reachable" to st.reachable,
                        "online" to st.online,
                        "account" to st.account,
                        "carrier" to st.carrier,
                        "message" to st.message
                    )
                )
            } catch (e: Exception) {
                Events.post(
                    "authStatus",
                    mapOf(
                        "reqId" to reqId,
                        "reachable" to false,
                        "online" to JSONObject.NULL,
                        "account" to "",
                        "carrier" to "",
                        "message" to "查询异常：${e.message}"
                    )
                )
            }
        }
    }

    private fun carrierName(code: String): String = when (code) {
        "cmcc" -> "中国移动"
        "ctcc" -> "中国电信"
        "cucc" -> "中国联通"
        else -> code
    }
}
