# PROJECT_MEMORY.md — ZMQ Discord Bot

> Bu dosya proje mimarisini, kararları ve bilinen sorunları belgeler.
> Yeni bir geliştirici (veya AI asistan) projeye girdiğinde ilk okuması gereken dosyadır.

---

## 1. Proje Kimliği

| Özellik | Değer |
|---------|-------|
| **İsim** | ZMQ Discord Bot |
| **Tür** | Microservice Discord Botu |
| **Dil** | Python 3.11+ |
| **Framework** | discord.py 2.7+ |
| **IPC** | ZeroMQ (pyzmq) |
| **Veritabanı** | SQLite (aiosqlite) |
| **Oluşturma** | 2026-04-24 |

---

## 2. Mimari Kararlar

### 2.1 Neden ZeroMQ?

Bot işlevselliği (müzik işleme, veritabanı sorguları, API çağrıları) tek bir process'te çalıştığında:
- Ağır I/O işlemleri Discord event loop'u bloklar
- Tek bir crash tüm botu çökertir
- Yatay ölçeklendirme imkansız

**ZMQ çözümü:** Her iş yükü bağımsız bir process'te çalışır. Broker (PULL/PUB proxy) mesajları topic bazlı yönlendirir.

### 2.2 PUSH/PULL + PUB/SUB (Centrum Pattern)

Bu mimari Centrum/Marmarai projesinden adapte edilmiştir:

```
[Service] --PUSH--> [Broker PULL:5556] --zmq.proxy--> [Broker PUB:5555] --SUB--> [Services]
```

**Neden XPUB/XSUB değil?**
- `zmq.proxy(PULL, PUB)` C seviyesinde çalışır, minimal overhead
- Mesaj kaybı riski düşük (PUSH load-balanced değil, hepsi broker'a gider)
- Centrum'da Raspberry Pi'de kanıtlanmış (3+ servis, sürekli çalışır)

### 2.3 Async vs Sync ZMQ

| Bileşen | ZMQ Tipi | Neden |
|---------|----------|-------|
| Bot Core | `zmq.asyncio` (AsyncZMQEventBus) | Discord.py asyncio loop ile uyumlu olmalı |
| Worker'lar | `zmq` sync (ZMQEventBus) | Ayrı process, kendi event loop'u yok |

### 2.4 SQLite Tercihi

- **Sıfır konfigürasyon** — dosya sistemi yeterli
- **Yeterli performans** — tek sunucu botu için fazlasıyla yeterli
- **Async desteği** — `aiosqlite` ile non-blocking
- **Upgrade yolu** — İleride PostgreSQL'e geçiş `database.py`'de izole

### 2.5 Discord.py v2 (Slash Commands)

- Prefix komutlar yerine app commands (slash) kullanılıyor
- `commands.Bot` + `app_commands` hibrit yaklaşım
- `setup_hook()` ile cog yükleme ve command sync

---

## 3. Servis Topolojisi

### Process'ler ve Portlar

| Process | Tip | ZMQ Port | Kritik | Yeniden Başlatma |
|---------|-----|----------|--------|------------------|
| ZMQ Broker | Router | PULL:5556, PUB:5555 | ✅ Evet | Ölürse tüm sistem kapanır |
| DB Worker | Worker | — (subscriber) | ❌ Hayır | Exponential backoff (2ˆn, max 30s) |
| Music Worker | Worker | — (subscriber) | ❌ Hayır | Exponential backoff |
| Discord Bot | Core | — (subscriber) | ✅ Evet | Ölürse tüm sistem kapanır |

### Başlatma Sırası (run.py)

```
1. ZMQ Broker (1s bekleme — bind tamamlansın)
2. DB Worker (0.5s bekleme)
3. Music Worker (0.5s bekleme)
4. Discord Bot (son — tüm worker'lar hazır olmalı)
```

### Watchdog Parametreleri

| Parametre | Değer | Kaynak |
|-----------|-------|--------|
| `WATCHDOG_INTERVAL` | 2s | config.yaml |
| `MAX_RESTARTS_PER_MIN` | 5 | config.yaml |
| Backoff formülü | `min(2^n, 30)` | run.py hardcoded |

---

## 4. ZMQ Mesaj Akışı

### Request/Response Korelasyonu

```python
# Bot tarafı (async):
future = loop.create_future()
pending[msg.request_id] = future
await ebus.publish("DB", msg)
response = await asyncio.wait_for(future, timeout=5.0)

# Worker tarafı (sync):
# Broker üzerinden gelen mesajı al
topic, msg = ebus.receive()
# İşle ve yanıt gönder
response = make_response(msg, data={...})
ebus.publish("BOT", response)

# Bot ZMQ listener'da:
# RESPONSE mesajı gelince pending[request_id] future'ını resolve et
```

### Handshake Protokolü

Her worker başladığında:
```json
{"action": "SERVICE_READY", "source": "music", "topic": "SYSTEM"}
```
Bot bu mesajları loglar. İleride health-check mekanizması eklenebilir.

### Socket Ayarları (Crash Resilience)

```python
# PUSH (gönderici):
LINGER = 1000    # Close'da 1s bekle, sonra drop et
SNDHWM = 100     # Max 100 mesaj kuyrukta (taşarsa drop)

# SUB (alıcı):
LINGER = 0       # Hemen kapat
RCVHWM = 100     # Max 100 mesaj buffer
```

---

## 5. Discord UI State Yönetimi

### Oturum (Session) Sistemi

```python
# Bellekte tutulan basit dict
_active_sessions: dict[int, dict] = {
    user_id: {
        "category": "music",      # Seçili kategori
        "guild_id": 123456789,    # Hangi sunucu
        "timestamp": 1714000000,  # Oluşturulma zamanı
    }
}
```

**Kurallar:**
- Bir kullanıcının aynı anda tek bir aktif oturumu olabilir
- 180s timeout → otomatik temizleme (`View.on_timeout`)
- `interaction_check` → sadece komutu çalıştıran kullanıcı etkileşebilir
- Oturum bilgisi veritabanında tutulmaz (volatile, restart'ta kaybolur)

### Modal → ZMQ → DB Akışı

```
Kullanıcı butona tıklar
  → EditButton.callback → Modal açılır
    → Kullanıcı veri girer → on_submit
      → make_request("SAVE_SETTING", ...)
        → ZMQ PUSH → Broker → DB Worker
          → DB Worker UPDATE → make_response
            → ZMQ PUSH → Broker → Bot SUB
              → Future resolved → interaction.response
```

---

## 6. Veritabanı Şeması

### Tablolar

| Tablo | PK | Açıklama |
|-------|-----|----------|
| `guild_settings` | `guild_id` | Sunucu ayarları (prefix, dil, kanallar, roller) |
| `user_settings` | `(user_id, guild_id)` | Kullanıcı tercihleri |
| `warnings` | `id` (auto) | Uyarı kayıtları |
| `music_history` | `id` (auto) | Çalınan şarkı geçmişi |

### Trigger'lar
- `guild_settings_update` → `updated_at` otomatik güncelleme
- `user_settings_update` → aynı

### Güvenlik
- `update_guild_setting()` whitelist ile korunur (SQL injection önlemi)
- İzin verilen kolonlar: `prefix, language, welcome_channel_id, ...`

---

## 7. Cog Sistemi

### Yaşam Döngüsü

```
Başlatma:
  cog_manager.load_all()
    → discover_cogs()     # src/bot/cogs/*.py tara
    → load_cog(path)      # bot.load_extension()
    → register_admin_commands()  # /cog komutlarını ekle

Hot-Swap:
  /cog yenile general
    → reload_cog("src.bot.cogs.general")
      → bot.reload_extension(path)   # unload + reimport + load
```

### Cog Keşif Kuralları
- `src/bot/cogs/` dizinindeki `.py` dosyaları
- `_` ile başlayanlar hariç (`__init__.py` gibi)
- Her dosyada `async def setup(bot)` fonksiyonu olmalı

---

## 8. Bilinen Sorunlar ve Notlar

### ⚠️ Privileged Intents
Bot ilk çalıştırıldığında Discord Developer Portal'da **Privileged Gateway Intents** açılmalı:
- `PRESENCE INTENT`
- `SERVER MEMBERS INTENT`
- `MESSAGE CONTENT INTENT`

Açılmazsa bot `exit code=1` ile çöker.

### ⚠️ Slash Command Sync Gecikmesi
- `DISCORD_GUILD_ID` ayarlanırsa: anında sync (geliştirme modu)
- Boş bırakılırsa: global sync (1 saat gecikme olabilir)

### ⚠️ Müzik — Voice Mimarisi
- Voice channel bağlantısı **bot process**'inde olmalı (discord.py kısıtı)
- Music Worker yalnızca kuyruk ve metadata yönetir
- Gerçek audio streaming bot cog'unda yapılmalı

### 📝 İleride Yapılacaklar
- [ ] Health-check / heartbeat mekanizması (SYSTEM topic)
- [ ] Redis/PostgreSQL migration desteği
- [ ] Müzik için gerçek audio streaming (FFmpegPCMAudio)
- [ ] Çoklu dil desteği (i18n)
- [ ] Web dashboard (Flask/FastAPI + ZMQ)
- [ ] Docker compose ile deployment

---

## 9. Dosya Referans Haritası

```
config.yaml ─────────┐
.env ─────────────────┤
                      ▼
              src/core/config.py ──→ Tüm modüller import eder
              src/core/logger.py ──→ get_logger("servis_adı")
              src/core/protocol.py → ZMQMessage, Topic, factory'ler
              src/core/router.py ──→ run.py tarafından process olarak başlatılır
              src/core/zmq_client.py
                   ├── ZMQEventBus ──→ Worker'lar kullanır
                   └── AsyncZMQEventBus ──→ Bot kullanır

src/bot/bot.py
  ├── setup_hook() → cog_manager.load_all()
  ├── _zmq_listener() → asyncio.Task (arka plan)
  └── request() → Future-based REQ/REP

src/bot/cog_manager.py
  └── discover_cogs() → src/bot/cogs/*.py

src/services/base_service.py
  └── run() → Poller loop → handle_message()

src/ui/settings_view.py
  ├── SettingsView → CategorySelect + EditButton + CloseButton
  ├── session state → _active_sessions dict
  └── ChannelPickerView, RolePickerView

src/db/database.py
  ├── initialize() / initialize_sync()
  ├── get_guild_settings() / update_guild_setting()
  └── SCHEMA_SQL → otomatik tablo oluşturma
```

---

*Son güncelleme: 2026-04-24*
