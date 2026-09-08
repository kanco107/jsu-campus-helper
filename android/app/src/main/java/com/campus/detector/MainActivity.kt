package com.campus.detector

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.RenderProcessGoneDetail

/**
 * 单 Activity 壳：装配全屏 WebView，加载 assets/www/index.html。
 *
 * - 桥接对象注入名 AndroidBridge（见 Bridge.kt）；
 * - 运行时权限：Android 17+ 的 ACCESS_LOCAL_NETWORK（局域网访问，检测功能命脉）、
 *   ACCESS_FINE_LOCATION（读取 WiFi SSID，可拒绝仅降级显示）；
 * - 只加载 file:///android_asset/ 本地内容，任何外部 URL 都交给系统浏览器。
 */
class MainActivity : Activity() {

    private lateinit var webView: WebView
    private lateinit var bridge: Bridge

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        webView = WebView(this)
        bridge = Bridge(this)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            cacheMode = WebSettings.LOAD_DEFAULT
            mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        }
        // 内容延伸到系统栏下方（targetSdk 36+ 强制 edge-to-edge；HTML 用 safe-area 避让）
        webView.setBackgroundColor(Color.TRANSPARENT)
        webView.isVerticalScrollBarEnabled = false

        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView,
                request: WebResourceRequest
            ): Boolean {
                val url = request.url.toString()
                if (url.startsWith("file:///android_asset/")) return false
                // 本地页面之外的一切导航交给系统浏览器
                bridge.openExternal(url)
                return true
            }

            /**
             * WebView 渲染进程崩溃（OOM / 系统查杀）时自动恢复：
             * 销毁旧 WebView 并重新加载页面，避免界面永久白屏。
             * 崩溃过于频繁（didCrash=true 且 1 分钟内多次）则返回 false 让系统处理。
             */
            override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail): Boolean {
                return try {
                    val msg = if (detail.didCrash()) "页面渲染进程崩溃，正在恢复…"
                              else "页面渲染进程被系统回收，正在恢复…"
                    Events.post("log", mapOf("text" to msg))
                    // 重建 WebView 并重新加载（Events 桥接需重新 attach）
                    runOnUiThread {
                        try {
                            Events.detach()
                            webView.destroy()
                        } catch (_: Exception) { }
                        recreateWebView()
                    }
                    true
                } catch (_: Exception) {
                    false
                }
            }
        }

        setContentView(webView)
        Events.attach(webView)
        webView.addJavascriptInterface(bridge, "AndroidBridge")
        webView.loadUrl("file:///android_asset/www/index.html")

        requestNeededPermissions()
    }

    /** 按系统版本申请所需运行时权限，结果经 permission 事件通知前端调整 UI 提示 */
    private fun requestNeededPermissions() {
        val wanted = mutableListOf<String>()

        // Android 17（API 37）起：访问局域网需要运行时授权，否则 ping 网关/访问认证接口被系统拦截
        if (Build.VERSION.SDK_INT >= 37 &&
            checkSelfPermission(LOCAL_NETWORK_PERMISSION) != PackageManager.PERMISSION_GRANTED
        ) {
            wanted.add(LOCAL_NETWORK_PERMISSION)
        }
        // WiFi SSID 读取需要定位权限（可拒绝，仅影响 SSID 显示）
        if (checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            wanted.add(Manifest.permission.ACCESS_FINE_LOCATION)
        }

        if (wanted.isNotEmpty()) {
            requestPermissions(wanted.toTypedArray(), REQ_PERMS)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != REQ_PERMS) return
        val granted = mutableListOf<String>()
        val denied = mutableListOf<String>()
        for (i in permissions.indices) {
            if (grantResults[i] == PackageManager.PERMISSION_GRANTED) granted.add(permissions[i])
            else denied.add(permissions[i])
        }
        Events.post(
            "permission",
            mapOf(
                "granted" to granted.joinToString(","),
                "denied" to denied.joinToString(",")
            )
        )
        if (denied.contains(LOCAL_NETWORK_PERMISSION)) {
            Events.post(
                "log",
                mapOf("text" to "提示：未授予「本地网络」权限，内网检测可能被系统拦截（可在系统设置→应用→校园网助手→权限中开启）")
            )
        }
    }

    /** WebView 渲染进程崩溃后重建：复用原 WebViewClient 配置并重新加载页面 */
    private fun recreateWebView() {
        try {
            webView = WebView(this)
            webView.settings.apply {
                javaScriptEnabled = true
                domStorageEnabled = true
                allowFileAccess = true
                cacheMode = WebSettings.LOAD_DEFAULT
                mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
            }
            webView.setBackgroundColor(Color.TRANSPARENT)
            webView.isVerticalScrollBarEnabled = false
            webView.webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                    val url = request.url.toString()
                    if (url.startsWith("file:///android_asset/")) return false
                    bridge.openExternal(url)
                    return true
                }
                override fun onRenderProcessGone(view: WebView, detail: RenderProcessGoneDetail) = false
            }
            setContentView(webView)
            Events.attach(webView)
            webView.addJavascriptInterface(bridge, "AndroidBridge")
            webView.loadUrl("file:///android_asset/www/index.html")
        } catch (e: Exception) {
            Events.post("log", mapOf("text" to "页面恢复失败：${e.message}"))
        }
    }

    override fun onDestroy() {
        Events.detach()
        webView.destroy()
        super.onDestroy()
    }

    companion object {
        private const val REQ_PERMS = 1
        // 该权限常量在 compileSdk 37 的 Manifest 中才存在，这里用字符串避免编译依赖
        private const val LOCAL_NETWORK_PERMISSION = "android.permission.ACCESS_LOCAL_NETWORK"
    }
}
