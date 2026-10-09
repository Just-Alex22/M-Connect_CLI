#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# M-Connect CLI
# Copyright (C) 2026 Appleton S.A. & Co.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/gpl-3.0.en.html>.

import os
import ssl
import datetime

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

IDENTITY_DIR = os.path.expanduser("~/.config/mconnect")
KEY_PATH = os.path.join(IDENTITY_DIR, "identity_key.pem")
CERT_PATH = os.path.join(IDENTITY_DIR, "identity_cert.pem")
DEVICE_ID_PATH = os.path.join(IDENTITY_DIR, "device_id")

CERT_VALID_DAYS = 3650


def load_or_create_device_id():
    os.makedirs(IDENTITY_DIR, exist_ok=True)

    if os.path.exists(DEVICE_ID_PATH):
        with open(DEVICE_ID_PATH) as f:
            device_id = f.read().strip()
        if device_id:
            return device_id

    import uuid
    device_id = str(uuid.uuid4())
    with open(DEVICE_ID_PATH, "w") as f:
        f.write(device_id)
    return device_id


def _generate_identity(device_id):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, device_id),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=CERT_VALID_DAYS))
        .sign(key, hashes.SHA256())
    )

    with open(KEY_PATH, "wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ))
    os.chmod(KEY_PATH, 0o600)

    with open(CERT_PATH, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return key, cert


def load_or_create_identity():
    os.makedirs(IDENTITY_DIR, exist_ok=True)

    if os.path.exists(KEY_PATH) and os.path.exists(CERT_PATH):
        with open(KEY_PATH, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
        with open(CERT_PATH, "rb") as f:
            cert = x509.load_pem_x509_certificate(f.read())
        return key, cert

    device_id = load_or_create_device_id()
    return _generate_identity(device_id)


def cert_fingerprint(cert):
    digest = cert.fingerprint(hashes.SHA256())
    return digest.hex()


def cert_fingerprint_display(cert):
    raw = cert_fingerprint(cert)
    return ":".join(raw[i:i + 2] for i in range(0, len(raw), 2)).upper()


def build_server_ssl_context():
    load_or_create_identity()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_PATH, keyfile=KEY_PATH)
    context.verify_mode = ssl.CERT_NONE
    return context


def build_client_ssl_context():
    load_or_create_identity()
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context