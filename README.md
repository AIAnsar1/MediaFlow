<div align="center">

# 📥 MediaDownloader
### Advanced Multi-Platform Telegram Bot Manager & Downloader

[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue?logo=python&logoColor=white)](https://python.org)
[![Litestar](https://img.shields.io/badge/Framework-Litestar-6B21A8?logo=fastapi&logoColor=white)](https://litestar.dev)
[![SQLAlchemy 2.0](https://img.shields.io/badge/OR-SQLAlchemy%202.0-red?logo=sqlalchemy&logoColor=white)](https://sqlalchemy.org)
[![Redis](https://img.shields.io/badge/Cache-Redis-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

**A powerful, self-hosted solution for managing a network of Telegram Media Downloader bots with a premium web-based administrative dashboard.**

[Explore Features](#-key-features) • [Installation](#-installation) • [Architecture](#-architecture) • [Screenshots](#-screenshots)

</div>

## ✨ Key Features

- **📥 Universal Downloader** – Supports Instagram, TikTok, YouTube, Pinterest, VK, and more.
- **🤖 Multi-Bot Hub** – Manage multiple Telegram bots from a single unified interface.
- **🌑 Premium Dark Interface** – Glassmorphic admin dashboard with a sleek, dark aesthetic.
- **📊 Real-time Metrics** – Tracking of downloads, user growth, and platform popularity.
- **📢 Broadcast System** – Reach your entire user base with built-in mass messaging.
- **🛡️ Enterprise Grade** – Robust rate limiting, logging, and asynchronous task processing.
- **⚡ High Performance** – Built on **Litestar** (ASGI) and **ARQ** (Redis-based queue).

## 🛠️ Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Core** | [Python 3.12+](https://python.org) |
| **API/Web** | [Litestar](https://litestar.dev) |
| **Database** | [SQLAlchemy 2.0](https://sqlalchemy.org) (+ PostgreSQL/SQLite) |
| **Queue/Task** | [ARQ](https://github.com/samuelcolvin/arq) (Redis based) |
| **Frontend** | [Jinja2](https://jinja.palletsprojects.com/) + [Tailwind CSS](https://tailwindcss.com/) |
| **Logging** | [Structlog](https://www.structlog.org/) |

## 🚀 Installation

### 1. Clone & Setup
```bash
git clone https://github.com/AIAnsar1/MediaDownloader.git
cd MediaDownloader
uv venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
uv sync
```

### 2. Configure
Copy labels from `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

### 3. Run Application
```bash
python main.py
```
> Admin panel will be available at: `http://127.0.0.1:8000/admin`

## 📊 Statistics Dashboard
Our built-in statistics module gives you a bird's-eye view of your bot network:
- **Daily/Monthly Downloads**
- **User Language Distribution**
- **Platform Success Rates**
- **Active Worker Status**

## 🛡️ Service Stability
The project is covered by a comprehensive test suite (135+ tests) ensuring:
- ✅ **Database mapping integrity**
- ✅ **Multi-source parsing reliability**
- ✅ **High-load queue stability**
- ✅ **Event-loop safe service operations**

## 📜 License
Distributed under the **MIT License**. See `LICENSE` for more information.

---

<div align="center">
    Made with ❤️ for the AIAnsar
</div>
