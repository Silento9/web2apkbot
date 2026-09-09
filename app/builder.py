import asyncio, os, re, shutil, uuid
from pathlib import Path
from .config import settings

BASE = Path(__file__).resolve().parent.parent
TEMPLATE = BASE / "android_template"
BUILDS = BASE / "builds"
BUILDS.mkdir(exist_ok=True)

def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return value[:60] or "WebApp"

def package_to_path(package: str) -> str:
    return package.replace(".", "/")

async def build_apk(url: str, app_name: str, package_name: str):
    job_id = uuid.uuid4().hex[:12]
    work = BUILDS / job_id
    shutil.copytree(TEMPLATE, work)

    # Patch template sources.
    manifest = work / "app/src/main/AndroidManifest.xml"
    main = work / "app/src/main/java/com/web2apk/template/MainActivity.java"
    strings = work / "app/src/main/res/values/strings.xml"

    text = manifest.read_text()
    text = text.replace("com.web2apk.template", package_name)
    manifest.write_text(text)

    java = main.read_text()
    java = java.replace("package com.web2apk.template;", f"package {package_name};")
    java = java.replace("__START_URL__", url)
    main.parent.mkdir(parents=True, exist_ok=True)
    # Move Java file to package path.
    target = work / "app/src/main/java" / package_to_path(package_name) / "MainActivity.java"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(java)
    if main.exists():
        main.unlink()

    s = strings.read_text().replace("__APP_NAME__", app_name)
    strings.write_text(s)

    proc = await asyncio.create_subprocess_exec(
        "./gradlew", "assembleDebug",
        cwd=work,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=settings.build_timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("Android build timed out.")

    if proc.returncode != 0:
        log = output.decode(errors="replace")[-6000:]
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("Android build failed:\n" + log)

    apk = work / "app/build/outputs/apk/debug/app-debug.apk"
    if not apk.exists():
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("APK output was not generated.")

    final = BUILDS / f"{safe_name(app_name)}-{job_id}.apk"
    shutil.copy2(apk, final)
    shutil.rmtree(work, ignore_errors=True)
    return final, job_id
