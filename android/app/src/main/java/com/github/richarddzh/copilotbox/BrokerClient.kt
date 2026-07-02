package com.github.richarddzh.copilotbox

import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

class BrokerClient(
    private val brokerUrl: String,
    private val token: String,
    private val listener: Listener,
    private val httpClient: OkHttpClient = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build(),
) {
    interface Listener {
        fun onConnected(workers: List<BrokerWorker>, activeSessions: List<ActiveSession>)
        fun onSessionSnapshot(requestId: String, snapshot: SessionSnapshot)
        fun onAccepted(requestId: String)
        fun onDelta(requestId: String, sequence: Int, text: String)
        fun onFinal(requestId: String, final: AgentFinal)
        fun onReportContent(requestId: String, report: ReportContent)
        fun onError(requestId: String?, error: BrokerError)
        fun onClosed(reason: String)
    }

    private var webSocket: WebSocket? = null

    fun connect() {
        val request = Request.Builder()
            .url(normalizeWebSocketUrl(brokerUrl))
            .header("X-Copilot-Box-Token", token)
            .build()
        webSocket = httpClient.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                webSocket.send(clientHelloJson())
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                handleMessage(text)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                listener.onClosed(t.message ?: "WebSocket failed")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                listener.onClosed(reason.ifBlank { "closed: $code" })
            }
        })
    }

    fun sendPrompt(
        workerId: String,
        workDir: String,
        sessionMode: String,
        sessionId: String?,
        prompt: String,
    ): String {
        val requestId = "android-${UUID.randomUUID()}"
        val socket = webSocket ?: throw IllegalStateException("Not connected to broker")
        socket.send(agentRequestJson(requestId, workerId, workDir, sessionMode, sessionId, prompt))
        return requestId
    }

    fun joinSession(workerId: String, activeRequestId: String): String {
        val requestId = "join-${UUID.randomUUID()}"
        val socket = webSocket ?: throw IllegalStateException("Not connected to broker")
        socket.send(sessionJoinJson(requestId, workerId, activeRequestId))
        return requestId
    }

    fun readReport(workerId: String, path: String): String {
        val requestId = "report-${UUID.randomUUID()}"
        val socket = webSocket ?: throw IllegalStateException("Not connected to broker")
        socket.send(reportReadJson(requestId, workerId, path))
        return requestId
    }

    fun close() {
        webSocket?.close(1000, "Activity destroyed")
        webSocket = null
    }

    private fun handleMessage(text: String) {
        val message = JSONObject(text)
        val requestId = message.optString("requestId").ifBlank { null }
        val payload = message.optJSONObject("payload") ?: JSONObject()
        when (message.optString("type")) {
            "broker.hello" -> listener.onConnected(
                parseWorkers(payload),
                parseActiveSessions(payload),
            )
            "session.snapshot" -> listener.onSessionSnapshot(
                requestId.orEmpty(),
                parseSessionSnapshot(payload),
            )
            "broker.accepted" -> listener.onAccepted(requestId.orEmpty())
            "agent.delta" -> listener.onDelta(
                requestId.orEmpty(),
                payload.optInt("sequence"),
                payload.optString("text"),
            )
            "agent.final" -> listener.onFinal(requestId.orEmpty(), AgentFinal.fromPayload(payload))
            "report.content" -> listener.onReportContent(
                requestId.orEmpty(),
                ReportContent.fromPayload(payload),
            )
            "error" -> listener.onError(requestId, BrokerError.fromPayload(payload))
        }
    }

    private fun normalizeWebSocketUrl(value: String): String {
        val trimmed = value.trim().trimEnd('/')
        val withScheme = when {
            trimmed.startsWith("wss://") || trimmed.startsWith("ws://") -> trimmed
            trimmed.startsWith("https://") -> "wss://${trimmed.removePrefix("https://")}"
            trimmed.startsWith("http://") -> "ws://${trimmed.removePrefix("http://")}"
            else -> "wss://$trimmed"
        }
        return if (withScheme.endsWith("/ws/client")) withScheme else "$withScheme/ws/client"
    }
}
