package com.github.richarddzh.copilotbox

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import okhttp3.OkHttpClient
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private val preferences by lazy { getSharedPreferences("copilot-box", MODE_PRIVATE) }

    private lateinit var requestSasUrl: EditText
    private lateinit var responseSasUrl: EditText
    private lateinit var requestPrefix: EditText
    private lateinit var workDir: EditText
    private lateinit var sessionMode: EditText
    private lateinit var sessionId: EditText
    private lateinit var prompt: EditText
    private lateinit var output: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContentView())
    }

    override fun onDestroy() {
        executor.shutdownNow()
        super.onDestroy()
    }

    private fun buildContentView(): ScrollView {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
        }
        requestSasUrl = input(
            "Requests container SAS URL",
            "https://<account>.blob.core.windows.net/requests?<sas>",
            preferences.getString("requestSasUrl", "").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI,
        )
        responseSasUrl = input(
            "Responses container SAS URL",
            "https://<account>.blob.core.windows.net/responses?<sas>",
            preferences.getString("responseSasUrl", "").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI,
        )
        requestPrefix = input(
            "Request prefix",
            "manual-test/android/",
            preferences.getString("requestPrefix", "manual-test/android/").orEmpty(),
        )
        workDir = input(
            "Remote work dir",
            "Q:\\gitroot\\copilot-box",
            preferences.getString("workDir", "Q:\\gitroot\\copilot-box").orEmpty(),
        )
        sessionMode = input(
            "Session mode",
            "auto, new, or continue",
            preferences.getString("sessionMode", "auto").orEmpty(),
        )
        sessionId = input(
            "Session id (optional)",
            "sess_xxx",
            preferences.getString("sessionId", "").orEmpty(),
        )
        prompt = input(
            "Prompt",
            "请只回复 pong，不要修改文件",
            preferences.getString("prompt", "请只回复 pong，不要修改文件").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE,
            minLines = 4,
        )
        output = TextView(this).apply {
            text = "Ready"
            setTextIsSelectable(true)
            textSize = 16f
        }
        val sendButton = Button(this).apply {
            text = "Send request"
            setOnClickListener { sendRequest() }
        }

        addField(container, "Requests container SAS URL", requestSasUrl)
        addField(container, "Responses container SAS URL", responseSasUrl)
        addField(container, "Request prefix", requestPrefix)
        addField(container, "Remote work dir", workDir)
        addField(container, "Session mode", sessionMode)
        addField(container, "Session id (optional)", sessionId)
        addField(container, "Prompt", prompt)
        container.addView(sendButton)
        container.addView(output)

        return ScrollView(this).apply { addView(container) }
    }

    private fun addField(container: LinearLayout, label: String, editText: EditText) {
        container.addView(
            TextView(this).apply {
                text = label
                textSize = 14f
                setPadding(0, 18, 0, 4)
            },
        )
        container.addView(editText)
    }

    private fun input(
        label: String,
        hint: String,
        value: String,
        inputType: Int = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS,
        minLines: Int = 1,
    ): EditText =
        EditText(this).apply {
            this.hint = hint
            setText(value)
            this.inputType = inputType
            this.minLines = minLines
            isSingleLine = minLines == 1
            isFocusable = true
            isFocusableInTouchMode = true
            textSize = 16f
            setSelectAllOnFocus(false)
            setOnClickListener {
                requestFocus()
                val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
                imm.showSoftInput(this, InputMethodManager.SHOW_IMPLICIT)
            }
            contentDescription = label
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }

    private fun sendRequest() {
        persistInputs()
        output.text = "Uploading request..."
        val requestSas = requestSasUrl.text.toString().trim()
        val responseSas = responseSasUrl.text.toString().trim()
        val request = CopilotBoxRequestFactory.create(
            requestPrefix = requestPrefix.text.toString(),
            workDir = workDir.text.toString(),
            prompt = prompt.text.toString(),
            sessionMode = sessionMode.text.toString().ifBlank { "auto" },
            sessionId = sessionId.text.toString().ifBlank { null },
        )

        executor.execute {
            try {
                val httpClient = OkHttpClient()
                val repository = CopilotBoxRepository(
                    requestClient = BlobSasClient(requestSas, httpClient),
                    responseClient = BlobSasClient(responseSas, httpClient),
                )
                repository.submit(request)
                postOutput("Request uploaded: ${request.requestBlobName}\nPolling final response...")
                val final = pollFinal(repository, request.responsePrefix)
                if (!final.sessionId.isNullOrBlank()) {
                    preferences.edit().putString("sessionId", final.sessionId).apply()
                }
                postOutput(
                    buildString {
                        appendLine("Status: ${final.status}")
                        appendLine("Session: ${final.sessionId.orEmpty()}")
                        appendLine()
                        appendLine(final.output ?: final.error.orEmpty())
                    },
                )
            } catch (exc: Exception) {
                postOutput("Failed: ${exc.message}")
            }
        }
    }

    private fun pollFinal(repository: CopilotBoxRepository, responsePrefix: String): FinalResponse {
        repeat(120) { attempt ->
            repository.tryReadFinalResponse(responsePrefix)?.let { return it }
            postOutput("Waiting for final response... ${attempt + 1}")
            Thread.sleep(3000)
        }
        throw IllegalStateException("Timed out waiting for final response")
    }

    private fun persistInputs() {
        preferences.edit()
            .putString("requestSasUrl", requestSasUrl.text.toString())
            .putString("responseSasUrl", responseSasUrl.text.toString())
            .putString("requestPrefix", requestPrefix.text.toString())
            .putString("workDir", workDir.text.toString())
            .putString("sessionMode", sessionMode.text.toString())
            .putString("sessionId", sessionId.text.toString())
            .putString("prompt", prompt.text.toString())
            .apply()
    }

    private fun postOutput(text: String) {
        mainHandler.post { output.text = text }
    }
}
