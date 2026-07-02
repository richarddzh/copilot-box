plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
}

android {
    namespace = "com.github.richarddzh.copilotbox"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.github.richarddzh.copilotbox"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
}

dependencies {
    implementation(libs.okhttp)
}
