# 🤖 ZMQ Discord Bot

> ZeroMQ tabanlı, microservice mimarili, modüler Discord botu.

## 🏗 Mimari

```
┌──────────────── run.py (Orchestrator) ────────────────┐
│     Watchdog · Exponential Backoff · Graceful Stop     │
└───┬──────────┬──────────────┬──────────────┬──────────┘
    │          │              │              │
┌───▼───┐ ┌───▼───┐   ┌──────▼─────┐  ┌────▼────┐
│  ZMQ  │ │  Bot  │   │ DB Worker  │  │  Music  │
│Broker │ │ Core  │   │  Service   │  │ Worker  │
│PULL/  │ │async  │   │ SQLite     │  │ yt-dlp  │
│PUB    │ │zmq.io │   │ sync       │  │ sync    │
└───┬───┘ └───┬───┘   └──────┬─────┘  └────┬────┘
    └─────────┴──────────────┴──────────────┘
              ZMQ PUSH/PULL + PUB/SUB
```

## 🚀 Hızlı Başlangıç

```bash
# Kurulum
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # DISCORD_TOKEN'ı düzenle

# Discord Developer Portal'da Privileged Gateway Intents aç:
# ✅ PRESENCE INTENT
# ✅ SERVER MEMBERS INTENT  
# ✅ MESSAGE CONTENT INTENT

# Çalıştır
python run.py
```

## 📁 Proje Yapısı

```
DiscordBot/
├── run.py                    # Orchestrator + Watchdog
├── config.yaml               # Global ayarlar (ZMQ, servisler)
├── .env                      # Token ve gizli anahtarlar
├── requirements.txt          # Bağımlılıklar
├── src/
│   ├── core/                 # Paylaşılan altyapı
│   │   ├── config.py         # .env + YAML config loader
│   │   ├── logger.py         # Merkezi loglama
│   │   ├── router.py         # ZMQ Broker (PULL/PUB proxy)
│   │   ├── zmq_client.py     # Sync + Async event bus
│   │   └── protocol.py       # ZMQMessage, Topic, MessageType
│   ├── bot/                  # Discord Bot
│   │   ├── bot.py            # DiscordBot sınıfı
│   │   ├── cog_manager.py    # Dinamik cog yükleyici
│   │   └── cogs/
│   │       ├── general.py        # /ping, /bilgi, /sunucu
│   │       ├── settings_cog.py   # /ayarlar (UI menü)
│   │       ├── music_cog.py      # /çal, /geç, /dur, /kuyruk, /ses
│   │       └── moderation_cog.py # /temizle, /sustur, /uyar
│   ├── services/             # Worker Servisleri
│   │   ├── base_service.py   # Soyut BaseWorker
│   │   ├── db_service.py     # Veritabanı worker
│   │   └── music_service.py  # Müzik worker
│   ├── ui/                   # Discord UI Bileşenleri
│   │   ├── settings_view.py  # SettingsView + session state
│   │   ├── settings_select.py# CategorySelect dropdown
│   │   └── settings_modal.py # Prefix, Welcome, Volume modals
│   └── db/
│       ├── database.py       # Async/sync SQLite
│       └── models.py         # GuildSettings, MusicQueue
├── data/bot.db               # SQLite (otomatik oluşur)
└── logs/bot.log              # Rotating log
```

## 📡 ZMQ Protokolü

### Wire Format
```
Frame 0: topic  (bytes) → "MUSIC", "DB", "BOT", "SYSTEM"
Frame 1: payload (JSON) → ZMQMessage envelope
```

### Mesaj Tipleri
| Tip | Açıklama | Kullanım |
|-----|----------|----------|
| `COMMAND` | Fire-and-forget | Kuyruğa ekle, sil |
| `REQUEST` | Yanıt bekler | Ayarları getir |
| `RESPONSE` | REQUEST yanıtı | Ayar verisi döndür |
| `EVENT` | Broadcast | Ayar değişti bildirimi |

### Topic'ler
| Topic | Abone | Açıklama |
|-------|-------|----------|
| `SYSTEM` | Hepsi | SERVICE_READY, SHUTDOWN |
| `BOT` | Bot | Worker yanıtları |
| `MUSIC` | Music Worker | Müzik komutları |
| `DB` | DB Worker | Veritabanı işlemleri |
| `SETTINGS` | Hepsi | Ayar değişiklikleri |

## 🎮 Komutlar

| Komut | Açıklama |
|-------|----------|
| `/ping` | Gecikme süresi |
| `/bilgi` | Bot istatistikleri |
| `/sunucu` | Sunucu bilgileri |
| `/ayarlar` | Pencereli ayar menüsü |
| `/çal <şarkı>` | Şarkı ara ve çal |
| `/geç` | Şarkı geç |
| `/dur` | Durdur ve ayrıl |
| `/kuyruk` | Kuyruğu göster |
| `/ses <0-100>` | Ses seviyesi |
| `/temizle <sayı>` | Mesaj sil |
| `/sustur <kullanıcı> <dk>` | Sustur |
| `/uyar <kullanıcı> <sebep>` | Uyarı ver |
| `/uyarılar <kullanıcı>` | Uyarıları listele |
| `/cog yükle/kaldır/yenile/liste` | Cog yönetimi |

## ⚙️ Ayarlar Menüsü (`/ayarlar`)

Interaktif Discord UI menüsü:
- **`discord.ui.Select`** → Kategori seçimi (Genel, Hoşgeldin, Müzik, Moderasyon)
- **`discord.ui.Button`** → Ayar düzenleme tetikleyicileri
- **`discord.ui.Modal`** → Pop-up veri giriş pencereleri
- **Session State** → `dict[user_id → state]`, 180s timeout
- Sadece komutu çalıştıran kullanıcı etkileşebilir

## 🔧 Konfigürasyon

| Dosya | İçerik | Öncelik |
|-------|--------|---------|
| `.env` | Token, gizli anahtarlar | 1 (en yüksek) |
| `config.yaml` | ZMQ portları, servis ayarları | 2 |
| Kod varsayılanları | Fallback değerler | 3 |

## 🛠 Geliştirme

### Yeni Cog
1. `src/bot/cogs/yeni_cog.py` oluştur
2. `commands.Cog` + `async def setup(bot)` pattern kullan
3. Otomatik keşfedilir veya `/cog yükle yeni_cog` ile yükle

### Yeni Worker
1. `BaseWorker`'dan miras al
2. `handle_message()` metodunu implement et
3. `run.py`'ye entry point ekle
4. `protocol.py`'ye yeni Topic ekle

## 📄 Lisans

Özel kullanım için geliştirilmiştir.
