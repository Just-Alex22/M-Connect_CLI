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


import sys
import time
import os
import platform
import threading
import asyncio
import json
import shutil
import textwrap
import subprocess
import atexit

from dbus_next.aio import MessageBus
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import CompleteStyle
from prompt_toolkit.styles import Style

ENGINE_BUS_NAME = "com.appleton.MConnect"
ENGINE_OBJECT_PATH = "/com/appleton/MConnect/Engine"
ENGINE_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine.py")
ENGINE_LOG_PATH = os.path.expanduser("~/.mconnect_engine.log")
HISTORY_PATH = os.path.expanduser("~/.mconnect_history")
PHONE_DEVICE_PORT = 17162
MAN_INDENT = 7

engine_process = None


class Palette:
    RESET = "\033[0m"
    BOLD = "\033[1m"

    TITLE = "\033[38;2;198;160;246m"
    TEXT = "\033[38;2;202;211;245m"
    MUTED = "\033[38;2;110;115;141m"
    ACCENT = "\033[38;2;125;196;228m"
    LINK = "\033[38;2;138;173;244m"
    SUCCESS = "\033[38;2;166;218;149m"
    ERROR = "\033[38;2;237;135;150m"
    WARNING = "\033[38;2;238;212;159m"


PROMPT_STYLE = Style.from_dict({
    "prompt-title": "bold #c6a0f6",
    "prompt-arrow": "#7dc4e4",
    "command-valid": "#a6da95",
})


def colorize(text, color):
    return f"{color}{text}{Palette.RESET}"


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def _spinner_thread(message):
    stop_event = threading.Event()

    def spin():
        chars = ['-', '/', '|', '\\']
        i = 0
        label = colorize(message, Palette.WARNING)
        while not stop_event.is_set():
            char = chars[i % len(chars)]
            sys.stdout.write(f"\r{label} {char}")
            sys.stdout.flush()
            time.sleep(0.1)
            i += 1
        sys.stdout.write(f"\r{' ' * (len(message) + 2)}\r")
        sys.stdout.flush()

    thread = threading.Thread(target=spin)
    thread.start()
    return stop_event, thread


async def with_spinner(message, coro, min_duration=0.6):
    stop_event, thread = _spinner_thread(message)
    start_time = time.time()

    try:
        return await coro
    finally:
        elapsed = time.time() - start_time
        if elapsed < min_duration:
            await asyncio.sleep(min_duration - elapsed)
        stop_event.set()
        thread.join()


class EngineUnavailable(Exception):
    pass


class ExitRequested(Exception):
    pass


class EngineClient:
    def __init__(self):
        self._bus = None
        self._interface = None

    async def _connect(self):
        self._bus = await MessageBus().connect()
        introspection = await self._bus.introspect(ENGINE_BUS_NAME, ENGINE_OBJECT_PATH)
        obj = self._bus.get_proxy_object(ENGINE_BUS_NAME, ENGINE_OBJECT_PATH, introspection)
        self._interface = obj.get_interface(ENGINE_BUS_NAME)

    async def _call(self, method_name, *args):
        last_error = None
        for attempt in range(2):
            try:
                if self._interface is None:
                    await self._connect()
                return await getattr(self._interface, method_name)(*args)
            except Exception as e:
                last_error = e
                self._bus = None
                self._interface = None
        raise EngineUnavailable(str(last_error)) from last_error

    async def discover(self):
        return await self._call("call_discover")

    async def device_get(self, address, category, field, extra=""):
        raw = await self._call("call_device_get", address, category, field, extra)
        return json.loads(raw)

    async def device_set(self, address, category, value):
        raw = await self._call("call_device_set", address, category, value)
        return json.loads(raw)

    async def device_file(self, address, local_path, subdir=""):
        raw = await self._call("call_device_file", address, local_path, subdir)
        return json.loads(raw)


def stop_engine():
    global engine_process
    if engine_process and engine_process.poll() is None:
        engine_process.terminate()
        try:
            engine_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            engine_process.kill()


async def ensure_engine(client):
    global engine_process

    try:
        await client.discover()
        return True
    except EngineUnavailable:
        pass

    if not os.path.exists(ENGINE_SCRIPT):
        print(colorize(f"No se encontró engine.py en {ENGINE_SCRIPT}, iniciálo manualmente", Palette.ERROR))
        return False

    log_file = open(ENGINE_LOG_PATH, "a")
    engine_process = subprocess.Popen(
        [sys.executable, ENGINE_SCRIPT],
        stdout=log_file,
        stderr=log_file,
    )
    atexit.register(stop_engine)

    for _ in range(20):
        try:
            await client.discover()
            return True
        except EngineUnavailable:
            pass
        if engine_process.poll() is not None:
            print(colorize(f"engine.py se cerró antes de tiempo, revisá {ENGINE_LOG_PATH}", Palette.ERROR))
            return False
        await asyncio.sleep(0.25)

    print(colorize(f"engine.py no arrancó a tiempo, revisá {ENGINE_LOG_PATH}", Palette.ERROR))
    return False


async def probe_device(address, port=PHONE_DEVICE_PORT, timeout=2.0):
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(address, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


def get_python_version():
    return platform.python_version()


def print_splash():
    clear_screen()
    print(colorize("\nM-Connect CLI v0.0-demo", Palette.BOLD + Palette.TITLE))
    print(colorize("Copyright (C) 2025-2026 Appleton S.A. & Co.\n", Palette.MUTED))
    print(colorize("Código fuente: ", Palette.MUTED) + colorize("https://github.com/Just-Alex22/M-Connect_CLI", Palette.LINK))
    print(colorize("Documentación: ", Palette.MUTED) + colorize("https://github.com/Just-Alex22/M-Connect_CLI/wiki\n", Palette.LINK))
    print(colorize("Este programa es software libre: usted puede redistribuirlo y/o modificarlo bajo los términos de la \nLicencia Pública General de GNU publicada por la Free Software Foundation, ya sea la versión 3 de \nla Licencia, o (a su elección) cualquier versión posterior...\n", Palette.MUTED))
    print(colorize("M-Connect se distribuye SIN NINGUNA GARANTÍA, en la medida permitida por la ley aplicable.\n\n", Palette.MUTED))


STATE_COLORS = {
    "disponible": Palette.SUCCESS,
    "no disponible": Palette.ERROR,
    "conectado": Palette.SUCCESS,
}


def colorize_cell(header, value):
    if header.upper() == "ESTADO":
        color = STATE_COLORS.get(value.lower(), Palette.WARNING)
        return colorize(value, color)
    return colorize(value, Palette.TEXT)


def print_table(headers, rows):
    widths = [len(header) for header in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    header_line = "  ".join(
        colorize(header.ljust(widths[i]), Palette.BOLD + Palette.ACCENT)
        for i, header in enumerate(headers)
    )
    print(header_line)

    for row in rows:
        cells = []
        for i, cell in enumerate(row):
            colored = colorize_cell(headers[i], cell) + " " * (widths[i] - len(cell))
            cells.append(colored)
        print("  ".join(cells))

CATEGORY_TO_WIRE = {
    "bateria": "battery",
    "volumen": "volume",
    "multimedia": "multimedia",
    "dispositivo": "device",
    "almacenamiento": "storage",
    "notificaciones": "notifications",
    "encontrar": "find",
}

MULTIMEDIA_VALUE_TO_WIRE = {
    "reproducir": "play",
    "pausar": "pause",
    "siguiente": "next",
    "anterior": "previous",
}

DEVICE_GET_FIELDS = {
    "bateria": {
        "porcentaje-actual": "Nivel de carga de la batería, en porcentaje.",
    },
    "volumen": {
        "porcentaje-actual": "Nivel de volumen multimedia, en porcentaje.",
    },
    "multimedia": {
        "reproduciendo-actual": "Título, artista, estado y fuente del reproductor activo.",
    },
    "dispositivo": {
        "informacion": "Modelo, fabricante y versión de Android.",
    },
    "almacenamiento": {
        "espacio-libre": "Espacio libre en el almacenamiento interno del dispositivo, en MB.",
    },
    "notificaciones": {
        "actual": "Las notificaciones que se muestran actualmente en el celular.",
    },
}

DEVICE_SET_VALUES = {
    "volumen": {
        "usage": "<0-100>",
        "choices": [],
        "description": "Ajusta el volumen multimedia, en porcentaje.",
    },
    "multimedia": {
        "usage": "reproducir|pausar|siguiente|anterior",
        "choices": ["reproducir", "pausar", "siguiente", "anterior"],
        "description": "Controla el reproductor multimedia activo.",
    },
    "encontrar": {
        "usage": "sonar",
        "choices": ["sonar"],
        "description": "Hace sonar el dispositivo al volumen máximo de alarma y vibra 10 segundos.",
    },
}

COMMAND_DOCS = {
    "ayuda": {
        "synopsis": ["ayuda [comando]"],
        "summary": "muestra el manual, o la página de un comando",
        "description": [
            "Sin argumentos, imprime la lista de comandos disponibles. Si se da un nombre de comando, imprime su sinopsis, descripción y ejemplos de uso.",
            "Presioná TAB en cualquier momento para completar nombres de comandos y argumentos, y usá las flechas ARRIBA y ABAJO para navegar comandos anteriores.",
        ],
        "sections": [],
        "examples": [
            ("ayuda obtener-dispositivo", "Muestra la página de manual de obtener-dispositivo."),
        ],
    },
    "descubrir": {
        "synopsis": ["descubrir"],
        "summary": "lista los dispositivos que se anuncian en la red",
        "description": [
            "Le pregunta al engine de M-Connect qué dispositivos escuchó en la red local. Un dispositivo desaparece de la lista unos segundos después de dejar de anunciarse.",
            "El engine (engine.py) arranca automáticamente cuando se inicia la CLI.",
        ],
        "sections": [],
        "examples": [
            ("descubrir", "Imprime una tabla con el nombre y la dirección de cada dispositivo encontrado."),
        ],
    },
    "conectar": {
        "synopsis": ["conectar <ip>"],
        "summary": "selecciona y verifica el dispositivo con el que hablan los comandos siguientes",
        "description": [
            f"Verifica que <ip> sea realmente alcanzable en el puerto {PHONE_DEVICE_PORT} (donde escucha la app M-Connect), y recién ahí lo guarda como dispositivo activo. Su dirección se muestra en el prompt y la usan obtener-dispositivo y ajustar-dispositivo hasta que se seleccione otro.",
            "Después de correr descubrir, TAB completa las direcciones encontradas.",
        ],
        "sections": [],
        "examples": [
            ("conectar 192.168.1.57", "Conecta al dispositivo en 192.168.1.57."),
        ],
    },
    "obtener-dispositivo": {
        "synopsis": ["obtener-dispositivo <categoria> <campo>"],
        "summary": "lee un valor del dispositivo conectado",
        "description": [
            "Consulta al dispositivo conectado e imprime cada valor que reporte. La app M-Connect tiene que estar abierta en el dispositivo.",
            "La categoría multimedia también requiere que la app tenga el permiso de Acceso a Notificaciones concedido en el dispositivo.",
        ],
        "sections": [
            (
                "CATEGORÍAS",
                [
                    (f"{category} {field}", description)
                    for category, fields in DEVICE_GET_FIELDS.items()
                    for field, description in fields.items()
                ],
            ),
        ],
        "examples": [
            ("obtener-dispositivo bateria porcentaje-actual", "Imprime el nivel de batería."),
            ("obtener-dispositivo multimedia reproduciendo-actual", "Imprime qué se está reproduciendo en el dispositivo."),
        ],
    },
    "ajustar-dispositivo": {
        "synopsis": ["ajustar-dispositivo <categoria> <valor>"],
        "summary": "cambia un ajuste en el dispositivo conectado",
        "description": [
            "Envía un cambio al celular conectado. La app M-Connect tiene que estar abierta en el dispositivo.",
            "La categoría multimedia también requiere que la app tenga el permiso de Acceso a Notificaciones concedido en el dispositivo.",
        ],
        "sections": [
            (
                "CATEGORÍAS",
                [
                    (f"{category} {spec['usage']}", spec["description"])
                    for category, spec in DEVICE_SET_VALUES.items()
                ],
            ),
        ],
        "examples": [
            ("ajustar-dispositivo volumen 40", "Pone el volumen multimedia en 40%."),
            ("ajustar-dispositivo multimedia pausar", "Pausa el reproductor multimedia activo."),
        ],
    },
    "vigilar-dispositivo": {
        "synopsis": ["vigilar-dispositivo notificaciones"],
        "summary": "muestra eventos en vivo del dispositivo conectado",
        "description": [
            "Abre una conexión directa al celular e imprime cada notificación nueva a medida que llega, hasta que se presiona Ctrl+C.",
            "Requiere que la app tenga el permiso de Acceso a Notificaciones concedido en el dispositivo.",
        ],
        "sections": [],
        "examples": [
            ("vigilar-dispositivo notificaciones", "Imprime cada notificación nueva a medida que llega."),
        ],
    },
    "enviar-archivo": {
        "synopsis": ["enviar-archivo <ruta-local> [subcarpeta]"],
        "summary": "envía un archivo de esta PC al dispositivo conectado",
        "description": [
            "Lee <ruta-local> en esta PC y lo guarda en el celular bajo Download/M-Connect, o Download/M-Connect/<subcarpeta> si se indica.",
            "Requiere Android 10 o superior en el dispositivo.",
        ],
        "sections": [],
        "examples": [
            ("enviar-archivo ~/Imagenes/foto.jpg", "Guarda foto.jpg en Download/M-Connect en el dispositivo."),
            ("enviar-archivo ~/informe.pdf trabajo", "Lo guarda en Download/M-Connect/trabajo en su lugar."),
        ],
    },
    "limpiar": {
        "synopsis": ["limpiar"],
        "summary": "limpia la pantalla de la terminal",
        "description": ["Limpia la pantalla y deja el prompt arriba de todo."],
        "sections": [],
        "examples": [],
    },
    "salir": {
        "synopsis": ["salir"],
        "summary": "cierra M-Connect",
        "description": ["Cierra la shell de M-Connect. Presionar Ctrl+C tiene el mismo efecto."],
        "sections": [],
        "examples": [],
    },
}

COMMANDS = list(COMMAND_DOCS.keys())


def terminal_width():
    return max(48, min(shutil.get_terminal_size((80, 24)).columns, 100))


def man_header(name):
    width = terminal_width()
    edge = f"{name.upper()}(1)"
    middle = "Manual de M-Connect".center(max(width - 2 * len(edge), 0))
    return colorize(edge + middle + edge, Palette.MUTED)


def print_heading(text):
    print()
    print(colorize(text, Palette.BOLD + Palette.ACCENT))


def print_paragraph(text):
    width = terminal_width() - MAN_INDENT
    for line in textwrap.wrap(text, width):
        print(" " * MAN_INDENT + colorize(line, Palette.TEXT))
    print()


def print_rows(rows):
    left_width = max(len(left) for left, _ in rows)
    right_width = max(terminal_width() - MAN_INDENT - left_width - 3, 20)
    for left, right in rows:
        wrapped = textwrap.wrap(right, right_width) or [""]
        print(
            " " * MAN_INDENT
            + colorize(left.ljust(left_width), Palette.TITLE)
            + "   "
            + colorize(wrapped[0], Palette.TEXT)
        )
        for continuation in wrapped[1:]:
            print(" " * (MAN_INDENT + left_width + 3) + colorize(continuation, Palette.TEXT))


def print_overview():
    print()
    print(man_header("m-connect"))
    print_heading("SINOPSIS")
    print(" " * MAN_INDENT + colorize("<comando> [argumentos]", Palette.TITLE))
    print_heading("COMANDOS")
    print_rows([(doc["synopsis"][0], doc["summary"]) for doc in COMMAND_DOCS.values()])
    print()
    print(colorize("Escribí 'ayuda <comando>' para ver la página de manual de un comando.", Palette.MUTED))


def print_command_page(name):
    doc = COMMAND_DOCS[name]
    print()
    print(man_header(name))
    print_heading("SINOPSIS")
    for line in doc["synopsis"]:
        print(" " * MAN_INDENT + colorize(line, Palette.TITLE))
    print_heading("DESCRIPCIÓN")
    for paragraph in doc["description"]:
        print_paragraph(paragraph)
    for title, rows in doc["sections"]:
        print_heading(title)
        print_rows(rows)
    if doc["examples"]:
        print_heading("EJEMPLOS")
        print_rows(doc["examples"])
    print()


def print_usage(name):
    synopsis = COMMAND_DOCS[name]["synopsis"][0]
    print(colorize("Uso: ", Palette.MUTED) + colorize(synopsis, Palette.TEXT))
    print(colorize(f"Escribe 'ayuda {name}' para más detalles.", Palette.MUTED))


def print_engine_unavailable(error):
    print(colorize(f"No se pudo contactar al engine: {error}", Palette.ERROR))
    print(colorize("¿Está corriendo engine.py?", Palette.MUTED))


def require_connection(state):
    address = state.get("connected_address")
    if not address:
        print(colorize("No estás conectado. Usa 'conectar <ip>' primero.", Palette.ERROR))
    return address


async def handle_help(args, state):
    if not args:
        print_overview()
        return

    name = args[0].lower()
    if name not in COMMAND_DOCS:
        print(colorize(f"No hay entrada de manual para {args[0]}", Palette.ERROR))
        return

    print_command_page(name)


async def handle_discover(args, state):
    try:
        devices = await with_spinner("Descubriendo dispositivos...", state["engine"].discover())
    except EngineUnavailable as e:
        print_engine_unavailable(e)
        return

    state["known_addresses"] = [address for _, address in devices]

    if not devices:
        print(colorize("No se encontraron dispositivos", Palette.MUTED))
        return

    headers = ["NOMBRE", "DIRECCIÓN", "ESTADO"]
    rows = [[name, address, "disponible"] for name, address in devices]
    print_table(headers, rows)


async def handle_connect(args, state):
    if len(args) != 1:
        print_usage("conectar")
        return

    ip = args[0]
    reachable = await with_spinner(f"Conectando a {ip}...", probe_device(ip))

    if not reachable:
        print(colorize(
            f"No se pudo contactar a {ip} en el puerto {PHONE_DEVICE_PORT}, ¿está abierta la app M-Connect en el dispositivo?",
            Palette.ERROR,
        ))
        return

    state["connected_address"] = ip
    print(colorize(f"Conectado a {ip}", Palette.SUCCESS))


async def handle_clear(args, state):
    clear_screen()


async def handle_exit(args, state):
    print("Saliendo...")
    raise ExitRequested()


async def handle_device_get(args, state):
    if len(args) != 2:
        print_usage("obtener-dispositivo")
        return

    category, field = args
    if category not in DEVICE_GET_FIELDS:
        available = ", ".join(DEVICE_GET_FIELDS)
        print(colorize(f"Categoría desconocida '{category}'. Disponibles: {available}", Palette.ERROR))
        return

    if field not in DEVICE_GET_FIELDS[category]:
        available = ", ".join(DEVICE_GET_FIELDS[category])
        print(colorize(f"Campo desconocido '{field}' para {category}. Disponibles: {available}", Palette.ERROR))
        return

    address = require_connection(state)
    if not address:
        return

    wire_category = CATEGORY_TO_WIRE[category]

    try:
        result = await with_spinner(
            f"Consultando {category}...", state["engine"].device_get(address, wire_category, field)
        )
    except EngineUnavailable as e:
        print_engine_unavailable(e)
        return

    if not result.get("ok"):
        print(colorize(result.get("error", "error desconocido"), Palette.ERROR))
        return

    for key, value in result.items():
        if key in ("type", "ok"):
            continue

        if key == "notifications" and isinstance(value, list):
            if not value:
                print(colorize("notificaciones: ninguna", Palette.ACCENT))
                continue
            print(colorize("notificaciones:", Palette.ACCENT))
            for item in value:
                source = item.get("source", "?")
                title = item.get("title", "")
                text = item.get("text", "")
                print(colorize(f"  [{source}] ", Palette.ACCENT) + colorize(title, Palette.TITLE))
                if text:
                    print(colorize(f"    {text}", Palette.TEXT))
            continue

        print(colorize(f"{key}: ", Palette.ACCENT) + colorize(str(value), Palette.TEXT))


def is_valid_set_value(category, value):
    spec = DEVICE_SET_VALUES[category]
    if spec["choices"]:
        return value in spec["choices"]
    if category == "volumen":
        return value.isdigit() and 0 <= int(value) <= 100
    return True


async def handle_device_set(args, state):
    if len(args) < 2:
        print_usage("ajustar-dispositivo")
        return

    category = args[0]
    value = " ".join(args[1:])

    if category not in DEVICE_SET_VALUES:
        available = ", ".join(DEVICE_SET_VALUES)
        print(colorize(f"Categoría desconocida '{category}'. Disponibles: {available}", Palette.ERROR))
        return

    if not is_valid_set_value(category, value):
        expected = DEVICE_SET_VALUES[category]["usage"]
        print(colorize(f"Valor inválido '{value}' para {category}. Esperado: {expected}", Palette.ERROR))
        return

    address = require_connection(state)
    if not address:
        return

    wire_category = CATEGORY_TO_WIRE[category]
    wire_value = MULTIMEDIA_VALUE_TO_WIRE.get(value, value) if category == "multimedia" else value

    try:
        result = await with_spinner(
            f"Ajustando {category}...", state["engine"].device_set(address, wire_category, wire_value)
        )
    except EngineUnavailable as e:
        print_engine_unavailable(e)
        return

    if result.get("ok"):
        print(colorize("Listo", Palette.SUCCESS))
    else:
        print(colorize(result.get("error", "error desconocido"), Palette.ERROR))


async def watch_notifications(address):
    reader, writer = await asyncio.open_connection(address, PHONE_DEVICE_PORT)
    request = {"type": "watch", "category": "notifications"}
    writer.write((json.dumps(request) + "\n").encode("utf-8"))
    await writer.drain()

    try:
        while True:
            line = await reader.readline()
            if not line:
                print(colorize("El dispositivo cerró la conexión.", Palette.MUTED))
                return

            event = json.loads(line.decode("utf-8").strip())

            if not event.get("ok", True):
                print(colorize(event.get("error", "error desconocido"), Palette.ERROR))
                return

            source = event.get("source", "?")
            title = event.get("title", "")
            text = event.get("text", "")
            print(colorize(f"[{source}] ", Palette.ACCENT) + colorize(title, Palette.TITLE))
            if text:
                print(colorize(f"  {text}", Palette.TEXT))
    finally:
        writer.close()


async def handle_device_watch(args, state):
    if len(args) != 1 or args[0] != "notificaciones":
        print_usage("vigilar-dispositivo")
        return

    address = require_connection(state)
    if not address:
        return

    print(colorize("Mirando notificaciones. Presiona Ctrl+C para detener.", Palette.MUTED))
    try:
        await watch_notifications(address)
    except (OSError, ConnectionError) as e:
        print(colorize(f"No se pudo observar: {e}", Palette.ERROR))
    except KeyboardInterrupt:
        print(colorize("\nSe detuvo la observación.", Palette.MUTED))


async def handle_file_send(args, state):
    if len(args) not in (1, 2):
        print_usage("enviar-archivo")
        return

    local_path = os.path.expanduser(args[0])
    subdir = args[1] if len(args) == 2 else ""

    if not os.path.isfile(local_path):
        print(colorize(f"No existe el archivo: {local_path}", Palette.ERROR))
        return

    address = require_connection(state)
    if not address:
        return

    try:
        result = await with_spinner(
            f"Enviando {os.path.basename(local_path)}...",
            state["engine"].device_file(address, local_path, subdir),
        )
    except EngineUnavailable as e:
        print_engine_unavailable(e)
        return

    if result.get("ok"):
        print(colorize("Listo", Palette.SUCCESS))
    else:
        print(colorize(result.get("error", "error desconocido"), Palette.ERROR))


HANDLERS = {
    "ayuda": handle_help,
    "descubrir": handle_discover,
    "conectar": handle_connect,
    "obtener-dispositivo": handle_device_get,
    "ajustar-dispositivo": handle_device_set,
    "vigilar-dispositivo": handle_device_watch,
    "enviar-archivo": handle_file_send,
    "limpiar": handle_clear,
    "salir": handle_exit,
}


class CommandLexer(Lexer):
    def lex_document(self, document):
        def get_line(lineno):
            line = document.lines[lineno]
            stripped = line.lstrip()
            if lineno != 0 or not stripped:
                return [("", line)]

            leading = line[: len(line) - len(stripped)]
            first, separator, rest = stripped.partition(" ")
            style = "class:command-valid" if first.lower() in COMMANDS else ""
            return [("", leading), (style, first), ("", separator + rest)]

        return get_line


class CommandCompleter(Completer):
    def __init__(self, state):
        self.state = state

    def argument_candidates(self, command, completed):
        position = len(completed)

        if command == "ayuda" and position == 0:
            return COMMANDS

        if command == "conectar" and position == 0:
            return self.state.get("known_addresses", [])

        if command == "obtener-dispositivo":
            if position == 0:
                return list(DEVICE_GET_FIELDS)
            if position == 1:
                return list(DEVICE_GET_FIELDS.get(completed[0], {}))

        if command == "ajustar-dispositivo":
            if position == 0:
                return list(DEVICE_SET_VALUES)
            if position == 1:
                return DEVICE_SET_VALUES.get(completed[0], {}).get("choices", [])

        if command == "vigilar-dispositivo" and position == 0:
            return ["notificaciones"]

        return []

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        words = text.split()
        starting_new_word = text == "" or text[-1].isspace()

        if starting_new_word:
            completed, prefix = words, ""
        else:
            completed, prefix = words[:-1], words[-1]

        if not completed:
            candidates = COMMANDS
        else:
            candidates = self.argument_candidates(completed[0].lower(), completed[1:])

        for candidate in candidates:
            if candidate.lower().startswith(prefix.lower()):
                yield Completion(candidate, start_position=-len(prefix))


def history_backend():
    home = os.path.dirname(HISTORY_PATH)
    if os.access(home, os.W_OK):
        return FileHistory(HISTORY_PATH)
    return InMemoryHistory()


def create_session(state, history=None):
    return PromptSession(
        history=history if history is not None else history_backend(),
        completer=CommandCompleter(state),
        lexer=CommandLexer(),
        style=PROMPT_STYLE,
        complete_style=CompleteStyle.READLINE_LIKE,
        complete_while_typing=False,
    )


def prompt_fragments(state, version):
    connected = state["connected_address"]
    suffix = f" [{connected}]" if connected else ""
    return [
        ("class:prompt-title", f"M-Connect vía \U0001F40D {version}{suffix}"),
        ("", "\n"),
        ("class:prompt-arrow", "❯ "),
    ]


async def run_repl(session, state, version):
    while True:
        try:
            line = (await session.prompt_async(lambda: prompt_fragments(state, version))).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSaliendo...")
            break

        if not line:
            continue

        parts = line.split()
        command, args = parts[0].lower(), parts[1:]

        handler = HANDLERS.get(command)
        if handler is None:
            print(colorize(f"Comando desconocido: {command} (usa 'ayuda')", Palette.ERROR))
            continue

        try:
            await handler(args, state)
        except ExitRequested:
            break


async def async_main():
    client = EngineClient()
    ok = await with_spinner("Inicializando..", ensure_engine(client), min_duration=0.3)

    print_splash()
    await asyncio.sleep(3.0)

    if not ok:
        print(colorize(
            "Continuando sin el engine, los comandos que lo necesiten van a fallar hasta que esté disponible.",
            Palette.MUTED,
        ))

    state = {"connected_address": None, "known_addresses": [], "engine": client}
    session = create_session(state)
    await run_repl(session, state, get_python_version())


def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
