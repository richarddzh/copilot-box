package com.github.richarddzh.copilotbox

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.util.UUID

const val PROTOCOL_VERSION = "2026-07-02"

data class BrokerWorker(
    val workerId: String,
    val displayName: String,
    val allowedWorkDirs: List<String>,
    val busy: Boolean,
) {
    override fun toString(): String = if (displayName == workerId) workerId else "$displayName ($workerId)"
}

data class AgentFinal(
    val status: String,
    val sessionId: String?,
    val output: String,
    val reportPath: String?,
) {
    companion object {
        fun fromPayload(payload: JSONObject): AgentFinal =
            AgentFinal(
                status = payload.optString("status"),
                sessionId = payload.optionalString("sessionId"),
                output = payload.optString("output"),
                reportPath = payload.optionalString("reportPath"),
            )
    }
}

data class ReportContent(
    val path: String,
    val contentType: String,
    val content: String,
) {
    companion object {
        fun fromPayload(payload: JSONObject): ReportContent =
            ReportContent(
                path = payload.optString("path"),
                contentType = payload.optString("contentType", "text/plain"),
                content = payload.optString("content"),
            )
    }
}

data class BrokerError(
    val code: String,
    val message: String,
    val retryable: Boolean,
) {
    companion object {
        fun fromPayload(payload: JSONObject): BrokerError =
            BrokerError(
                code = payload.optString("code"),
                message = payload.optString("message"),
                retryable = payload.optBoolean("retryable", false),
            )
    }
}

fun parseWorkers(payload: JSONObject): List<BrokerWorker> {
    val workers = payload.optJSONArray("availableWorkers") ?: JSONArray()
    return buildList {
        for (index in 0 until workers.length()) {
            val worker = workers.getJSONObject(index)
            val workDirs = worker.optJSONArray("allowedWorkDirs") ?: JSONArray()
            add(
                BrokerWorker(
                    workerId = worker.getString("workerId"),
                    displayName = worker.optString("displayName", worker.getString("workerId")),
                    allowedWorkDirs = buildList {
                        for (dirIndex in 0 until workDirs.length()) {
                            add(workDirs.getString(dirIndex))
                        }
                    },
                    busy = worker.optBoolean("busy", false),
                ),
            )
        }
    }
}

fun clientHelloJson(): String =
    JSONObject()
        .put("type", "client.hello")
        .put("protocolVersion", PROTOCOL_VERSION)
        .put("messageId", "msg-${UUID.randomUUID()}")
        .put("clientId", "android-local")
        .put(
            "capabilities",
            JSONObject()
                .put("streaming", true)
                .put("chatUi", true)
                .put("markdown", true),
        )
        .toString()

private fun JSONObject.optionalString(name: String): String? {
    if (!has(name) || isNull(name)) {
        return null
    }
    val value = optString(name).trim()
    return value.ifBlank { null }
}

fun agentRequestJson(
    requestId: String,
    workerId: String,
    workDir: String,
    sessionMode: String,
    prompt: String,
): String =
    JSONObject()
        .put("type", "agent.request")
        .put("protocolVersion", PROTOCOL_VERSION)
        .put("messageId", "msg-${UUID.randomUUID()}")
        .put("requestId", requestId)
        .put("timestamp", Instant.now().toString())
        .put(
            "payload",
            JSONObject()
                .put("workerId", workerId)
                .put("workDir", workDir)
                .put(
                    "session",
                    JSONObject()
                        .put("mode", sessionMode)
                        .put("sessionId", JSONObject.NULL),
                )
                .put(
                    "agent",
                    JSONObject()
                        .put("prompt", prompt)
                        .put("model", JSONObject.NULL)
                        .put("timeoutSeconds", 120),
                ),
        )
        .toString()

fun reportReadJson(requestId: String, workerId: String, path: String): String =
    JSONObject()
        .put("type", "report.read")
        .put("protocolVersion", PROTOCOL_VERSION)
        .put("messageId", "msg-${UUID.randomUUID()}")
        .put("requestId", requestId)
        .put("timestamp", Instant.now().toString())
        .put(
            "payload",
            JSONObject()
                .put("workerId", workerId)
                .put("path", path),
        )
        .toString()
