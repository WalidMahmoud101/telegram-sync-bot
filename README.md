# Telegram Sync Bot 🚀

**English** | [العربية](#-النسخة-العربية)

A complete bot that downloads files (.txt / .rar / any extension) from Telegram channels and folders automatically — full archive on the first run, daily sync for new files, and full remote control from Telegram on your phone.

> This project was built step by step with a lot of hard work — from a simple script
> to a complete system running 24/7 on its own. Hope it helps you as much as it helped me ❤️

## ✨ Features

- 📥 **Full archive download** on the first run (from the very first message to today)
- 🔄 **Automatic daily sync** for new files only (zero duplicates)
- 📱 **Full control from Telegram** — commands in Saved Messages from anywhere in the world
- ⚡ **Maximum speed** — parallel downloads (channels × files) + native C crypto
- 🖥️ **Live console title** — current channel, progress %, file count, and total GB in the window title
- 🔁 **Auto-restart** — a watchdog brings the bot back in 10 seconds if it crashes + starts with Windows
- 🔑 **Archive password capture** — passwords in file captions are saved to `_passwords.txt`
- 🛡️ **Duplicate & incomplete-file protection** — partial files are re-downloaded automatically
- 📊 **Live reports** in Saved Messages with per-channel counters

## 📋 Requirements

- Windows (or Linux) + Python 3.10+
- A Telegram account + API credentials from https://my.telegram.org ← API development tools

## 🔧 Installation (step by step)

```bash
# 1) Clone the project
git clone https://github.com/WalidMahmoud101/telegram-sync-bot.git
cd telegram-sync-bot

# 2) Create a virtual environment and install dependencies
python -m venv venv
venv\Scripts\pip install telethon colorama cryptg     # Windows
# ./venv/bin/pip install telethon colorama cryptg     # Linux

# 3) Prepare your configuration
cp env.example .env
# Edit .env and set your TG_API_ID and TG_API_HASH
```

## ⚙️ Configuration (.env)

| Setting | Meaning |
|---|---|
| `TG_API_ID` / `TG_API_HASH` | From my.telegram.org (required) |
| `TG_CHANNELS` | Channel IDs or usernames, comma-separated |
| `TG_FOLDERS` | Telegram folder names (optional) |
| `TG_EXTENSIONS` | Wanted extensions, e.g. `txt,rar` |
| `OUT_DIR` | Download destination |
| `FIRST_RUN_DAYS` | `0` = entire archive on first run, or N = only last N days |
| `MAX_FILE_MB` | Max file size in MB, `0` = unlimited |
| `TG_NOTIFY` | Telegram reports: `1` on / `0` off |
| `DAILY_TIME` | Daily sync time (e.g. `03:00`) |

## 🚀 Usage (step by step)

```bash
# 1) Sign in (one time only - your phone number + the code)
venv\Scripts\python tg_txt_sync.py --login

# 2) List all your channels with their IDs
venv\Scripts\python tg_list_folders.py --channels   # saves channels.txt

# 3) Put the IDs you want into TG_CHANNELS in .env

# 4) Run the main bot
venv\Scripts\python tg_bot.py
```

## 📱 Telegram commands (in Saved Messages)

| Command | What it does |
|---|---|
| `/add -100xxx` or `/add @user` | Adds a channel, replies with its name, downloads its archive immediately |
| `/remove -100xxx` | Removes a channel from the list |
| `/list` | Shows configured channels |
| `/channels` | Full list of your channels/groups with IDs (sends channels.txt) |
| `/status` | File count, disk usage, current activity, next run time |
| `/sync` | Forces a full sync right now |
| `/help` | Shows the command list |

## 🔄 Running 24/7 (Windows)

The bot starts automatically at logon and heals itself:
- A **scheduled task** `TG_Sync_Daemon` runs `run_bot.bat` at logon
- **run_bot.bat (watchdog)**: if the bot crashes for any reason, it restarts it after 10 seconds

Create the task manually:
```cmd
schtasks /create /tn "TG_Sync_Daemon" /tr "\"C:\path\to\run_bot.bat\"" /sc onlogon /f
```

## 📁 Output structure

```
OUT_DIR\
├── Channel Name\
│   ├── 2026-01-15_123_filename.rar
│   └── _passwords.txt      ← archive passwords captured for this channel
└── Another Channel\
    └── ...
```

## 🧠 How it works

- `state.json` stores the last processed message per channel → later syncs fetch only new files
- Files on disk with matching sizes are skipped; incomplete files are re-downloaded
- **3 parallel file downloads per channel × 6 channels concurrently**
- `cryptg` accelerates decryption ~70x compared to the default pure-Python pyaes

## 🛠️ Troubleshooting

| Problem | Fix |
|---|---|
| `database is locked` | Another copy of the script is running - close it first |
| Very slow downloads | Make sure `cryptg` is installed: `pip install cryptg` |
| `Folder not found` | The folder name in `.env` must match Telegram exactly |
| Bot not answering commands | Send commands in **Saved Messages**, not another chat |

## 🔐 Security

- `tg_session.session` = full access to your account — never upload it (it's in .gitignore)
- Same for `.env` — your keys are secret
- If anything leaks: Telegram ← Settings ← Devices and terminate the session
- The bot only reads and downloads — it never messages anyone except your own Saved Messages

## 📄 Project files

| File | Role |
|---|---|
| `tg_bot.py` | Main bot (24/7 daemon + Telegram commands + scheduling) |
| `tg_txt_sync.py` | Sync/download engine (also works standalone) |
| `tg_list_folders.py` | Lists folders/channels with their IDs |
| `run_bot.bat` | Watchdog that keeps the bot alive |
| `env.example` | Configuration template |

---

# 🇪🇬 النسخة العربية

بوت شامل لتنزيل ملفات (.txt / .rar / أي امتداد) من قنوات وفولدرات تليجرام تلقائياً —
بأرشيف كامل أول مرة، ومزامنة يومية للجديد، وتحكم كامل من تليجرام على موبايلك.

> المشروع ده اتبنى خطوة بخطوة بتعب ومجهود كبير لحد ما وصل للشكل ده — من سكريبت بسيط
> لنظام كامل شغال 24/7 لوحده. إن شاء الله يفيدك زي ما أفادني ❤️

## ✨ المميزات

- 📥 **تحميل الأرشيف الكامل** أول مرة من كل قناة (من أول رسالة لحد النهارده)
- 🔄 **مزامنة يومية تلقائية** للملفات الجديدة بس (من غير أي تكرار)
- 📱 **تحكم كامل من تليجرام** — أوامر في Saved Messages من أي مكان في العالم
- ⚡ **سرعة قصوى** — تحميل متوازي (قنوات × ملفات) + فك تشفير C أصلي
- 🖥️ **عنوان CMD لايف** — القناة، النسبة، عدد الملفات، والجيجات في شريط العنوان
- 🔁 **إعادة تشغيل تلقائي** — watchdog يرجّع البوت في 10 ثواني لو وقع + يشتغل مع الويندوز
- 🔑 **التقاط باسوردات فك الضغط** تلقائياً من كابشن الملفات وحفظها في `_passwords.txt`
- 🛡️ **حماية من التكرار والملفات الناقصة** — أي ملف مش كامل بيتعاد تنزيله لوحده
- 📊 **تقارير لايف** على Saved Messages بعدّادات كل قناة

## 📋 المتطلبات

- Windows (أو Linux) + Python 3.10+
- حساب تليجرام + API credentials من https://my.telegram.org ← API development tools

## 🔧 التركيب (بالترتيب)

```bash
# 1) حمّل المشروع وادخل فولدره
git clone https://github.com/WalidMahmoud101/telegram-sync-bot.git
cd telegram-sync-bot

# 2) أنشئ بيئة افتراضية وثبّت المكتبات
python -m venv venv
venv\Scripts\pip install telethon colorama cryptg

# 3) جهّز الإعدادات
cp env.example .env
# عدّل .env وحط TG_API_ID و TG_API_HASH بتاعك
```

## ⚙️ إعدادات .env

| الإعداد | المعنى |
|---|---|
| `TG_API_ID` / `TG_API_HASH` | من my.telegram.org (إجباري) |
| `TG_CHANNELS` | IDs أو يوزرات القنوات، مفصولة بفاصلة |
| `TG_FOLDERS` | أسماء فولدرات تليجرام (اختياري) |
| `TG_EXTENSIONS` | الامتدادات المطلوبة: `txt,rar` مثلاً |
| `OUT_DIR` | مكان التنزيل على الجهاز |
| `FIRST_RUN_DAYS` | `0` = الأرشيف كله أول مرة، أو رقم = آخر N يوم |
| `MAX_FILE_MB` | أقصى حجم بالميجا، `0` = بدون حد |
| `TG_NOTIFY` | تقارير تليجرام: `1` شغال / `0` مقفول |
| `DAILY_TIME` | معاد المزامنة اليومية (مثال: `03:00`) |

## 🚀 طريقة التشغيل (بالترتيب)

```bash
# 1) تسجيل الدخول (مرة واحدة بس - رقمك + الكود)
venv\Scripts\python tg_txt_sync.py --login

# 2) استخرج قائمة قنواتك بالـ IDs
venv\Scripts\python tg_list_folders.py --channels   # بيحفظ channels.txt

# 3) حط الـ IDs اللي عايزها في .env ← TG_CHANNELS

# 4) شغّل البوت الرئيسي
venv\Scripts\python tg_bot.py
```

## 📱 أوامر تليجرام (من Saved Messages)

| الأمر | الوظيفة |
|---|---|
| `/add -100xxx` أو `/add @user` | يضيف قناة، يرد باسمها، وينزّل أرشيفها فوراً |
| `/remove -100xxx` | يشيل قناة من الليستة |
| `/list` | القنوات المضافة |
| `/channels` | ليستة كل قنواتك/جروباتك بالـ IDs (بيبعت channels.txt) |
| `/status` | عدد الملفات، المساحة، النشاط الحالي، المعاد الجاي |
| `/sync` | مزامنة كاملة فورية |
| `/help` | قائمة الأوامر |

## 🔄 التشغيل الدائم (ويندوز)

البوت بيشتغل تلقائياً مع تسجيل الدخول عن طريق:
- **مهمة مجدولة** `TG_Sync_Daemon` تشغّل `run_bot.bat` عند الـ logon
- **run_bot.bat (watchdog)**: لو البوت وقع لأي سبب بيرجع يشغّله بعد 10 ثواني

إنشاء المهمة يدوياً:
```cmd
schtasks /create /tn "TG_Sync_Daemon" /tr "\"C:\path\to\run_bot.bat\"" /sc onlogon /f
```

## 📁 شكل الناتج

```
OUT_DIR\
├── Channel Name\
│   ├── 2026-01-15_123_filename.rar
│   └── _passwords.txt      ← باسوردات فك الضغط الخاصة بالقناة دي
└── Another Channel\
    └── ...
```

## 🧠 إزاي بيشتغل؟

- `state.json` بيحفظ رقم آخر رسالة لكل قناة → المزامنات الجاية بتجيب الجديد بس
- أي ملف موجود على الهارد بنفس الحجم بيتتخطى، والناقص بيتعاد تنزيله
- الملفات بينزّل منها **3 بالتوازي لكل قناة** و**6 قنوات بالتوازي**
- `cryptg` بتسرّع فك التشفير ~70x مقارنة بـ pyaes الافتراضية

## 🛠️ استكشاف الأخطاء

| المشكلة | الحل |
|---|---|
| `database is locked` | فيه نسخة تانية من السكريبت شغالة — اقفلها الأول |
| التحميل بطيء جداً | تأكد إن `cryptg` متثبتة: `pip install cryptg` |
| `Folder not found` | اسم الفولدر في `.env` مش مطابق لتليجرام بالظبط |
| البوت مش بيرد على الأوامر | ابعت الأمر في **Saved Messages** مش أي شات تاني |

## 🔐 الأمان

- ملف `tg_session.session` = دخول كامل لحسابك — مترفعوش أبداً (موجود في .gitignore)
- نفس الكلام لملف `.env` — مفاتيحك سرية
- لو حاجة اتسربت: Telegram ← Settings ← Devices وامسح الجلسة
- البوت بيقرا وينزّل بس — مبيبعتش رسايل لحد غير Saved Messages بتاعتك

---

Built with ❤️ and a lot of hard work.
