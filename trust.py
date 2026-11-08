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
import json
import ssl

from identity import fingerprint_from_der

TRUST_DIR = os.path.expanduser("~/.config/mconnect")
TRUST_PATH = os.path.join(TRUST_DIR, "trusted_devices.json")


def _load():
    if not os.path.exists(TRUST_PATH):
        return {}
    with open(TRUST_PATH) as f:
        return json.load(f)


def _save(data):
    os.makedirs(TRUST_DIR, exist_ok=True)
    with open(TRUST_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _entry(value):
    if isinstance(value, str):
        return {"fingerprint": value, "certificate": None}
    return value


def is_trusted(address, fingerprint):
    value = _load().get(address)
    return value is not None and _entry(value)["fingerprint"] == fingerprint


def get_trusted_fingerprint(address):
    value = _load().get(address)
    return None if value is None else _entry(value)["fingerprint"]


def has_trusted_certificate(address):
    value = _load().get(address)
    return value is not None and _entry(value)["certificate"] is not None


def is_fingerprint_trusted(fingerprint):
    return any(_entry(value)["fingerprint"] == fingerprint for value in _load().values())


def trusted_certificates():
    entries = [_entry(value) for value in _load().values()]
    return [entry["certificate"] for entry in entries if entry["certificate"]]


def trust(address, fingerprint, certificate=None):
    if certificate is not None:
        der_cert = ssl.PEM_cert_to_DER_cert(certificate)
        if fingerprint_from_der(der_cert) != fingerprint:
            raise ValueError("El certificado no corresponde al fingerprint indicado")
    data = _load()
    if certificate is None and address in data:
        existing = _entry(data[address])
        if existing["fingerprint"] == fingerprint:
            certificate = existing["certificate"]
    data[address] = {"fingerprint": fingerprint, "certificate": certificate}
    _save(data)


def forget(address):
    data = _load()
    data.pop(address, None)
    _save(data)