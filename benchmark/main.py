"""Double-click main.cmd on Windows, or run: python main.py."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
import threading
import venv
import webbrowser


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description="MetaEvolution Rescue — локальный 2D-бенчмарк")
    parser.add_argument("--port", type=int, default=8765, help="порт сервера; 0 — свободный порт")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--no-venv", action="store_true", help="использовать текущий Python")
    args = parser.parse_args()
    if sys.version_info < (3,10):
        parser.error("Нужен Python 3.10 или новее.")
    if not 0 <= args.port <= 65535:
        parser.error("Порт должен быть от 0 до 65535.")
    if not args.no_venv and sys.prefix == sys.base_prefix:
        folder = ROOT/"venv"
        python = folder/("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            print("Создаю локальное venv. Скачивать пакеты не требуется.", flush=True)
            venv.EnvBuilder(with_pip=False).create(folder)
        command = [str(python), "-B", "-X", "utf8", str(ROOT/"main.py"), "--no-venv",
                   "--port", str(args.port)]
        if args.no_browser:
            command.append("--no-browser")
        try:
            return subprocess.call(command, cwd=ROOT)
        except KeyboardInterrupt:
            return 0
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT/"main part"))
    from rescuebench.server import Server
    try:
        server = Server(("127.0.0.1",args.port))
    except OSError as error:
        if args.port and error.errno in {48,98,10048}:
            server = Server(("127.0.0.1",0))
        else:
            raise
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"\nMetaEvolution Rescue\n{url}\nОстановить сервер: Ctrl+C в этом окне.\n", flush=True)
    if not args.no_browser:
        threading.Timer(.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.app.close()
        server.server_close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ImportError) as error:
        print(f"Ошибка запуска: {error}\nПроверьте Python 3.10+ и целостность распакованной папки.", file=sys.stderr)
        raise SystemExit(1)
