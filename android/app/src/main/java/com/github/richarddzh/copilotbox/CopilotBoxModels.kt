package com.github.richarddzh.copilotbox

import org.json.JSONObject
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.UUID

data class CopilotBoxRequest(
    val requestId: String,
    val requestBlobName: String,
    val responsePrefix: String,
    val json: String,
)

object CopilotBoxRequestFactory {
    private val blobTimestampFormatter: DateTimeFormatter =
        DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmssSSS'Z'").withZone(ZoneOffset.UTC)

    fun create(
        requestPrefix: String,
        workDir: String,
        prompt: String,
        sessionMode: String,
        sessionId: String?,
    ): CopilotBoxRequest {
        val id = "android-${UUID.randomUUID()}"
        val timestamp = blobTimestampFormatter.format(Instant.now())
        val normalizedPrefix = requestPrefix.trim('/').let {
            if (it.isBlank()) "" else "$it/"
        }
        val baseName = "$normalizedPrefix$timestamp-$id"
        val responsePrefix = baseName
        val requestJson = JSONObject()
            .put("protocolVersion", "2026-07-02")
            .put("requestId", id)
            .put("createdAt", Instant.now().toString())
            .put(
                "client",
                JSONObject()
                    .put("type", "android")
                    .put("userId", "android-local"),
            )
            .put("workDir", workDir)
            .put(
                "session",
                JSONObject()
                    .put("mode", sessionMode)
                    .put("sessionId", sessionId),
            )
            .put(
                "agent",
                JSONObject()
                    .put("prompt", prompt)
                    .put("model", JSONObject.NULL)
                    .put("timeoutSeconds", 120),
            )
            .put(
                "response",
                JSONObject()
                    .put("prefix", responsePrefix),
            )
            .toString(2)

        return CopilotBoxRequest(
            requestId = id,
            requestBlobName = "$baseName.json",
            responsePrefix = responsePrefix,
            json = requestJson,
        )
    }
}

data class FinalResponse(
    val status: String,
    val sessionId: String?,
    val output: String?,
    val error: String?,
) {
    companion object {
        fun parse(json: String): FinalResponse {
            val obj = JSONObject(json)
            val error = obj.optJSONObject("error")?.optString("message")
            return FinalResponse(
                status = obj.optString("status"),
                sessionId = obj.optString("sessionId").ifBlank { null },
                output = obj.optString("output").ifBlank { null },
                error = error?.ifBlank { null },
            )
        }
    }
}
