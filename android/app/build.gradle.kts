import java.util.Properties

// 签名配置：存在 keystore.properties 时用于 release，否则回退 debug 签名（便于先出测试包）
val keystoreProps = Properties()
val keystorePropsFile = rootProject.file("keystore.properties")
val hasReleaseKeystore = keystorePropsFile.exists()
if (hasReleaseKeystore) {
    keystorePropsFile.inputStream().use { keystoreProps.load(it) }
}

plugins {
    id("com.android.application")
}

android {
    namespace = "com.campus.detector"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.campus.detector"
        minSdk = 29
        targetSdk = 37
        versionCode = 3
        versionName = "1.2.1"
    }

    if (hasReleaseKeystore) {
        signingConfigs {
            create("release") {
                storeFile = rootProject.file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
}
