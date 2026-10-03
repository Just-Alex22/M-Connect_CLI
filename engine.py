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

import asyncio
import socket
import json
import uuid
import time
import platform
import base64
import os

from dbus_next.service import ServiceInterface, method
from dbus_next.aio import MessageBus

DISCOVERY_PORT = 17160
EXEC_PORT = 17161
PHONE_DEVICE_PORT = 17162
BROADCAST_ADDR = "255.255.255.255"
ANNOUNCE_INTERVAL_SECONDS = 2
DEVICE_TIMEOUT_SECONDS = 6
CLEANUP_INTERVAL_SECONDS = 2

BUS_NAME = "com.appleton.MConnect"
OBJECT_PATH = "/com/appleton/MConnect/Engine"

DEVICE_ID = str(uuid.uuid4())
DEVICE_NAME = platform.node()

devices = {}


def build_identity_packet():
    payload = {
        "type": "identity",
        "deviceId": DEVICE_ID,
        "deviceName": DEVICE_NAME,
        "port": EXEC_PORT,
    }
    return json.dumps(payload).encode("utf-8")


class DiscoveryProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        sock = transport.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    def datagram_received(self, data, addr):
        try:
            payload = json.loads(data.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return

        if payload.get("type") != "identity":
            return

        device_id = payload.get("deviceId")
        if device_id is None or device_id == DEVICE_ID:
            return

        is_new = device_id not in devices
        devices[device_id] = {
            "deviceName": payload.get("deviceName", "unknown"),
            "address": addr[0],
            "port": payload.get("port", EXEC_PORT),
            "last_seen": time.monotonic(),
        }

        if is_new:
            device = devices[device_id]
            print(f"[+] {device['deviceName']} ({device['address']}) discovered")


async def announce_loop(transport):
    packet = build_identity_packet()
    while True:
        transport.sendto(packet, (BROADCAST_ADDR, DISCOVERY_PORT))
        await asyncio.sleep(ANNOUNCE_INTERVAL_SECONDS)


async def cleanup_loop():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        now = time.monotonic()
        expired = [
            device_id
            for device_id, device in devices.items()
            if now - device["last_seen"] > DEVICE_TIMEOUT_SECONDS
        ]

        for device_id in expired:
            device = devices.pop(device_id)
            print(f"[-] {device['deviceName']} ({device['address']}) lost")


async def start_discovery():
    loop = asyncio.get_running_loop()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", DISCOVERY_PORT))
    sock.setblocking(False)

    transport, protocol = await loop.create_datagram_endpoint(
        DiscoveryProtocol, sock=sock
    )

    await asyncio.gather(announce_loop(transport), cleanup_loop())


async def handle_exec_client(reader, writer):
    peer = writer.get_extra_info("peername")
    peer_ip = peer[0] if peer else "unknown"

    try:
        line = await reader.readline()
        if not line:
            return

        request = json.loads(line.decode("utf-8"))
        if request.get("type") != "exec":
            return

        command = request.get("command", "")
        print(f"[exec-in] {peer_ip} -> {command}")

        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        response = {
            "type": "exec_result",
            "exit_code": process.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except (json.JSONDecodeError, UnicodeDecodeError):
        response = {
            "type": "exec_result",
            "exit_code": -1,
            "stdout": "",
            "stderr": "invalid request",
        }
    finally:
        writer.write((json.dumps(response) + "\n").encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()


async def start_exec_server():
    server = await asyncio.start_server(handle_exec_client, "0.0.0.0", EXEC_PORT)
    async with server:
        await server.serve_forever()


async def exec_remote(address, command):
    try:
        reader, writer = await asyncio.open_connection(address, EXEC_PORT)
    except ConnectionRefusedError:
        return [
            -1,
            "",
            f"{address} refused the connection on port {EXEC_PORT} — "
            "it may not be running an exec server (e.g. it's a phone/client-only device)",
        ]
    except OSError as e:
        return [-1, "", f"connection failed: {e}"]

    request = {"type": "exec", "command": command}
    writer.write((json.dumps(request) + "\n").encode("utf-8"))
    await writer.drain()

    line = await reader.readline()
    writer.close()
    await writer.wait_closed()

    if not line:
        return [-1, "", "no response from device"]

    try:
        response = json.loads(line.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return [-1, "", "invalid response from device"]

    return [
        response.get("exit_code", -1),
        response.get("stdout", ""),
        response.get("stderr", ""),
    ]


async def device_get(address, category, field, extra=None):
    request = {"type": "get", "category": category, "field": field}
    if extra:
        request.update(extra)
    return await _call_phone_device(address, request)


async def device_set(address, category, value):
    request = {"type": "set", "category": category, "value": value}
    return await _call_phone_device(address, request)


async def device_file(address, local_path, subdir=""):
    if not os.path.isfile(local_path):
        return json.dumps({"ok": False, "error": f"no such file: {local_path}"})

    with open(local_path, "rb") as f:
        data = f.read()

    request = {
        "type": "file",
        "name": os.path.basename(local_path),
        "subdir": subdir,
        "data_base64": base64.b64encode(data).decode("ascii"),
    }
    return await _call_phone_device(address, request)


async def _call_phone_device(address, request):
    try:
        reader, writer = await asyncio.open_connection(address, PHONE_DEVICE_PORT)
    except ConnectionRefusedError:
        return json.dumps({
            "ok": False,
            "error": f"{address} refused the connection on port {PHONE_DEVICE_PORT} — is the M-Connect app open on the phone?",
        })
    except OSError as e:
        return json.dumps({"ok": False, "error": f"connection failed: {e}"})

    writer.write((json.dumps(request) + "\n").encode("utf-8"))
    await writer.drain()

    line = await reader.readline()
    writer.close()
    await writer.wait_closed()

    if not line:
        return json.dumps({"ok": False, "error": "no response from device"})

    return line.decode("utf-8").strip()


class EngineInterface(ServiceInterface):
    def __init__(self):
        super().__init__(BUS_NAME)

    @method()
    def Discover(self) -> "a(ss)":
        return [
            [device["deviceName"], device["address"]]
            for device in devices.values()
        ]

    @method()
    async def Exec(self, address: "s", command: "s") -> "(iss)":
        return await exec_remote(address, command)

    @method()
    async def DeviceGet(self, address: "s", category: "s", field: "s", extra: "s") -> "s":
        parsed_extra = json.loads(extra) if extra else None
        return await device_get(address, category, field, parsed_extra)

    @method()
    async def DeviceSet(self, address: "s", category: "s", value: "s") -> "s":
        return await device_set(address, category, value)

    @method()
    async def DeviceFile(self, address: "s", local_path: "s", subdir: "s") -> "s":
        return await device_file(address, local_path, subdir)


async def start_dbus_service():
    bus = await MessageBus().connect()
    interface = EngineInterface()
    bus.export(OBJECT_PATH, interface)
    await bus.request_name(BUS_NAME)
    print(f"D-Bus service registered as {BUS_NAME}")
    await bus.wait_for_disconnect()


async def main():
    print(f"Local device: {DEVICE_NAME} ({DEVICE_ID})")
    print(f"Discovery on UDP {DISCOVERY_PORT}, exec on TCP {EXEC_PORT}...")

    await asyncio.gather(
        start_discovery(),
        start_exec_server(),
        start_dbus_service(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopping...")
