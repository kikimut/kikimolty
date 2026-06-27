from __future__ import annotations

import asyncio
import logging
import webbrowser
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from yarl import URL

from exceptions import ExitRequest

if TYPE_CHECKING:
    from channel import Channel
    from inventory import DropsCampaign, TimedDrop
    from twitch import Twitch
    from utils import Game

logger = logging.getLogger("TwitchDrops")


class _StatusBar:
    def __init__(self) -> None:
        self.value = ""

    def update(self, text: str) -> None:
        self.value = text
        logger.info(text)

    def clear(self) -> None:
        self.value = ""


class _TrayIcon:
    def __init__(self) -> None:
        self.icon = "pickaxe"
        self.title = ""

    def change_icon(self, icon: str) -> None:
        self.icon = icon

    def update_title(self, drop: TimedDrop | None) -> None:
        self.title = "" if drop is None else drop.rewards_text()

    def notify(self, title: str, message: str, *, duration: int = 10) -> None:
        logger.info("%s: %s", title, message)

    def stop(self) -> None:
        return None

    def restore(self) -> None:
        return None

    def minimize(self) -> None:
        return None


class _Progress:
    ALMOST_DONE_SECONDS = 10

    def __init__(self) -> None:
        self._drop: TimedDrop | None = None
        self._seconds = 0
        self._timer_task: asyncio.Task[None] | None = None

    def _update_seconds(self, seconds: int) -> None:
        self._seconds = max(seconds, 0)

    async def _timer_loop(self) -> None:
        self._update_seconds(60)
        while self._seconds > 0:
            await asyncio.sleep(1)
            self._seconds -= 1
        self._timer_task = None

    def display(self, drop: TimedDrop | None, *, countdown: bool = True, subone: bool = False) -> None:
        self.stop_timer()
        self._drop = drop
        if drop is None:
            self._update_seconds(0)
            return
        if countdown:
            self.start_timer()
        elif subone:
            self._update_seconds(0)
        else:
            self._update_seconds(60)
        logger.info(
            "Drop progress: campaign=%s drop=%s campaign_progress=%.1f%% drop_progress=%.1f%%",
            drop.campaign.name,
            drop.rewards_text(),
            drop.campaign.progress * 100,
            drop.progress * 100,
        )

    def start_timer(self) -> None:
        if self._timer_task is None:
            self._timer_task = asyncio.create_task(self._timer_loop())

    def stop_timer(self) -> None:
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def minute_almost_done(self) -> bool:
        return self._timer_task is None or self._seconds <= self.ALMOST_DONE_SECONDS


class _ConsoleOutput:
    def print(self, message: str) -> None:
        logger.info(message)


class _ChannelList:
    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}
        self._watching: str | None = None

    def clear_watching(self) -> None:
        self._watching = None

    def set_watching(self, channel: Channel) -> None:
        self._watching = channel.iid
        logger.info("Watching channel: %s", channel.name)

    def get_selection(self) -> Channel | None:
        return None

    def clear_selection(self) -> None:
        return None

    def clear(self) -> None:
        self._channels.clear()
        self._watching = None

    def display(self, channel: Channel, *, add: bool = False) -> None:
        self._channels[channel.iid] = channel
        if add:
            logger.info("Channel added: %s", channel.name)


class _InventoryOverview:
    def __init__(self) -> None:
        self._campaigns: dict[str, DropsCampaign] = {}

    def clear(self) -> None:
        self._campaigns.clear()

    async def add_campaign(self, campaign: DropsCampaign) -> None:
        self._campaigns[campaign.id] = campaign
        logger.info("Campaign available: %s", campaign.name)

    def update_drop(self, drop: TimedDrop) -> None:
        self._campaigns[drop.campaign.id] = drop.campaign

    def configure_theme(self, **_: Any) -> None:
        return None


class _WebsocketStatus:
    def __init__(self) -> None:
        self._entries: dict[int, dict[str, Any]] = {}

    def update(self, idx: int, *, status: str | None = None, topics: int | None = None) -> None:
        entry = self._entries.setdefault(idx, {})
        if status is not None:
            entry["status"] = status
        if topics is not None:
            entry["topics"] = topics

    def remove(self, idx: int) -> None:
        self._entries.pop(idx, None)


class _SettingsPanel:
    def __init__(self) -> None:
        self.games: set[str] = set()

    def set_games(self, games: set[Game]) -> None:
        self.games = {game.name for game in games}

    def clear_selection(self) -> None:
        return None


@dataclass
class LoginData:
    username: str
    password: str
    token: str = ""


class _LoginForm:
    def __init__(self) -> None:
        self.status = ""
        self.user_id: int | None = None

    def clear(self, login: bool = False, password: bool = False, token: bool = False) -> None:
        return None

    async def ask_login(self) -> LoginData:
        raise RuntimeError("Interactive username/password login is not supported in --cli mode. Use device-code login.")

    async def ask_enter_code(self, page_url: URL, user_code: str) -> None:
        logger.info("Open this URL in your browser: %s", page_url)
        logger.info("Enter this Twitch device code: %s", user_code)
        try:
            webbrowser.open(str(page_url))
        except Exception:
            logger.debug("Failed to open browser automatically", exc_info=True)

    def update(self, status: str, user_id: int | None) -> None:
        self.status = status
        self.user_id = user_id
        if user_id is None:
            logger.info("Login status: %s", status)
        else:
            logger.info("Login status: %s (user_id=%s)", status, user_id)


class GUIManager:
    def __init__(self, twitch: Twitch):
        self._twitch = twitch
        self._close_requested = asyncio.Event()
        self._running = False
        self.status = _StatusBar()
        self.websockets = _WebsocketStatus()
        self.login = _LoginForm()
        self.progress = _Progress()
        self.output = _ConsoleOutput()
        self.channels = _ChannelList()
        self.inv = _InventoryOverview()
        self.settings = _SettingsPanel()
        self.tray = _TrayIcon()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def close_requested(self) -> bool:
        return self._close_requested.is_set()

    async def wait_until_closed(self) -> None:
        await self._close_requested.wait()

    async def coro_unless_closed(self, coro):
        tasks = [asyncio.ensure_future(coro), asyncio.ensure_future(self._close_requested.wait())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if self._close_requested.is_set():
            raise ExitRequest()
        return await next(iter(done))

    def prevent_close(self) -> None:
        self._close_requested.clear()

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False
        self.progress.stop_timer()

    def close(self, *args) -> int:
        self._close_requested.set()
        self._twitch.close()
        return 0

    def close_window(self) -> None:
        self.stop()

    def save(self, *, force: bool = False) -> None:
        return None

    def grab_attention(self, *, sound: bool = True) -> None:
        return None

    def set_games(self, games: set[Game]) -> None:
        self.settings.set_games(games)

    def display_drop(self, drop: TimedDrop, *, countdown: bool = True, subone: bool = False) -> None:
        self.progress.display(drop, countdown=countdown, subone=subone)
        self.tray.update_title(drop)

    def clear_drop(self) -> None:
        self.progress.display(None)
        self.tray.update_title(None)

    def print(self, message: str) -> None:
        self.output.print(message)
