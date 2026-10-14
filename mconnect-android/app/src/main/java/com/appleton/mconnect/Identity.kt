package com.appleton.mconnect

import android.content.Context
import org.bouncycastle.asn1.x500.X500Name
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder
import org.bouncycastle.jce.provider.BouncyCastleProvider
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder
import java.io.File
import java.math.BigInteger
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Date
import java.util.UUID
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext

object Identity {

    private val bcProvider = BouncyCastleProvider()

    private const val CERT_VALID_DAYS = 3650L
    private const val KEY_ALIAS = "mconnect"

    private fun deviceIdFile(context: Context) = File(context.filesDir, "device_id")
    private fun keyFile(context: Context) = File(context.filesDir, "identity_key.der")
    private fun certFile(context: Context) = File(context.filesDir, "identity_cert.der")

    fun loadOrCreateDeviceId(context: Context): String {
        val file = deviceIdFile(context)
        if (file.exists()) {
            val existing = file.readText().trim()
            if (existing.isNotEmpty()) {
                return existing
            }
        }

        val deviceId = UUID.randomUUID().toString()
        file.writeText(deviceId)
        return deviceId
    }

    fun loadOrCreateIdentity(context: Context): Pair<PrivateKey, X509Certificate> {
        val keyFile = keyFile(context)
        val certFile = certFile(context)

        if (keyFile.exists() && certFile.exists()) {
            val keyFactory = KeyFactory.getInstance("RSA")
            val privateKey = keyFactory.generatePrivate(PKCS8EncodedKeySpec(keyFile.readBytes()))

            val certFactory = CertificateFactory.getInstance("X.509")
            val cert = certFactory.generateCertificate(certFile.inputStream()) as X509Certificate

            return Pair(privateKey, cert)
        }

        val deviceId = loadOrCreateDeviceId(context)
        val keyPair = KeyPairGenerator.getInstance("RSA").apply { initialize(2048) }.generateKeyPair()

        val subject = X500Name("CN=$deviceId")
        val now = Date()
        val notAfter = Date(now.time + CERT_VALID_DAYS * 24 * 60 * 60 * 1000)
        val serial = BigInteger(64, SecureRandom())

        val builder = JcaX509v3CertificateBuilder(subject, serial, now, notAfter, subject, keyPair.public)
        val signer = JcaContentSignerBuilder("SHA256WithRSA").setProvider(bcProvider).build(keyPair.private)
        val cert = JcaX509CertificateConverter().setProvider(bcProvider).getCertificate(builder.build(signer))

        keyFile.writeBytes(keyPair.private.encoded)
        certFile.writeBytes(cert.encoded)

        return Pair(keyPair.private, cert)
    }

    fun certFingerprint(cert: X509Certificate): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(cert.encoded)
        return digest.joinToString(":") { String.format("%02X", it.toInt() and 0xFF) }
    }

    fun buildServerSslContext(context: Context): SSLContext {
        val (privateKey, cert) = loadOrCreateIdentity(context)

        val keyStore = KeyStore.getInstance("PKCS12")
        keyStore.load(null, null)
        val password = CharArray(0)
        keyStore.setKeyEntry(KEY_ALIAS, privateKey, password, arrayOf(cert))

        val keyManagerFactory = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
        keyManagerFactory.init(keyStore, password)

        val sslContext = SSLContext.getInstance("TLS")
        sslContext.init(keyManagerFactory.keyManagers, null, null)
        return sslContext
    }
}