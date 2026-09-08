package com.campus.detector

import android.content.Context
import android.provider.Settings
import android.util.Base64
import org.json.JSONObject
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * 配置存储：SharedPreferences 里存一个 config JSON 对象。
 *
 * 键名与桌面版 config.json 完全一致，默认值照搬桌面版，
 * 便于两端配置语义对齐（gateway/status_url/login_url 等）。
 *
 * saved_password 以 AES 加密后存储（密钥派生自设备 ANDROID_ID），
 * 避免明文出现在 SharedPreferences / 备份中。密文以 "enc:" 前缀标识，
 * 旧版明文密码（无前缀）在加载时不处理，保存时会自动转为密文。
 */
object ConfigStore {
    private const val PREFS = "config"
    private const val KEY = "config_json"
    private const val ENC_PREFIX = "enc:"

    /** 默认配置（与桌面版 config.json 默认值一致；ping 超时改为移动端合适的 2 秒） */
    val defaults: Map<String, Any> = mapOf(
        "gateway" to "192.168.254.17",
        "status_url" to "http://192.168.254.17/drcom/chkstatus",
        "login_url" to "http://192.168.254.17/drcom/login",
        "portal_url" to "http://192.168.254.17/",
        "public_test_host" to "223.5.5.5",
        "test_domain" to "www.baidu.com",
        "carrier" to "cmcc",
        "wifi_keyword" to "DORM",
        "ping_count" to 2,
        "ping_timeout" to 2,
        "last_account" to "",
        "saved_password" to "",
        "remember_password" to false
    )

    /** 读取配置：存储值与默认值合并，保证所有键都存在（与桌面版 load_config 行为一致） */
    fun load(ctx: Context): JSONObject {
        val prefs = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val raw = prefs.getString(KEY, null)
        val obj = if (raw != null) {
            try {
                JSONObject(raw)
            } catch (_: Exception) {
                JSONObject()
            }
        } else {
            JSONObject()
        }
        for ((k, v) in defaults) if (!obj.has(k)) obj.put(k, v)
        // 解密已加密的 saved_password
        val pwd = obj.optString("saved_password", "")
        if (pwd.startsWith(ENC_PREFIX)) {
            obj.put("saved_password", decrypt(ctx, pwd.removePrefix(ENC_PREFIX)) ?: "")
        }
        return obj
    }

    /** 保存配置：只接受已知键，未知键忽略（防止前端乱写） */
    fun save(ctx: Context, json: String): Boolean {
        return try {
            val incoming = JSONObject(json)
            val merged = load(ctx)
            for (k in defaults.keys) {
                if (incoming.has(k)) {
                    var v = incoming.get(k)
                    // saved_password 加密存储
                    if (k == "saved_password" && v is String && v.isNotEmpty() && !v.startsWith(ENC_PREFIX)) {
                        v = ENC_PREFIX + encrypt(ctx, v)
                    }
                    merged.put(k, v)
                }
            }
            ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putString(KEY, merged.toString()).apply()
            true
        } catch (_: Exception) {
            false
        }
    }

    /** 内部使用：只更新部分键 */
    fun patch(ctx: Context, values: Map<String, Any>) {
        val merged = load(ctx)
        for ((k, v) in values) {
            var value = v
            if (k == "saved_password" && v is String && v.isNotEmpty() && !v.startsWith(ENC_PREFIX)) {
                value = ENC_PREFIX + encrypt(ctx, v)
            }
            merged.put(k, value)
        }
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit().putString(KEY, merged.toString()).apply()
    }

    // ---------- AES 加解密（密钥派生自设备 ANDROID_ID，无外部依赖） ----------

    private fun aesKey(ctx: Context): SecretKeySpec {
        val androidId = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID) ?: "jsu-campus-default"
        val digest = MessageDigest.getInstance("MD5").digest(androidId.toByteArray(Charsets.UTF_8))
        return SecretKeySpec(digest, "AES")
    }

    private fun encrypt(ctx: Context, plain: String): String {
        return try {
            val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
            cipher.init(Cipher.ENCRYPT_MODE, aesKey(ctx), IvParameterSpec(ByteArray(16)))
            val enc = cipher.doFinal(plain.toByteArray(Charsets.UTF_8))
            Base64.encodeToString(enc, Base64.NO_WRAP)
        } catch (_: Exception) {
            plain // 加密失败回退明文（极端情况，不阻塞登录流程）
        }
    }

    private fun decrypt(ctx: Context, cipherText: String): String? {
        return try {
            val cipher = Cipher.getInstance("AES/CBC/PKCS5Padding")
            cipher.init(Cipher.DECRYPT_MODE, aesKey(ctx), IvParameterSpec(ByteArray(16)))
            val dec = cipher.doFinal(Base64.decode(cipherText, Base64.NO_WRAP))
            String(dec, Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }
}
