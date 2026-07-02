package com.github.richarddzh.copilotbox

import android.app.Activity
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.InputType
import android.view.Gravity
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.ArrayAdapter
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Spinner
import android.widget.TextView
import io.noties.markwon.Markwon

class MainActivity : Activity(), BrokerClient.Listener {
    private val mainHandler = Handler(Looper.getMainLooper())
    private val preferences by lazy { getSharedPreferences("copilot-box", MODE_PRIVATE) }
    private val markwon by lazy { Markwon.create(this) }

    private lateinit var brokerUrl: EditText
    private lateinit var brokerToken: EditText
    private lateinit var workerSpinner: Spinner
    private lateinit var workDirSpinner: Spinner
    private lateinit var sessionActionSpinner: Spinner
    private lateinit var prompt: EditText
    private lateinit var status: TextView
    private lateinit var messages: LinearLayout
    private lateinit var scrollView: ScrollView

    private var brokerClient: BrokerClient? = null
    private var workers: List<BrokerWorker> = emptyList()
    private var lastRequestWorkerId: String? = null
    private var currentAssistantBubble: TextView? = null
    private val currentAssistantMarkdown = StringBuilder()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildContentView())
    }

    override fun onDestroy() {
        brokerClient?.close()
        super.onDestroy()
    }

    private fun buildContentView(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
        }
        brokerUrl = input(
            "Broker WebSocket URL",
            "wss://<app-name>.azurewebsites.net/ws/client",
            preferences.getString("brokerUrl", "").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI,
        )
        brokerToken = input(
            "Client token",
            "shared secret token",
            preferences.getString("brokerToken", "").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD,
        )
        workerSpinner = Spinner(this)
        workDirSpinner = Spinner(this)
        sessionActionSpinner = Spinner(this).apply {
            adapter = ArrayAdapter(
                this@MainActivity,
                android.R.layout.simple_spinner_dropdown_item,
                listOf("继续现有 session", "在该 work dir 新建 session"),
            )
        }
        prompt = input(
            "Message",
            "输入 prompt，支持要求 agent 返回 Markdown",
            preferences.getString("prompt", "请用 Markdown 总结当前项目").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE,
            minLines = 3,
        )
        status = TextView(this).apply {
            text = "Disconnected"
            textSize = 14f
        }
        messages = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }
        scrollView = ScrollView(this).apply {
            addView(messages)
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                0,
                1f,
            )
        }

        val connectButton = Button(this).apply {
            text = "Connect"
            setOnClickListener { connectBroker() }
        }
        val sendButton = Button(this).apply {
            text = "Send"
            setOnClickListener { sendPrompt() }
        }

        addField(root, "Broker WebSocket URL", brokerUrl)
        addField(root, "Client token", brokerToken)
        root.addView(connectButton)
        addSpinner(root, "Worker", workerSpinner)
        addSpinner(root, "Work dir", workDirSpinner)
        addSpinner(root, "Session", sessionActionSpinner)
        root.addView(status)
        root.addView(scrollView)
        addField(root, "Message", prompt)
        root.addView(sendButton)
        return root
    }

    private fun connectBroker() {
        persistInputs()
        status.text = "Connecting..."
        brokerClient?.close()
        brokerClient = BrokerClient(
            brokerUrl = brokerUrl.text.toString(),
            token = brokerToken.text.toString(),
            listener = this,
        ).also { it.connect() }
    }

    private fun sendPrompt() {
        val selectedPrompt = prompt.text.toString()
        if (selectedPrompt.isBlank()) {
            return
        }
        val worker = selectedWorker() ?: run {
            status.text = "No worker connected"
            return
        }
        val workDir = workDirSpinner.selectedItem?.toString().orEmpty()
        if (workDir.isBlank()) {
            status.text = "No work dir selected"
            return
        }
        persistInputs()
        addUserBubble(selectedPrompt)
        currentAssistantMarkdown.clear()
        currentAssistantBubble = addAssistantBubble("...")
        val sessionMode = if (sessionActionSpinner.selectedItemPosition == 1) "new" else "auto"
        try {
            lastRequestWorkerId = worker.workerId
            brokerClient?.sendPrompt(worker.workerId, workDir, sessionMode, selectedPrompt)
            status.text = "Running..."
            prompt.setText("")
        } catch (exc: Exception) {
            status.text = exc.message ?: "Send failed"
        }
    }

    override fun onConnected(workers: List<BrokerWorker>) {
        mainHandler.post {
            this.workers = workers
            status.text = if (workers.isEmpty()) "Connected: no workers" else "Connected"
            workerSpinner.adapter = ArrayAdapter(
                this,
                android.R.layout.simple_spinner_dropdown_item,
                workers,
            )
            updateWorkDirs()
            workerSpinner.setOnItemSelectedListener(SimpleItemSelectedListener { updateWorkDirs() })
        }
    }

    override fun onAccepted(requestId: String) {
        mainHandler.post { status.text = "Accepted: $requestId" }
    }

    override fun onDelta(requestId: String, sequence: Int, text: String) {
        mainHandler.post {
            currentAssistantMarkdown.append(text)
            renderAssistantMarkdown(currentAssistantMarkdown.toString())
        }
    }

    override fun onFinal(requestId: String, final: AgentFinal) {
        mainHandler.post {
            currentAssistantMarkdown.clear()
            currentAssistantMarkdown.append(final.output)
            renderAssistantMarkdown(final.output)
            status.text = "${final.status}: ${final.sessionId.orEmpty()}"
            val reportPath = final.reportPath
            val workerId = lastRequestWorkerId
            if (!reportPath.isNullOrBlank() && !workerId.isNullOrBlank()) {
                status.text = "Loading report: $reportPath"
                brokerClient?.readReport(workerId, reportPath)
            }
        }
    }

    override fun onReportContent(requestId: String, report: ReportContent) {
        mainHandler.post {
            val title = "**Report:** `${report.path}`\n\n"
            currentAssistantMarkdown.clear()
            currentAssistantMarkdown.append(title).append(report.content)
            renderAssistantMarkdown(currentAssistantMarkdown.toString())
            status.text = "Report loaded"
        }
    }

    override fun onError(requestId: String?, error: BrokerError) {
        mainHandler.post {
            val bubble = currentAssistantBubble ?: addAssistantBubble("")
            currentAssistantBubble = bubble
            currentAssistantMarkdown.clear()
            currentAssistantMarkdown.append("**Error `${error.code}`**\n\n${error.message}")
            renderAssistantMarkdown(currentAssistantMarkdown.toString())
            status.text = "Failed: ${error.code}"
        }
    }

    override fun onClosed(reason: String) {
        mainHandler.post { status.text = "Disconnected: $reason" }
    }

    private fun updateWorkDirs() {
        val worker = selectedWorker()
        workDirSpinner.adapter = ArrayAdapter(
            this,
            android.R.layout.simple_spinner_dropdown_item,
            worker?.allowedWorkDirs ?: emptyList(),
        )
    }

    private fun selectedWorker(): BrokerWorker? =
        workerSpinner.selectedItem as? BrokerWorker

    private fun addUserBubble(text: String) {
        addBubble(text, isUser = true)
    }

    private fun addAssistantBubble(markdown: String): TextView =
        addBubble(markdown, isUser = false).also {
            markwon.setMarkdown(it, markdown)
        }

    private fun addBubble(text: String, isUser: Boolean): TextView {
        val bubble = TextView(this).apply {
            this.text = text
            textSize = 16f
            setTextIsSelectable(true)
            setPadding(24, 16, 24, 16)
            setBackgroundColor(if (isUser) Color.rgb(220, 240, 255) else Color.rgb(240, 240, 240))
            layoutParams = LinearLayout.LayoutParams(
                (resources.displayMetrics.widthPixels * 0.82f).toInt(),
                ViewGroup.LayoutParams.WRAP_CONTENT,
            ).apply {
                gravity = if (isUser) Gravity.END else Gravity.START
                setMargins(0, 8, 0, 8)
            }
        }
        messages.addView(bubble)
        scrollToBottom()
        return bubble
    }

    private fun renderAssistantMarkdown(markdown: String) {
        val bubble = currentAssistantBubble ?: addAssistantBubble("")
        markwon.setMarkdown(bubble, markdown.ifBlank { "..." })
        scrollToBottom()
    }

    private fun scrollToBottom() {
        scrollView.post { scrollView.fullScroll(ScrollView.FOCUS_DOWN) }
    }

    private fun addField(container: LinearLayout, label: String, editText: EditText) {
        container.addView(TextView(this).apply { text = label })
        container.addView(editText)
    }

    private fun addSpinner(container: LinearLayout, label: String, spinner: Spinner) {
        container.addView(TextView(this).apply { text = label })
        container.addView(spinner)
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
            textSize = 16f
            contentDescription = label
            setOnClickListener {
                requestFocus()
                val imm = getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager
                imm.showSoftInput(this, InputMethodManager.SHOW_IMPLICIT)
            }
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT,
            )
        }

    private fun persistInputs() {
        preferences.edit()
            .putString("brokerUrl", brokerUrl.text.toString())
            .putString("brokerToken", brokerToken.text.toString())
            .putString("prompt", prompt.text.toString())
            .apply()
    }
}
