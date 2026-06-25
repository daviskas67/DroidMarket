# DroidMarket

Private APK store with a web frontend and an Android 1.6 (Donut) client.

## Features

- **Android 1.6 client** — built with raw SDK tools (`aapt`, `javac`, `d8`, `jarsigner`), no Gradle/Android Studio
- **Flask server** — lightweight, zero dependencies beyond Flask + Pillow
- **Multi-server support** — switch between multiple market servers from the Android client
- **Holo / Material themes** — toggle between Holo Dark and Material Light on Android
- **Admin panel** — upload/edit/delete apps, change icons, manage versions
- **User system** — register, login, download tracking
- **Download progress** — horizontal progress bar with bytes counter
- **Responsive web UI** — works on desktop and mobile

## Quick Start

```bash
pip install flask pillow
python server.py
```

Server starts on `http://localhost:5000`. Admin password is printed on first run.

## Android Client

Open `AndroidClient/` in the repo, or build with `build.ps1` (Windows).

## Directory Structure

```
├── server.py              # Flask server + all HTML/CSS templates
├── AndroidClient/         # Android 1.6 app source
│   ├── src/               # Java source (ApiClient, ImageLoader, etc.)
│   ├── res/               # Layouts, themes, drawables
│   └── build.ps1          # Build script
├── suggest_server.py      # Server suggestion utility
└── README.md
```

## License

MIT
