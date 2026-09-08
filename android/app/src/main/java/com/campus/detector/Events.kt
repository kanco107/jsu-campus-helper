package com.campus.detector

import android.os.Handler
import android.os.Looper
import android.webkit.WebView
import org.json.JSONObject
import java.util.concurrent.atomic.AtomicInteger

/**
 * Kotlin → JS 的统一事件出口。
 *
 * 所有事件都通过 evaluateJavascript 调用前端全局函数 window.__onEvent(payload)，
 * 与桌面版（pywebview 的 window.__onEvent）保持同一协议，前端事件分发逻辑可直接移植。
 *
 * 注意：evaluateJavascript 必须在主线程调用；@JavascriptInterface 方法与协程
 * 都运行在后台线程，因此统一 post 到主线程 Handler。
 */
object Events {
    private val main = Handler(Looper.getMainLooper())
    private var webView: WebView? = null
    private val reqCounter = AtomicInteger(0)

    fun attach(wv: WebView) {
        webView = wv
    }

    fun detach() {
        webView = null
    }

    /** 生成一个异步请求 ID（JS 侧用它把响应和请求配对） */
    fun nextReqId(): Int = reqCounter.incrementAndGet()

    /** 推送一条事件到前端。params 的值支持 String/Int/Boolean/JSONObject 等 */
    fun post(type: String, params: Map<String, Any?> = emptyMap()) {
        val wv = webView ?: return
        val json = JSONObject()
        json.put("type", type)
        for ((k, v) in params) {
            json.put(k, v ?: JSONObject.NULL)
        }
        val payload = json.toString()
        main.post {
            try {
                wv.evaluateJavascript("window.__onEvent($payload)", null)
            } catch (_: Exception) {
            }
        }
    }
}
