package com.github.richarddzh.copilotbox

import android.app.Activity
import com.microsoft.identity.client.AuthenticationCallback
import com.microsoft.identity.client.IAccount
import com.microsoft.identity.client.IAuthenticationResult
import com.microsoft.identity.client.IPublicClientApplication
import com.microsoft.identity.client.ISingleAccountPublicClientApplication
import com.microsoft.identity.client.PublicClientApplication
import com.microsoft.identity.client.SilentAuthenticationCallback
import com.microsoft.identity.client.exception.MsalException
import com.microsoft.identity.client.exception.MsalUiRequiredException

class MsalTokenProvider(
    private val activity: Activity,
    private val scopes: Array<String>,
) {
    private var app: ISingleAccountPublicClientApplication? = null
    private var account: IAccount? = null

    fun acquireToken(
        onSuccess: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        getApp(
            onSuccess = { application ->
                application.getCurrentAccountAsync(
                    object : ISingleAccountPublicClientApplication.CurrentAccountCallback {
                        override fun onAccountLoaded(activeAccount: IAccount?) {
                            account = activeAccount
                            if (activeAccount == null) {
                                acquireInteractive(application, onSuccess, onError)
                            } else {
                                acquireSilent(application, activeAccount, onSuccess, onError)
                            }
                        }

                        override fun onAccountChanged(
                            priorAccount: IAccount?,
                            currentAccount: IAccount?,
                        ) {
                            account = currentAccount
                        }

                        override fun onError(exception: MsalException) {
                            onError(exception.message ?: "MSAL account load failed")
                        }
                    },
                )
            },
            onError = onError,
        )
    }

    private fun getApp(
        onSuccess: (ISingleAccountPublicClientApplication) -> Unit,
        onError: (String) -> Unit,
    ) {
        app?.let {
            onSuccess(it)
            return
        }
        PublicClientApplication.createSingleAccountPublicClientApplication(
            activity,
            R.raw.auth_config_single_account,
            object : IPublicClientApplication.ISingleAccountApplicationCreatedListener {
                override fun onCreated(application: ISingleAccountPublicClientApplication) {
                    app = application
                    onSuccess(application)
                }

                override fun onError(exception: MsalException) {
                    onError(exception.message ?: "MSAL init failed")
                }
            },
        )
    }

    private fun acquireSilent(
        application: ISingleAccountPublicClientApplication,
        activeAccount: IAccount,
        onSuccess: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        application.acquireTokenSilentAsync(
            scopes,
            activeAccount.authority,
            object : SilentAuthenticationCallback {
                override fun onSuccess(authenticationResult: IAuthenticationResult) {
                    onSuccess(authenticationResult.accessToken)
                }

                override fun onError(exception: MsalException) {
                    if (exception is MsalUiRequiredException) {
                        acquireInteractive(application, onSuccess, onError)
                    } else {
                        onError(exception.message ?: "MSAL silent auth failed")
                    }
                }
            },
        )
    }

    private fun acquireInteractive(
        application: ISingleAccountPublicClientApplication,
        onSuccess: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        application.signIn(
            activity,
            null,
            scopes,
            object : AuthenticationCallback {
                override fun onSuccess(authenticationResult: IAuthenticationResult) {
                    account = authenticationResult.account
                    onSuccess(authenticationResult.accessToken)
                }

                override fun onError(exception: MsalException) {
                    onError(exception.message ?: "MSAL interactive auth failed")
                }

                override fun onCancel() {
                    onError("MSAL sign-in was cancelled")
                }
            },
        )
    }
}
