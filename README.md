# Twitch Drops Miner (Headless CLI)

Fork/clone of [udry0/twitchdropsminer-cli](https://github.com/udry0/twitchdropsminer-cli) — auto-farm Twitch drops in headless mode.

## Setup

```bash
cp twitchdropsminer.env.example twitchdropsminer.env
# Edit .env with your Twitch auth token
bash run_headless.sh
```

## Running as systemd service

```bash
# See systemd/ folder for service files
systemctl --user enable --now twitchdropsminer.service
```

## Features
- Headless CLI mode (no GUI needed)
- Auto-farm drops for configured games
- Campaign inventory tracking
- Multi-account support via separate instances

## Credits
Original: [udry0/twitchdropsminer-cli](https://github.com/udry0/twitchdropsminer-cli)
