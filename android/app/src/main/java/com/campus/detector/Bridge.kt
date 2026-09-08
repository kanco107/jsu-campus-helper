package com.campus.detector

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.webkit.JavascriptInterface
import org.json.JSONObject

/**
 * JS ↔ Kotlin 的唯一边界（注入到 WebView 的对象名：AndroidBridge）。
 *
 * 约定：
 * - 快速/本地操作（读写配置）同步返回；
 * - 慢/网络操作立即返回 reqId，结果统一经 window.__onEvent({type, reqId, ...}) 异步推送
 *   （@JavascriptInterface 方法运行在 WebView 的 JavaBridge 线程，绝不能在这里做网络 IO）；
 * - 安全是底线：只暴露 @JavascriptInterface 注解的方法，WebView 只加载本地页面，
 *   打开外部网页一律经 openExternal 交给系统浏览器。
 */
class Bridge(private val activity: MainActivity) {

    private val engine by lazy { Engine(activity) }

    /** 触发全量检测（结果经 checksInit/checkDone/done 事件逐项推送） */
    @JavascriptInterface
    fun runDetection() {
        engine.runDetection()
    }

    /** 登录校园网，返回 reqId；结果经 loginResult 事件推送 */
    @JavascriptInterface
    fun login(account: String, carrier: String, password: String): Int {
        val reqId = Events.nextReqId()
        engine.login(reqId, account, carrier, password)
        return reqId
    }

    /** 刷新认证状态，返回 reqId；结果经 authStatus 事件推送 */
    @JavascriptInterface
    fun checkAuthStatus(): Int {
        val reqId = Events.nextReqId()
        engine.checkAuthStatus(reqId)
        return reqId
    }

    /** 读取配置（同步） */
    @JavascriptInterface
    fun getConfig(): String = ConfigStore.load(activity).toString()

    /** 保存配置（同步），只接受已知键 */
    @JavascriptInterface
    fun saveConfig(json: String): Boolean = ConfigStore.save(activity, json)

    /** 用系统浏览器打开外部网页（认证页等）；非 http(s) 一律忽略 */
    @JavascriptInterface
    fun openExternal(url: String) {
        try {
            val uri = Uri.parse(url)
            if (uri.scheme == "http" || uri.scheme == "https") {
                activity.startActivity(Intent(Intent.ACTION_VIEW, uri))
            }
        } catch (_: Exception) {
        }
    }

    /**
     * 跳转系统设置（修复引导用）：
     * wifi → WLAN 列表；proxy → 网络总设置（含 VPN/代理）；
     * app → 应用详情（给本应用网络权限）；cellular → 移动数据设置(关闭移动数据)
     */
    @JavascriptInterface
    fun openSystemSettings(target: String) {
        val action = when (target) {
            "wifi" -> Settings.ACTION_WIFI_SETTINGS
            "proxy" -> Settings.ACTION_WIRELESS_SETTINGS
            "app" -> Settings.ACTION_APPLICATION_DETAILS_SETTINGS
            // 移动数据开关在系统设置页有,跳到网络总设置让用户手动找到
            "cellular" -> Settings.ACTION_WIRELESS_SETTINGS
            else -> Settings.ACTION_SETTINGS
        }
        try {
            activity.startActivity(Intent(action).apply {
                if (target == "app") {
                    data = Uri.parse("package:${activity.packageName}")
                }
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            })
        } catch (_: Exception) {
            try {
                activity.startActivity(Intent(Settings.ACTION_SETTINGS))
            } catch (_: Exception) {
            }
        }
    }

    /** 版本与设备信息（设置页展示） */
    @JavascriptInterface
    fun getAppInfo(): String {
        val obj = JSONObject()
        try {
            val pi = activity.packageManager.getPackageInfo(activity.packageName, 0)
            obj.put("version", pi.versionName ?: "?")
        } catch (_: Exception) {
            obj.put("version", "?")
        }
        obj.put("apiLevel", Build.VERSION.SDK_INT)
        obj.put("androidVersion", Build.VERSION.RELEASE)
        obj.put("model", Build.MODEL ?: "")
        return obj.toString()
    }
}
