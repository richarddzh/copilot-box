package com.github.richarddzh.copilotbox

class CopilotBoxRepository(
    private val requestClient: BlobSasClient,
    private val responseClient: BlobSasClient,
) {
    fun submit(request: CopilotBoxRequest) {
        requestClient.uploadJson(request.requestBlobName, request.json)
    }

    fun tryReadFinalResponse(responsePrefix: String): FinalResponse? {
        val finalBlob = "$responsePrefix/999999.final.json"
        val names = responseClient.listBlobNames(responsePrefix)
        if (!names.contains(finalBlob)) {
            return null
        }
        return FinalResponse.parse(responseClient.downloadText(finalBlob))
    }
}
