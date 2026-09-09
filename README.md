# Web2APK Telegram Bot

Advanced Telegram Web → APK converter designed for Railway deployment.

## Features
- Telegram inline-button UI
- Telegram numeric User ID based admin authorization
- URL validation with SSRF/private-network protection
- PostgreSQL-ready persistence
- Build queue
- Android WebView APK template
- APK build/signing using Android SDK + Gradle
- FastAPI `/health` endpoint
- Railway/Docker deployment files
- Temporary build cleanup

## Important
This project creates APKs using a bundled Android project template. Railway build/runtime resources can be limited for Android builds, so use a persistent object-storage adapter for production APK retention.

## Environment
Copy `.env.example` to `.env` locally or configure the same variables in Railway.

Required:
- BOT_TOKEN
- ADMIN_IDS
- DATABASE_URL

Optional:
- STORAGE_* variables
- BUILD_TIMEOUT
- MAX_CONCURRENT_BUILDS
- APK_RETENTION_DAYS

## Run
```bash
pip install -r requirements.txt
python -m app.main
```

## Railway
Deploy the repository with Docker. Attach PostgreSQL and set environment variables in Railway.

Admin access is ONLY based on Telegram numeric IDs in `ADMIN_IDS`; there is no OTP/password/web admin panel.
