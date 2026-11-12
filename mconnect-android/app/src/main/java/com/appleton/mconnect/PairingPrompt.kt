package com.appleton.mconnect

import java.util.concurrent.CountDownLatch
import java.util.concurrent.Semaphore
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

typealias PairingResponder = (Boolean) -> Unit

typealias PairingPresenter = (address: String, fingerprint: String, respond: PairingResponder) -> (() -> Unit)

object PairingPrompt {

    enum class Answer { ACCEPTED, REJECTED, TIMEOUT, UNAVAILABLE, BUSY }

    private const val DEFAULT_TIMEOUT_SECONDS = 60L

    private val pending = Semaphore(1)

    @Volatile
    var presenter: PairingPresenter? = null

    fun request(address: String, fingerprint: String, timeoutSeconds: Long = DEFAULT_TIMEOUT_SECONDS): Answer {
        val present = presenter ?: return Answer.UNAVAILABLE
        if (!pending.tryAcquire()) {
            return Answer.BUSY
        }
        try {
            val latch = CountDownLatch(1)
            val answered = AtomicBoolean(false)
            val accepted = AtomicBoolean(false)
            val dismiss = present(address, fingerprint) { value ->
                if (answered.compareAndSet(false, true)) {
                    accepted.set(value)
                    latch.countDown()
                }
            }
            if (!latch.await(timeoutSeconds, TimeUnit.SECONDS)) {
                answered.set(true)
                dismiss()
                return Answer.TIMEOUT
            }
            return if (accepted.get()) Answer.ACCEPTED else Answer.REJECTED
        } finally {
            pending.release()
        }
    }
}