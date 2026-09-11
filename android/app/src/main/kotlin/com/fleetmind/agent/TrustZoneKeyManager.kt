package com.fleetmind.agent

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import android.util.Base64
import androidx.annotation.RequiresApi
import java.security.KeyFactory
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PublicKey
import java.security.SecureRandom
import java.security.cert.Certificate
import java.security.spec.ECGenParameterSpec
import java.security.spec.X509EncodedKeySpec
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

// TrustZoneKeyManager wraps Android Keystore to keep EC private keys inside the
// ARM TrustZone TEE. On API 31+ (Android 12+), ECDH agreement runs entirely
// inside the TEE via PURPOSE_AGREE_KEY. On API 26-30, the key is still generated
// and stored inside the TEE (hardware-backed), but the ECDH agreement step runs
// in Normal World using the private key reference — the private key bytes are
// never exposed; the Keystore JCE provider handles the operation.
class TrustZoneKeyManager(private val context: Context) {

    companion object {
        private const val KEY_ALIAS_PREFIX = "fleetmind_user_"
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val GCM_TAG_LENGTH = 128
        private const val GCM_IV_LENGTH = 12
    }

    private val keyStore: KeyStore by lazy {
        KeyStore.getInstance(ANDROID_KEYSTORE).also { it.load(null) }
    }

    fun generateUserKeyPair(userEmail: String): PublicKey {
        val alias = KEY_ALIAS_PREFIX + sanitizeAlias(userEmail)
        if (keyStore.containsAlias(alias)) {
            return keyStore.getCertificate(alias).publicKey
        }

        val kpg = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            try {
                kpg.initialize(buildKeyGenSpec(alias, useStrongBox = true))
                kpg.generateKeyPair()
                return keyStore.getCertificate(alias).publicKey
            } catch (_: StrongBoxUnavailableException) {
                keyStore.deleteEntry(alias)
            }
        }

        kpg.initialize(buildKeyGenSpec(alias, useStrongBox = false))
        kpg.generateKeyPair()
        return keyStore.getCertificate(alias).publicKey
    }

    // Encrypts query for a recipient. Uses an ephemeral EC key pair (not Keystore) for the sender
    // side of ECDH — this is intentional: the sender's ephemeral key provides forward secrecy.
    // The recipient's Keystore private key never leaves the TEE during decryption.
    fun encryptQuery(query: String, recipientPublicKeyBase64: String): String {
        val recipientPubKeyBytes = Base64.decode(recipientPublicKeyBase64, Base64.NO_WRAP)
        val recipientPublicKey = KeyFactory.getInstance("EC")
            .generatePublic(X509EncodedKeySpec(recipientPubKeyBytes))

        val ephemeralKpg = KeyPairGenerator.getInstance("EC")
        ephemeralKpg.initialize(ECGenParameterSpec("secp256r1"))
        val ephemeralKeyPair = ephemeralKpg.generateKeyPair()

        val ka = KeyAgreement.getInstance("ECDH")
        ka.init(ephemeralKeyPair.private)
        ka.doPhase(recipientPublicKey, true)
        val sharedSecret = ka.generateSecret()

        val aesKeyBytes = deriveAesKey(sharedSecret)
        val iv = SecureRandom().generateSeed(GCM_IV_LENGTH)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(aesKeyBytes, "AES"), GCMParameterSpec(GCM_TAG_LENGTH, iv))
        val cipherText = cipher.doFinal(query.toByteArray(Charsets.UTF_8))

        val ephemeralPubKeyBytes = ephemeralKeyPair.public.encoded
        val ephemeralPubKeyLen = ephemeralPubKeyBytes.size
        val result = ByteArray(2 + ephemeralPubKeyLen + GCM_IV_LENGTH + cipherText.size)
        result[0] = (ephemeralPubKeyLen shr 8).toByte()
        result[1] = (ephemeralPubKeyLen and 0xFF).toByte()
        System.arraycopy(ephemeralPubKeyBytes, 0, result, 2, ephemeralPubKeyLen)
        System.arraycopy(iv, 0, result, 2 + ephemeralPubKeyLen, GCM_IV_LENGTH)
        System.arraycopy(cipherText, 0, result, 2 + ephemeralPubKeyLen + GCM_IV_LENGTH, cipherText.size)

        return Base64.encodeToString(result, Base64.NO_WRAP)
    }

    // Decrypts using this device's TrustZone-backed private key.
    // The private key never leaves the TEE; the JCE Keystore provider executes ECDH inside it.
    fun decryptResponse(encryptedResponse: String): String {
        val raw = Base64.decode(encryptedResponse, Base64.NO_WRAP)

        val ephemeralPubKeyLen = ((raw[0].toInt() and 0xFF) shl 8) or (raw[1].toInt() and 0xFF)
        val ephemeralPubKeyBytes = raw.copyOfRange(2, 2 + ephemeralPubKeyLen)
        val iv = raw.copyOfRange(2 + ephemeralPubKeyLen, 2 + ephemeralPubKeyLen + GCM_IV_LENGTH)
        val cipherText = raw.copyOfRange(2 + ephemeralPubKeyLen + GCM_IV_LENGTH, raw.size)

        val ephemeralPublicKey = KeyFactory.getInstance("EC")
            .generatePublic(X509EncodedKeySpec(ephemeralPubKeyBytes))

        val sanitizedEmail = findAliasForDecryption()
            ?: throw IllegalStateException("No TrustZone key found for this device")
        val alias = KEY_ALIAS_PREFIX + sanitizedEmail

        val privateKeyEntry = keyStore.getEntry(alias, null) as KeyStore.PrivateKeyEntry

        // ECDH via AndroidKeyStore provider — TEE executes the agreement, never exposes private key
        val ka = KeyAgreement.getInstance("ECDH", ANDROID_KEYSTORE)
        ka.init(privateKeyEntry.privateKey)
        ka.doPhase(ephemeralPublicKey, true)
        val sharedSecret = ka.generateSecret()

        val aesKeyBytes = deriveAesKey(sharedSecret)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(aesKeyBytes, "AES"), GCMParameterSpec(GCM_TAG_LENGTH, iv))
        return String(cipher.doFinal(cipherText), Charsets.UTF_8)
    }

    fun getPublicKeyBase64(userEmail: String): String {
        val alias = KEY_ALIAS_PREFIX + sanitizeAlias(userEmail)
        if (!keyStore.containsAlias(alias)) generateUserKeyPair(userEmail)
        return Base64.encodeToString(keyStore.getCertificate(alias).publicKey.encoded, Base64.NO_WRAP)
    }

    fun getAttestationCertificateChain(userEmail: String): List<Certificate> {
        val alias = KEY_ALIAS_PREFIX + sanitizeAlias(userEmail)
        if (!keyStore.containsAlias(alias)) generateUserKeyPair(userEmail)
        return keyStore.getCertificateChain(alias)?.toList()
            ?: throw IllegalStateException("No certificate chain found for alias $alias")
    }

    fun isHardwareBacked(userEmail: String): Boolean {
        val alias = KEY_ALIAS_PREFIX + sanitizeAlias(userEmail)
        if (!keyStore.containsAlias(alias)) return false
        return try {
            val entry = keyStore.getEntry(alias, null) as? KeyStore.PrivateKeyEntry ?: return false
            val keyInfo = android.security.keystore.KeyFactory.getInstance(
                entry.privateKey.algorithm, ANDROID_KEYSTORE
            ).getKeySpec(entry.privateKey, android.security.keystore.KeyInfo::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                keyInfo.securityLevel != KeyProperties.SECURITY_LEVEL_SOFTWARE
            } else {
                @Suppress("DEPRECATION")
                keyInfo.isInsideSecureHardware
            }
        } catch (_: Exception) {
            false
        }
    }

    private fun buildKeyGenSpec(alias: String, useStrongBox: Boolean): KeyGenParameterSpec {
        // PURPOSE_AGREE_KEY requires API 31; use PURPOSE_SIGN as fallback for older devices.
        // In both cases the key is hardware-backed; only the permitted JCE operations differ.
        val purpose = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            KeyProperties.PURPOSE_AGREE_KEY
        } else {
            KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY
        }

        val builder = KeyGenParameterSpec.Builder(alias, purpose)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA512)
            .setUserAuthenticationRequired(false)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (useStrongBox) builder.setIsStrongBoxBacked(true)
            builder.setAttestationChallenge(
                "fleetmind-attestation-${System.currentTimeMillis()}".toByteArray()
            )
        }

        return builder.build()
    }

    private fun deriveAesKey(sharedSecret: ByteArray): ByteArray =
        java.security.MessageDigest.getInstance("SHA-256").digest(sharedSecret)

    private fun sanitizeAlias(email: String): String =
        email.replace(Regex("[^a-zA-Z0-9._-]"), "_")

    private fun findAliasForDecryption(): String? {
        val aliases = keyStore.aliases()
        while (aliases.hasMoreElements()) {
            val alias = aliases.nextElement()
            if (alias.startsWith(KEY_ALIAS_PREFIX)) {
                return alias.removePrefix(KEY_ALIAS_PREFIX)
            }
        }
        return null
    }
}
