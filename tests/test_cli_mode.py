from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.argv[0] = str(ROOT / "main.py")

import settings as settings_module
import main
from headless import GUIManager


class DummyTwitch:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_parse_args_cli_flag_sets_mode() -> None:
    args = main.parse_args(["--cli", "--log", "-vv"])
    assert args.cli is True
    assert args.log is True
    assert args.logging_level == main.LOGGING_LEVELS[2]


def test_parse_args_supports_headless_overrides() -> None:
    args = main.parse_args(
        [
            "--cli",
            "--priority",
            "Rust, VALORANT",
            "--exclude",
            "Hearthstone, Dota 2",
            "--priority-mode",
            "low-availability-first",
            "--available-drops-check",
            "--connection-quality",
            "4",
        ]
    )
    assert args.priority == "Rust, VALORANT"
    assert args.exclude == "Hearthstone, Dota 2"
    assert args.priority_mode == "low-availability-first"
    assert args.available_drops_check is True
    assert args.connection_quality == 4


def test_settings_apply_cli_overrides() -> None:
    args = main.parse_args(
        [
            "--cli",
            "--priority",
            "Rust, VALORANT",
            "--exclude",
            "Hearthstone, Dota 2",
            "--priority-mode",
            "ending-soonest",
            "--no-available-drops-check",
            "--connection-quality",
            "5",
        ]
    )
    settings = settings_module.Settings(args)
    assert settings.priority == ["Rust", "VALORANT"]
    assert settings.exclude == {"Hearthstone", "Dota 2"}
    assert settings.priority_mode is settings_module.PriorityMode.ENDING_SOONEST
    assert settings.available_drops_check is False
    assert settings.connection_quality == 5


def test_headless_gui_close_sets_event_and_notifies_twitch() -> None:
    twitch = DummyTwitch()
    gui = GUIManager(twitch)

    assert gui.close_requested is False
    gui.close()

    assert gui.close_requested is True
    assert twitch.closed is True


def test_headless_wait_until_closed_blocks_until_close() -> None:
    import asyncio

    twitch = DummyTwitch()
    gui = GUIManager(twitch)

    async def runner() -> bool:
        waiter = asyncio.create_task(gui.wait_until_closed())
        await asyncio.sleep(0.01)
        assert waiter.done() is False
        gui.close()
        await asyncio.wait_for(waiter, timeout=1)
        return True

    assert asyncio.run(runner()) is True


def test_headless_tray_notify_is_available() -> None:
    twitch = DummyTwitch()
    gui = GUIManager(twitch)
    gui.tray.notify("title", "message")


def test_daemon_artifacts_exist_and_reference_headless_runner() -> None:
    runner = ROOT / "run_headless.sh"
    env_example = ROOT / "contrib" / "twitchdropsminer.env.example"
    service = ROOT / "contrib" / "twitchdropsminer@.service"
    readme = ROOT / "README.md"

    assert runner.exists()
    assert env_example.exists()
    assert service.exists()
    assert "ExecStart=/opt/twitchdropsminer/run_headless.sh" in service.read_text()
    assert "TDM_PRIORITY_MODE=priority-only" in env_example.read_text()
    assert "./run_headless.sh" in readme.read_text()


def test_cli_version_runs_without_gui() -> None:
    result = subprocess.run(
        [sys.executable, "main.py", "--cli", "--version"],
        cwd="/tmp/TwitchDropsMiner",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip().startswith("v")
