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


def is_trusted(address, fingerprint):
    data = _load()
    return data.get(address) == fingerprint


def trust(address, fingerprint):
    data = _load()
    data[address] = fingerprint
    _save(data)


def forget(address):
    data = _load()
    data.pop(address, None)
    _save(data)