# desktop-bot

Telegram bot for remotely waking, shutting down, and checking the status of a Windows desktop PC.

**Commands:**
- `/wake` — sends a Wake-on-LAN magic packet
- `/shutdown` — SSHes into the desktop and runs `shutdown /s /t 0`
- `/status` — checks if the desktop is online via `tailscale ping`

## Prerequisites

### Windows Desktop

**1. Wake-on-LAN**
- Enable WOL in BIOS (usually under Power Management)
- Enable WOL in the network adapter: Device Manager → NIC → Properties → Power Management → "Allow this device to wake the computer"
- The desktop must be connected via **Ethernet** (Wi-Fi WOL is unreliable)

**2. OpenSSH Server** (for `/shutdown`)
- Install via Settings → Optional Features → OpenSSH Server
- Start and enable the service: `Start-Service sshd; Set-Service sshd -StartupType Automatic`
- Allow inbound port 22 through Windows Firewall if not done automatically

**3. SSH key auth** (for `/shutdown`)

Copy the server's public key into the desktop's authorized_keys. From the server:
```bash
ssh-copy-id -i /root/.ssh/id_rsa.pub <DESKTOP_SSH_USER>@<DESKTOP_IP>
```
Or manually append `~/.ssh/id_rsa.pub` contents to `C:\Users\<user>\.ssh\authorized_keys` on the desktop.

> If the desktop user is an Administrator, Windows requires the key to be in
> `C:\ProgramData\ssh\administrators_authorized_keys` instead, with restricted permissions:
> ```powershell
> icacls "C:\ProgramData\ssh\administrators_authorized_keys" /inheritance:r /grant "Administrators:F" /grant "SYSTEM:F"
> ```

**4. Tailscale** (for `/status`)
- Install Tailscale on the desktop and connect it to the same tailnet as the server
- The bot uses `tailscale ping` rather than ICMP ping — Windows Firewall blocks ICMP by default

### Server (Docker host)

- **Tailscale** running on the host, with `/usr/bin/tailscale` and `/var/run/tailscale` available (bind-mounted into the container)
- **SSH key pair** at `/root/.ssh/id_rsa` — private key bind-mounted read-only into the container
- `network_mode: host` is required so the WOL broadcast reaches the LAN

## Setup

**1. Create a Telegram bot**

Message [@BotFather](https://t.me/BotFather), create a bot, and copy the token.

**2. Find your Telegram chat ID**

Message [@userinfobot](https://t.me/userinfobot) — it will reply with your chat ID.

**3. Configure `.env`**

```bash
cp .env.example .env
```

Edit `.env`:
```
BOT_TOKEN=your-telegram-bot-token
ALLOWED_CHAT_IDS=your-chat-id        # comma-separated for multiple users
DESKTOP_IP=100.x.x.x                 # Tailscale IP of the desktop
DESKTOP_MAC=AA:BB:CC:DD:EE:FF        # Ethernet MAC address for WOL
DESKTOP_SSH_USER=your-windows-username
```

**4. Build and start**

```bash
docker-compose build
docker-compose up -d
```
