package com.github.richarddzh.copilotbox

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.w3c.dom.Element
import java.io.StringReader
import java.net.URLEncoder
import javax.xml.parsers.DocumentBuilderFactory
import org.xml.sax.InputSource

class BlobSasClient(
    private val containerSasUrl: String,
    private val httpClient: OkHttpClient = OkHttpClient(),
) {
    fun uploadJson(blobName: String, json: String) {
        val request = Request.Builder()
            .url(blobUrl(blobName))
            .put(json.toRequestBody("application/json; charset=utf-8".toMediaType()))
            .header("x-ms-blob-type", "BlockBlob")
            .header("x-ms-version", "2023-11-03")
            .build()
        httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("Upload failed: HTTP ${response.code} ${response.body?.string()}")
            }
        }
    }

    fun listBlobNames(prefix: String): List<String> {
        val request = Request.Builder()
            .url(containerUrlWithQuery("restype=container&comp=list&prefix=${urlEncode(prefix)}"))
            .get()
            .header("x-ms-version", "2023-11-03")
            .build()
        val xml = httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("List failed: HTTP ${response.code} ${response.body?.string()}")
            }
            response.body?.string().orEmpty()
        }
        return parseBlobNames(xml)
    }

    fun downloadText(blobName: String): String {
        val request = Request.Builder()
            .url(blobUrl(blobName))
            .get()
            .header("x-ms-version", "2023-11-03")
            .build()
        return httpClient.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("Download failed: HTTP ${response.code} ${response.body?.string()}")
            }
            response.body?.string().orEmpty()
        }
    }

    private fun blobUrl(blobName: String): String {
        val base = containerSasUrl.substringBefore("?").trimEnd('/')
        val sas = containerSasUrl.substringAfter("?", "")
        val encodedPath = blobName.split('/').joinToString("/") { urlEncode(it) }
        return if (sas.isBlank()) "$base/$encodedPath" else "$base/$encodedPath?$sas"
    }

    private fun containerUrlWithQuery(query: String): String {
        val separator = if (containerSasUrl.contains("?")) "&" else "?"
        return "$containerSasUrl$separator$query"
    }

    private fun parseBlobNames(xml: String): List<String> {
        if (xml.isBlank()) {
            return emptyList()
        }
        val document = DocumentBuilderFactory.newInstance()
            .newDocumentBuilder()
            .parse(InputSource(StringReader(xml)))
        val nodes = document.getElementsByTagName("Blob")
        return buildList {
            for (index in 0 until nodes.length) {
                val element = nodes.item(index) as Element
                val name = element.getElementsByTagName("Name").item(0)?.textContent
                if (!name.isNullOrBlank()) {
                    add(name)
                }
            }
        }
    }

    private fun urlEncode(value: String): String =
        URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")
}
