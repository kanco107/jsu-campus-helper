package com.campus.detector

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.provider.Settings
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.net.Socket
import java.net.URL

/**
 * 基于 Java API 的检测项：连接状态、SSID、DNS、系统代理、169.254。
 * （ping 类检测在 Ping.kt，HTTP 类在 Drcom.kt）
 */
object NetChecks {

    data class ConnState(val status: String, val detail: String, val onWifi: Boolean)

    /**
     * 网络连接状态：是否有网、走的是什么通道。
     *
     * 关键场景：用户连校园 WiFi（未认证）+ 同时开了移动数据。
     * 此时系统 activeNetwork 默认是移动数据（因 WiFi 未 validated），
     * 所有流量走移动数据通道,导致校园网网关 ping 失败 → 误判为"非校园网"。
     * 这种情况返回 status=ok 但 detail 显式标注"流量可能走移动数据",
     * 上层 Engine 据此调整判定逻辑。
     */
    fun connectionState(ctx: Context): ConnState {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val activeNet = cm.activeNetwork ?: return ConnState("fail", "当前无任何网络连接（未连 WiFi 也没有移动数据）", false)
        val caps = cm.getNetworkCapabilities(activeNet)
            ?: return ConnState("fail", "当前无任何网络连接（未连 WiFi 也没有移动数据）", false)
        // getNetworkCapabilities 返回可空类型,上面 elvis 已过滤 null,这里安全解引用
        val wifi = caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        val cell = caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)
        val validated = caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
        // WiFi 已连但未通过网络验证 + 同时有移动数据 → 系统默认走移动数据
        // 这是校园网未认证 + 移动数据同时开启的典型场景
        val wifiUnvalidated = wifi && !validated
        val trafficOnCell = wifiUnvalidated && cell
        val via = when {
            trafficOnCell -> "WiFi（未认证）+ 移动数据，流量走移动数据"
            wifi && cell -> "WiFi + 移动数据同时在线"
            wifi -> "WiFi"
            cell -> "移动数据"
            else -> "其他网络"
        }
        val extra = if (validated) "" else "，系统标记网络受限"
        return ConnState("ok", "已连接（$via$extra）", wifi)
    }

    /**
     * 检测当前是否处于"WiFi 已连但流量被移动数据劫持"状态。
     * 返回 true 时表示检测/认证请求必须显式绑定 WiFi 网络,否则到不了校园网。
     */
    fun isCellularHijackingWifi(ctx: Context): Boolean {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val activeNet = cm.activeNetwork ?: return false
        val caps = cm.getNetworkCapabilities(activeNet) ?: return false
        // activeNetwork 是移动数据 + 存在 WiFi 网络(可能未 validated)
        if (!caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) return false
        return cm.allNetworks.any { n ->
            val c = cm.getNetworkCapabilities(n)
            c != null && c.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
        }
    }

    /**
     * 找到当前可用的 WiFi Network 对象。
     * 用于绑定到 WiFi 网络做探测/认证请求,绕过系统默认路由(可能走移动数据)。
     */
    fun wifiNetwork(ctx: Context): Network? {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        // allNetworks 比 activeNetwork 更全面：未 validated 的 WiFi 也能找到
        for (n in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(n) ?: continue
            if (caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) &&
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)) {
                return n
            }
        }
        return null
    }

    /**
     * 绑定到指定 Network 的 TCP 探测：用 Network.getSocketFactory()
     * 创建 Socket,流量一定走该网络,不会被系统默认路由劫持。
     *
     * Android 5.0+(API 23+) 支持 Network.openConnection / SocketFactory,
     * 本应用 minSdk=29,可放心使用。
     */
    fun tcpProbeOnNetwork(network: Network, host: String, port: Int,
                           timeoutMs: Int = 2000): Boolean {
        return try {
            val factory = network.socketFactory
            val socket = factory.createSocket()
            socket.connect(InetSocketAddress(host, port), timeoutMs)
            socket.close()
            true
        } catch (_: Exception) {
            false
        }
    }

    /** 应用层互联网验证结果 */
    data class InternetState(
        val ok: Boolean,        // 是否真的能上互联网
        val via: String,        // 成功时的验证方式
        val detail: String,     // 给用户看的结论/证据
        val portal: Boolean     // 是否明确收到认证门户的劫持响应
    )

    // 国内厂商的联网检测地址：正常网络返回 HTTP 204；
    // 未认证时校园网门户会透明劫持 80 端口，返回 200 认证页或 302 跳转到网关 IP。
    // 不能用 Google 的 connectivitycheck（国内正常网络也访问不通，会误报）。
    private val HTTP_204_ENDPOINTS = listOf(
        "http://connect.rom.miui.com/generate_204",
        "http://connectivitycheck.platform.hicloud.com/generate_204",
        "http://www.qualcomm.cn/generate_204",
        "http://wifi.vivo.com.cn/generate_204"
    )

    // HTTPS 兜底：认证门户无法伪造目标网站的 TLS 证书，握手能成功且响应正常
    // 就证明端到端互联网是通的（TCP 能连上 + 收到非预期 HTTP 都不算数）。
    private val HTTPS_ENDPOINTS = listOf(
        "https://www.baidu.com/",
        "https://www.qq.com/"
    )

    private const val PROBE_UA =
        "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"

    private sealed class Probe {
        object Ok : Probe()
        data class Portal(val evidence: String) : Probe()
        data class Error(val message: String) : Probe()
    }

    /**
     * 应用层互联网验证（绑定 WiFi 网络）。
     *
     * 为什么不能用 TCP 握手判断：校园网未认证时，网关为了把浏览器弹到认证页，
     * 会透明劫持 80 端口——对任意 IP 发 SYN 都会被网关 ACK，Socket.connect
     * 成功只代表"被门户劫持了"，不代表能上网。必须发起真实 HTTP 请求并校验
     * 响应（204），或用无法被伪造证书的 HTTPS 验证。
     */
    fun checkInternet(ctx: Context): InternetState {
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        // 必须绑定 WiFi 网络：未认证 WiFi + 移动数据同时在线时默认路由走流量，
        // 不绑定会把"移动数据能上网"误判成"校园 WiFi 能上网"
        val net = wifiNetwork(ctx) ?: cm.activeNetwork
            ?: return InternetState(false, "", "当前没有任何可用网络连接", false)

        var portalHint = ""
        var lastErr = ""
        for (url in HTTP_204_ENDPOINTS) {
            when (val r = http204Probe(net, url)) {
                is Probe.Ok -> return InternetState(true, "HTTP 联网验证", "$url 正常返回 204", false)
                is Probe.Portal -> {
                    if (portalHint.isEmpty()) portalHint = r.evidence
                    lastErr = r.evidence
                }
                is Probe.Error -> lastErr = r.message
            }
        }
        for (url in HTTPS_ENDPOINTS) {
            if (httpsProbe(net, url)) {
                return InternetState(true, "HTTPS 加密验证", "$url 连接与证书校验正常", false)
            }
        }
        val detail = when {
            portalHint.isNotEmpty() ->
                "访问外网被劫持到认证页面（$portalHint），说明校园网尚未登录；" +
                    "注意“能连上端口/能解析域名”不代表能上网"
            lastErr.isNotEmpty() ->
                "所有 HTTP/HTTPS 联网探测均失败（$lastErr），请先完成校园网登录"
            else -> "无法访问互联网，请先完成校园网登录"
        }
        return InternetState(false, "", detail, portalHint.isNotEmpty())
    }

    /** 单个 204 探测：严格 204 才算通；200/3xx 视为门户劫持证据 */
    private fun http204Probe(net: Network, urlStr: String): Probe {
        var conn: HttpURLConnection? = null
        return try {
            conn = net.openConnection(URL(urlStr)) as HttpURLConnection
            conn.connectTimeout = 3000
            conn.readTimeout = 4000
            conn.instanceFollowRedirects = false // 不跟随跳转，302 到网关 IP 正是劫持铁证
            conn.setRequestProperty("User-Agent", PROBE_UA)
            when (val code = conn.responseCode) {
                204 -> Probe.Ok
                in 300..399 -> {
                    val loc = conn.getHeaderField("Location") ?: ""
                    Probe.Portal(if (loc.isNotEmpty()) "HTTP $code 跳转至 $loc" else "HTTP $code 重定向")
                }
                in 200..299 ->
                    Probe.Portal("HTTP $code：204 探测地址返回了网页内容，疑似认证页")
                else -> Probe.Error("HTTP $code")
            }
        } catch (e: Exception) {
            Probe.Error(e.message?.take(80) ?: "连接失败")
        } finally {
            conn?.disconnect()
        }
    }

    /** HTTPS 验证：默认 TLS 证书校验，门户伪造证书会直接握手失败 */
    private fun httpsProbe(net: Network, urlStr: String): Boolean {
        var conn: HttpURLConnection? = null
        return try {
            conn = net.openConnection(URL(urlStr)) as HttpURLConnection
            conn.connectTimeout = 4000
            conn.readTimeout = 5000
            conn.instanceFollowRedirects = true
            conn.setRequestProperty("User-Agent", PROBE_UA)
            conn.responseCode in 200..399
        } catch (_: Exception) {
            false
        } finally {
            conn?.disconnect()
        }
    }

    /** 仅做 DNS 解析并返回 IP（用于展示）；解析成功不代表能上网（网关可能代答） */
    fun resolveIp(domain: String): String? =
        try { InetAddress.getByName(domain).hostAddress } catch (_: Exception) { null }

    /** 当前 WiFi 的网关地址（取默认路由的网关，用于与配置网关比对） */
    fun gatewayIp(ctx: Context): String {
        return try {
            val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            val lp = cm.activeNetwork?.let { cm.getLinkProperties(it) } ?: return ""
            lp.routes.firstOrNull { it.isDefaultRoute }?.gateway?.hostAddress ?: ""
        } catch (_: Exception) {
            ""
        }
    }

    /**
     * WiFi SSID 和信号强度（best-effort）：Android 10+ 需要定位权限且系统定位开启，
     * 拿不到时返回空串，不影响其它检测。
     *
     * @return (ssid, rssiDbm) rssi 为 Int.MIN_VALUE 表示无法读取
     */
    fun wifiSsidAndRssi(ctx: Context): Triple<String, Int, String> {
        return try {
            val wm = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            val info = wm.connectionInfo
            val raw = info?.ssid ?: ""
            val rssi = info?.rssi ?: Int.MIN_VALUE
            if (raw.isEmpty() || raw == "<unknown ssid>" || raw == "0x") {
                Triple("", Int.MIN_VALUE, "无法读取 SSID（需授予定位权限并开启系统定位；不影响其它检测项）")
            } else {
                Triple(raw.trim('"'), rssi, "当前已连接")
            }
        } catch (e: Exception) {
            Triple("", Int.MIN_VALUE, "读取失败：${e.message}")
        }
    }

    /** 兼容旧调用：只返回 ssid 和提示文本（信号强度丢失） */
    fun wifiSsid(ctx: Context): Pair<String, String> {
        val (ssid, _, detail) = wifiSsidAndRssi(ctx)
        return Pair(ssid, detail)
    }

    /** DNS 解析检测 */
    fun dnsResolve(domain: String): Pair<String, String> {
        return try {
            val addr = InetAddress.getByName(domain)
            Pair("ok", "$domain 解析正常 → ${addr.hostAddress}")
        } catch (_: Exception) {
            Pair("fail", "无法解析 $domain（DNS 服务异常或当前无网络；登录成功但网页打不开多与此有关）")
        }
    }

    /**
     * 代理检测（多维度）：v2rayNG/Clash 等走 VPN 通道的代理软件
     * 不会被 Settings.Global.HTTP_PROXY 反映，需结合多种手段检测。
     */
    fun systemProxy(ctx: Context): Pair<String, String> {
        val findings = mutableListOf<String>()

        // 1. 系统全局代理（旧式 HTTP 代理设置）
        val globalProxy = try {
            Settings.Global.getString(ctx.contentResolver, Settings.Global.HTTP_PROXY)
        } catch (_: Exception) { null }
        if (!globalProxy.isNullOrEmpty()) {
            findings.add("系统代理设置：$globalProxy")
        }

        // 2. JVM 代理属性（部分代理软件会设置）
        val jvmHost = System.getProperty("http.proxyHost")
        val jvmPort = System.getProperty("http.proxyPort")
        if (!jvmHost.isNullOrEmpty()) {
            findings.add("JVM 代理：$jvmHost:${jvmPort ?: "80"}")
        }

        // 3. VPN 通道检测（v2rayNG/Clash/Shadowsocks 等核心特征）
        //    这类软件通过 VpnService 创建 tun0 虚拟网卡，不会写入 HTTP_PROXY
        val cm = ctx.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val activeNet = cm.activeNetwork
        if (activeNet != null) {
            val caps = cm.getNetworkCapabilities(activeNet)
            if (caps != null && caps.hasTransport(NetworkCapabilities.TRANSPORT_VPN)) {
                findings.add("检测到 VPN 通道（可能是 v2rayNG/Clash 等代理软件）")
            }
        }

        // 4. VPN 虚拟网卡检测（tun0/tap0/vpn0）
        //    即使 VPN 通道被杀，残留的虚拟网卡仍说明有代理软件运行过。
        //    注意：不要把 ppp 列入——ppp0 是部分机型移动数据（4G/5G）的接口名，
        //    不是 VPN，列入会导致所有移动数据用户被误报"检测到代理"。
        try {
            val ifaces = NetworkInterface.getNetworkInterfaces()
            if (ifaces != null) {
                val vpnNames = listOf("tun", "tap", "vpn")
                for (nif in ifaces) {
                    if (!nif.isUp) continue
                    val name = nif.name.lowercase()
                    if (vpnNames.any { name.startsWith(it) }) {
                        findings.add("发现 VPN 虚拟网卡：${nif.name}")
                        break
                    }
                }
            }
        } catch (_: Exception) { }

        return if (findings.isEmpty()) {
            Pair("ok", "未检测到代理/VPN")
        } else {
            Pair("warn", findings.joinToString("；") + "。代理软件可能导致校园网认证异常或网页被拦截，建议在「引导」页查看关闭方法")
        }
    }

    /** 169.254 链路本地地址检测（DHCP 失败征兆） */
    fun linkLocal(): Pair<String, String> {
        val badIfaces = mutableListOf<String>()
        val ips = mutableListOf<String>()
        val ifaces = NetworkInterface.getNetworkInterfaces() ?: return Pair("skip", "无法枚举网络接口")
        for (nif in ifaces) {
            if (!nif.isUp) continue
            for (ia in nif.interfaceAddresses) {
                val a = ia.address?.hostAddress ?: continue
                if (a.contains(':')) continue // 跳过 IPv6
                if (a.startsWith("169.254.")) badIfaces.add(nif.name) else ips.add(a)
            }
        }
        return if (badIfaces.isNotEmpty()) {
            Pair(
                "warn",
                "${badIfaces.distinct().joinToString("、")} 获取到 169.254.x.x 链路本地地址（DHCP 获取失败征兆），建议在引导页查看处理方法"
            )
        } else if (ips.isEmpty()) {
            // 没拿到任何 IPv4（连 169.254 都没有），说明网卡未连接或驱动异常
            Pair("fail", "未获取到 IPv4 地址（网卡未连接或驱动异常，无法进行网络检测）")
        } else {
            Pair("ok", "本机 IPv4：${ips.distinct().take(3).joinToString("、")}")
        }
    }

    /**
     * 查询本机是否拿到有效的 IPv4 地址（非 169.254 链路本地地址）。
     * 用于 ping 网关前的预检：没有 IP 时 ping 必然失败，应短路给出明确诊断
     * 而不是误报"非校园网环境"。
     */
    fun hasValidIpv4(): Boolean {
        return try {
            val ifaces = NetworkInterface.getNetworkInterfaces() ?: return false
            for (nif in ifaces) {
                if (!nif.isUp) continue
                for (ia in nif.interfaceAddresses) {
                    val a = ia.address?.hostAddress ?: continue
                    if (a.contains(':')) continue
                    if (!a.startsWith("169.254.") && a != "127.0.0.1") return true
                }
            }
            false
        } catch (_: Exception) {
            false
        }
    }
}
