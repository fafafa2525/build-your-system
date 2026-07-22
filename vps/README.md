# AdsBot — VPS deployment

Runs the Telegram bot + background worker that talks to your Lovable web app.

## Prerequisites

- Ubuntu / Debian VPS (any small instance)
- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- Your Lovable app URL (e.g. `https://your-app.lovable.app`)
- The `BOT_API_TOKEN` from your Lovable project **Settings → Secrets**

## Install

```bash
# 1. Copy the vps/ folder to your server
scp -r vps user@YOUR_VPS:/opt/adsbot

# 2. SSH in and install
ssh user@YOUR_VPS
cd /opt/adsbot
sudo apt update && sudo apt install -y python3 python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
nano .env   # fill TELEGRAM_BOT_TOKEN, LOVABLE_API_URL, BOT_API_TOKEN
```

## Test manually

```bash
source .venv/bin/activate
python bot.py
```

Send `/start` to your bot on Telegram. Then get your Telegram user ID from
[@userinfobot](https://t.me/userinfobot) and add it in the web dashboard under
**Settings → Allowed Telegram IDs**.

## Run as a service (systemd)

```bash
sudo cp systemd/adsbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now adsbot
sudo systemctl status adsbot
sudo journalctl -u adsbot -f       # live logs
```

## Bot commands

| Command | What it does |
| --- | --- |
| `/start` | Show help |
| `/search` | Start a new Facebook Ads Library search (asks for keyword + country) |
| `/addkey <apify_api_XXX> [name]` | Add a new Apify API key |
| `/keys` | List active keys |
| `/stats` | Quick stats |
| `/cancel` | Cancel current conversation |

## How the flow works

```
Telegram user → /search "restaurants" 🇩🇿
    ↓
Bot creates a "job" in Lovable DB (status = pending)
    ↓
Worker (same process) polls every 5s, claims pending job
    ↓
Worker calls Apify (Facebook Ads Library scraper) with active key
    ↓
Worker extracts phone numbers from every ad's text
    ↓
Worker POSTs numbers to Lovable → server deduplicates against ALL past numbers
    ↓
Worker marks job completed, sends result file back to the user on Telegram
```

Everything shows live in the web dashboard: progress bar, logs, keys usage.

## Key rotation

- Add multiple keys with `/addkey` (or from the web dashboard).
- The worker picks the least-recently-used active key each run.
- When a key returns 402 / 429 / "insufficient credit", it is auto-marked as
  `exhausted` and the worker rotates to the next one — no code changes needed.
- Add a new key anytime with `/addkey` and it goes into the rotation immediately.

## Update the code

```bash
cd /opt/adsbot
git pull   # or re-scp the new vps/ folder
sudo systemctl restart adsbot
```
