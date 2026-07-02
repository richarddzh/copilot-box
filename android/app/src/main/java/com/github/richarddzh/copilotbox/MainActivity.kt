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
    private lateinit var configStatus: TextView
    private lateinit var startChatButton: Button

    private lateinit var prompt: EditText
    private lateinit var chatStatus: TextView
    private lateinit var messages: LinearLayout
    private lateinit var scrollView: ScrollView

    private var brokerClient: BrokerClient? = null
    private var workers: List<BrokerWorker> = emptyList()
    private var selectedWorkerId: String? = null
    private var selectedWorkDir: String? = null
    private var selectedSessionMode: String = "auto"
    private var lastRequestWorkerId: String? = null
    private var currentAssistantBubble: TextView? = null
    private val currentAssistantMarkdown = StringBuilder()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        showConnectionView()
    }

    override fun onDestroy() {
        brokerClient?.close()
        super.onDestroy()
    }

    private fun showConnectionView() {
        setContentView(buildConnectionView())
    }

    private fun showChatView() {
        setContentView(buildChatView())
    }

    private fun buildConnectionView(): ScrollView {
        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 32, 32, 32)
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
        configStatus = TextView(this).apply {
            text = "Disconnected"
            textSize = 14f
            setPadding(0, 16, 0, 16)
        }
        startChatButton = Button(this).apply {
            text = "Start chat"
            isEnabled = false
            setOnClickListener { startChat() }
        }
        val connectButton = Button(this).apply {
            text = "Connect"
            setOnClickListener { connectBroker() }
        }

        container.addView(title("Connection"))
        addField(container, "Broker WebSocket URL", brokerUrl)
        addField(container, "Client token", brokerToken)
        container.addView(connectButton)
        container.addView(configStatus)
        container.addView(title("Session target"))
        addSpinner(container, "Worker", workerSpinner)
        addSpinner(container, "Work dir", workDirSpinner)
        addSpinner(container, "Session", sessionActionSpinner)
        container.addView(startChatButton)
        return ScrollView(this).apply { addView(container) }
    }

    private fun buildChatView(): LinearLayout {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 24, 24, 24)
        }
        chatStatus = TextView(this).apply {
            text = "Ready"
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
        prompt = input(
            "Message",
            "输入 prompt，支持要求 agent 返回 Markdown",
            preferences.getString("prompt", "请用 Markdown 总结当前项目").orEmpty(),
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE,
            minLines = 3,
        )
        val switchButton = Button(this).apply {
            text = "Exit to connection settings"
            setOnClickListener { exitToConnectionSettings() }
        }
        val sendButton = Button(this).apply {
            text = "Send"
            setOnClickListener { sendPrompt() }
        }

        root.addView(title("Copilot Box"))
        root.addView(chatStatus)
        root.addView(scrollView)
        addField(root, "Message", prompt)
        root.addView(sendButton)
        root.addView(switchButton)
        return root
    }

    private fun exitToConnectionSettings() {
        brokerClient?.close()
        brokerClient = null
        workers = emptyList()
        selectedWorkerId = null
        selectedWorkDir = null
        selectedSessionMode = "auto"
        lastRequestWorkerId = null
        currentAssistantBubble = null
        currentAssistantMarkdown.clear()
        showConnectionView()
    }

    private fun connectBroker() {
        persistConnectionInputs()
        configStatus.text = "Connecting..."
        brokerClient?.close()
        brokerClient = BrokerClient(
            brokerUrl = brokerUrl.text.toString(),
            token = brokerToken.text.toString(),
            listener = this,
        ).also { it.connect() }
    }

    private fun startChat() {
        val worker = selectedWorker() ?: run {
            configStatus.text = "No worker connected"
            return
        }
        val workDir = workDirSpinner.selectedItem?.toString().orEmpty()
        if (workDir.isBlank()) {
            configStatus.text = "No work dir selected"
            return
        }
        selectedWorkerId = worker.workerId
        selectedWorkDir = workDir
        selectedSessionMode = if (sessionActionSpinner.selectedItemPosition == 1) "new" else "auto"
        currentAssistantBubble = null
        currentAssistantMarkdown.clear()
        showChatView()
    }

    private fun sendPrompt() {
        val selectedPrompt = prompt.text.toString()
        if (selectedPrompt.isBlank()) {
            return
        }
        val workerId = selectedWorkerId ?: run {
            chatStatus.text = "No worker selected"
            return
        }
        val workDir = selectedWorkDir ?: run {
            chatStatus.text = "No work dir selected"
            return
        }
        persistPromptInput()
        addUserBubble(selectedPrompt)
        currentAssistantMarkdown.clear()
        currentAssistantBubble = addAssistantBubble("...")
        try {
            lastRequestWorkerId = workerId
            brokerClient?.sendPrompt(workerId, workDir, selectedSessionMode, selectedPrompt)
            chatStatus.text = "Running..."
            prompt.setText("")
        } catch (exc: Exception) {
            chatStatus.text = exc.message ?: "Send failed"
        }
    }

    override fun onConnected(workers: List<BrokerWorker>) {
        mainHandler.post {
            this.workers = workers
            if (::configStatus.isInitialized) {
                configStatus.text = if (workers.isEmpty()) "Connected: no workers" else "Connected"
                startChatButton.isEnabled = workers.isNotEmpty()
                workerSpinner.adapter = ArrayAdapter(
                    this,
                    android.R.layout.simple_spinner_dropdown_item,
                    workers,
                )
                updateWorkDirs()
                workerSpinner.setOnItemSelectedListener(
                    SimpleItemSelectedListener { updateWorkDirs() },
                )
            }
        }
    }

    override fun onAccepted(requestId: String) {
        mainHandler.post {
            if (::chatStatus.isInitialized) {
                chatStatus.text = "Accepted: $requestId"
            }
        }
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
            chatStatus.text = "${final.status}: ${final.sessionId.orEmpty()}"
            val reportPath = final.reportPath
            val workerId = lastRequestWorkerId
            if (!reportPath.isNullOrBlank() && !workerId.isNullOrBlank()) {
                chatStatus.text = "Loading report"
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
            chatStatus.text = "Report loaded"
        }
    }

    override fun onError(requestId: String?, error: BrokerError) {
        mainHandler.post {
            if (!::messages.isInitialized) {
                if (::configStatus.isInitialized) {
                    configStatus.text = "Failed: ${error.code}"
                }
                return@post
            }
            val bubble = currentAssistantBubble ?: addAssistantBubble("")
            currentAssistantBubble = bubble
            currentAssistantMarkdown.clear()
            currentAssistantMarkdown.append("**Error `${error.code}`**\n\n${error.message}")
            renderAssistantMarkdown(currentAssistantMarkdown.toString())
            chatStatus.text = "Failed: ${error.code}"
        }
    }

    override fun onClosed(reason: String) {
        mainHandler.post {
            val text = "Disconnected: $reason"
            if (::chatStatus.isInitialized) {
                chatStatus.text = text
            }
            if (::configStatus.isInitialized) {
                configStatus.text = text
                startChatButton.isEnabled = false
            }
        }
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

    private fun title(text: String): TextView =
        TextView(this).apply {
            this.text = text
            textSize = 20f
            setPadding(0, 16, 0, 12)
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

    private fun persistConnectionInputs() {
        preferences.edit()
            .putString("brokerUrl", brokerUrl.text.toString())
            .putString("brokerToken", brokerToken.text.toString())
            .apply()
    }

    private fun persistPromptInput() {
        preferences.edit()
            .putString("prompt", prompt.text.toString())
            .apply()
    }
}
