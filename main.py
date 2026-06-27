from __future__ import annotations

from multiprocessing import freeze_support

import argparse
import asyncio
import io
import logging
import signal
import sys
import traceback
import warnings
from typing import NoReturn

from constants import FILE_FORMATTER, LOCK_PATH, LOGGING_LEVELS, LOG_PATH, SELF_PATH
from exceptions import CaptchaRequired
from settings import Settings
from translate import _
from twitch import Twitch
from utils import lock_file
from version import __version__

warnings.simplefilter("default", ResourceWarning)

if sys.version_info < (3, 10):
    raise RuntimeError("Python 3.10 or higher is required")


class ParsedArgs(argparse.Namespace):
    _verbose: int
    _debug_ws: bool
    _debug_gql: bool
    log: bool
    tray: bool
    dump: bool
    cli: bool
    priority: str | None
    exclude: str | None
    priority_mode: str | None
    available_drops_check: bool | None
    connection_quality: int | None

    @property
    def logging_level(self) -> int:
        return LOGGING_LEVELS[min(self._verbose, 4)]

    @property
    def debug_ws(self) -> int:
        if self._debug_ws:
            return logging.DEBUG
        if self._verbose >= 4:
            return logging.INFO
        return logging.NOTSET

    @property
    def debug_gql(self) -> int:
        if self._debug_gql:
            return logging.DEBUG
        if self._verbose >= 4:
            return logging.INFO
        return logging.NOTSET


class GUIParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._message = io.StringIO()

    def _print_message(self, message: str, file=None) -> None:
        self._message.write(message)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        try:
            super().exit(status, message)
        finally:
            from tkinter import messagebox

            messagebox.showerror("Argument Parser Error", self._message.getvalue())


def build_parser(*, cli_mode: bool) -> argparse.ArgumentParser:
    parser_cls = argparse.ArgumentParser if cli_mode else GUIParser
    parser = parser_cls(
        SELF_PATH.name,
        description="A program that allows you to mine timed drops on Twitch.",
    )
    parser.add_argument("--version", action="version", version=f"v{__version__}")
    parser.add_argument("-v", dest="_verbose", action="count", default=0)
    parser.add_argument("--tray", action="store_true")
    parser.add_argument("--log", action="store_true")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--cli", action="store_true", help="run without Tk GUI using terminal logging")
    parser.add_argument(
        "--priority",
        help="comma-separated game names to prioritize in headless mode, e.g. 'Rust,VALORANT'",
    )
    parser.add_argument(
        "--exclude",
        help="comma-separated game names to exclude in headless mode",
    )
    parser.add_argument(
        "--priority-mode",
        choices=("priority-only", "ending-soonest", "low-availability-first"),
        help="override mining order for games outside the priority list",
    )
    parser.add_argument(
        "--available-drops-check",
        dest="available_drops_check",
        action="store_true",
        default=None,
        help="enable extra available drops validation",
    )
    parser.add_argument(
        "--no-available-drops-check",
        dest="available_drops_check",
        action="store_false",
        help="disable extra available drops validation",
    )
    parser.add_argument(
        "--connection-quality",
        type=int,
        choices=range(1, 7),
        metavar="{1,2,3,4,5,6}",
        help="override network timeout multiplier (1=fastest, 6=slowest)",
    )
    parser.add_argument("--debug-ws", dest="_debug_ws", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--debug-gql", dest="_debug_gql", action="store_true", help=argparse.SUPPRESS)
    return parser


def parse_args(argv: list[str] | None = None) -> ParsedArgs:
    argv = list(sys.argv[1:] if argv is None else argv)
    cli_mode = "--cli" in argv
    if not cli_mode:
        from tkinter import Tk

        from utils import resource_path, set_root_icon

        root = Tk()
        root.overrideredirect(True)
        root.withdraw()
        set_root_icon(root, resource_path("icons/pickaxe.ico"))
        root.update()
    parser = build_parser(cli_mode=cli_mode)
    try:
        args = parser.parse_args(argv, namespace=ParsedArgs())
    finally:
        if not cli_mode:
            root.destroy()
    return args


def configure_logging(settings: Settings) -> logging.Logger:
    if settings.logging_level > logging.DEBUG:
        logging.getLogger().addHandler(logging.NullHandler())
    logger = logging.getLogger("TwitchDrops")
    logger.setLevel(settings.logging_level)
    if settings.log:
        handler = logging.FileHandler(LOG_PATH)
        handler.setFormatter(FILE_FORMATTER)
        logger.addHandler(handler)
    logging.getLogger("TwitchDrops.gql").setLevel(settings.debug_gql)
    logging.getLogger("TwitchDrops.websocket").setLevel(settings.debug_ws)
    if settings.cli:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(stream_handler)
    return logger


async def run_client(settings: Settings) -> int:
    client = Twitch(settings)
    loop = asyncio.get_running_loop()
    if sys.platform == "linux":
        loop.add_signal_handler(signal.SIGINT, lambda *_: client.gui.close())
        loop.add_signal_handler(signal.SIGTERM, lambda *_: client.gui.close())

    exit_status = 0
    try:
        await client.run()
    except CaptchaRequired:
        exit_status = 1
        client.prevent_close()
        client.print(_("error", "captcha"))
    except Exception:
        exit_status = 1
        client.prevent_close()
        client.print("Fatal error encountered:\n")
        client.print(traceback.format_exc())
    finally:
        if sys.platform == "linux":
            loop.remove_signal_handler(signal.SIGINT)
            loop.remove_signal_handler(signal.SIGTERM)
        client.print(_("gui", "status", "exiting"))
        await client.shutdown()

    if not client.gui.close_requested and not settings.cli:
        client.gui.tray.change_icon("error")
        client.print(_("status", "terminated"))
        client.gui.status.update(_("gui", "status", "terminated"))
        client.gui.grab_attention(sound=True)

    if not settings.cli:
        await client.gui.wait_until_closed()
    client.save(force=True)
    client.gui.stop()
    client.gui.close_window()
    return exit_status


def main(argv: list[str] | None = None) -> int:
    freeze_support()
    try:
        import truststore
    except ModuleNotFoundError:
        truststore = None
    else:
        truststore.inject_into_ssl()
    args = parse_args(argv)
    try:
        settings = Settings(args)
    except Exception:
        if args.cli:
            print("Settings error:\n", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
        else:
            from tkinter import messagebox

            messagebox.showerror(
                "Settings error",
                f"There was an error while loading the settings file:\n\n{traceback.format_exc()}"
            )
        return 4

    configure_logging(settings)
    success, file = lock_file(LOCK_PATH)
    if not success:
        return 3
    try:
        import asyncio

        return asyncio.run(run_client(settings))
    finally:
        file.close()


if __name__ == "__main__":
    raise SystemExit(main())
