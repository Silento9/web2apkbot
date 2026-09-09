import asyncio, re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func
from .config import settings
from .db import Session, User, BuildJob
from .security import check_url
from .builder import build_apk

router = Router()
pending = {}
sem = asyncio.Semaphore(settings.max_concurrent_builds)

def menu(admin=False):
    b = InlineKeyboardBuilder()
    b.button(text="🌐 Create APK", callback_data="build")
    b.button(text="📦 My APKs", callback_data="apps")
    b.button(text="👤 Profile", callback_data="profile")
    b.button(text="ℹ️ Help", callback_data="help")
    b.button(text="⚙️ Settings", callback_data="settings")
    if admin:
        b.button(text="👑 Admin Panel", callback_data="admin")
    b.adjust(2, 2, 1)
    return b.as_markup()

def is_admin(uid): return uid in settings.admins

@router.message(CommandStart())
async def start(message: Message):
    async with Session() as db:
        q = await db.execute(select(User).where(User.telegram_id == message.from_user.id))
        user = q.scalar_one_or_none()
        if not user:
            user = User(telegram_id=message.from_user.id,
                        username=message.from_user.username,
                        first_name=message.from_user.first_name)
            db.add(user)
            await db.commit()
    await message.answer(
        "🚀 <b>Welcome to Web2APK Converter</b>\\n\\n"
        "Convert a supported website into an Android APK directly from Telegram.\\n\\n"
        "⚡ Fast build queue\\n📱 Android WebView\\n🎨 App customization",
        reply_markup=menu(is_admin(message.from_user.id))
    )

@router.callback_query(F.data == "build")
async def build_start(call: CallbackQuery):
    pending[call.from_user.id] = {"step": "url"}
    await call.message.edit_text(
        "🔗 <b>Send your website URL</b>\\n\\nExample: https://example.com",
        reply_markup=InlineKeyboardBuilder().button(text="❌ Cancel", callback_data="cancel").as_markup()
    )
    await call.answer()

@router.message(F.text)
async def text_input(message: Message):
    uid = message.from_user.id
    state = pending.get(uid)
    if not state:
        return

    if state["step"] == "url":
        try:
            url = await check_url(message.text)
        except Exception as e:
            await message.answer(f"❌ {e}")
            return
        pending[uid] = {"step": "name", "url": url}
        await message.answer("📝 Send the APK app name.")
        return

    if state["step"] == "name":
        name = message.text.strip()
        if not 2 <= len(name) <= 50:
            await message.answer("❌ App name must be between 2 and 50 characters.")
            return
        pending[uid] = {"step": "package", "url": state["url"], "name": name}
        await message.answer(
            "📦 Send a package name or type <code>auto</code>.\\n"
            "Example: <code>com.example.myapp</code>"
        )
        return

    if state["step"] == "package":
        package = message.text.strip()
        if package.lower() == "auto":
            package = f"com.web2apk.app{uid}"
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+", package):
            await message.answer("❌ Invalid Android package name.")
            return
        pending[uid]["package"] = package
        await message.answer(
            f"📱 <b>Ready to build</b>\\n\\n"
            f"🌐 {state['url']}\\n📝 {state['name']}\\n📦 {package}",
            reply_markup=InlineKeyboardBuilder()
              .button(text="🚀 Build APK", callback_data="confirm_build")
              .button(text="❌ Cancel", callback_data="cancel").as_markup()
        )

@router.callback_query(F.data == "confirm_build")
async def confirm_build(call: CallbackQuery):
    uid = call.from_user.id
    state = pending.get(uid)
    if not state or "package" not in state:
        await call.answer("Session expired. Start again.", show_alert=True)
        return

    await call.message.edit_text("⏳ Build queued...")
    async with Session() as db:
        job = BuildJob(telegram_id=uid, url=state["url"], app_name=state["name"],
                       package_name=state["package"], status="QUEUED")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id
        user = (await db.execute(select(User).where(User.telegram_id == uid))).scalar_one()
        user.total_builds += 1
        await db.commit()

    pending.pop(uid, None)
    asyncio.create_task(run_job(call.message.chat.id, job_id, state))
    await call.answer()

async def run_job(chat_id, job_id, state):
    async with sem:
        async with Session() as db:
            job = (await db.execute(select(BuildJob).where(BuildJob.id == job_id))).scalar_one()
            job.status = "BUILDING"
            await db.commit()
        try:
            path, internal_id = await build_apk(state["url"], state["name"], state["package"])
            async with Session() as db:
                job = (await db.execute(select(BuildJob).where(BuildJob.id == job_id))).scalar_one()
                job.status = "COMPLETED"
                job.apk_path = str(path)
                user = (await db.execute(select(User).where(User.telegram_id == job.telegram_id))).scalar_one()
                user.successful_builds += 1
                await db.commit()
            # Bot instance is attached at runtime.
            bot = run_job.bot
            await bot.send_document(chat_id, FSInputFile(path), caption=f"✅ <b>APK Ready</b>\\n\\n📱 {state['name']}\\n🌐 {state['url']}")
        except Exception as exc:
            async with Session() as db:
                job = (await db.execute(select(BuildJob).where(BuildJob.id == job_id))).scalar_one()
                job.status = "FAILED"
                job.error = str(exc)[-6000:]
                user = (await db.execute(select(User).where(User.telegram_id == job.telegram_id))).scalar_one()
                user.failed_builds += 1
                await db.commit()
            await run_job.bot.send_message(chat_id, "❌ <b>Build failed</b>\\nPlease retry later or contact an administrator.")

@router.callback_query(F.data == "cancel")
async def cancel(call: CallbackQuery):
    pending.pop(call.from_user.id, None)
    await call.message.edit_text("❌ Cancelled.", reply_markup=menu(is_admin(call.from_user.id)))
    await call.answer()

@router.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    async with Session() as db:
        user = (await db.execute(select(User).where(User.telegram_id == call.from_user.id))).scalar_one()
    await call.message.edit_text(
        f"👤 <b>Your Profile</b>\\n\\n🆔 {user.telegram_id}\\n📦 Builds: {user.total_builds}\\n"
        f"✅ Success: {user.successful_builds}\\n❌ Failed: {user.failed_builds}",
        reply_markup=menu(is_admin(call.from_user.id))
    )
    await call.answer()

@router.callback_query(F.data == "apps")
async def apps(call: CallbackQuery):
    async with Session() as db:
        jobs = (await db.execute(
            select(BuildJob).where(BuildJob.telegram_id == call.from_user.id)
            .order_by(BuildJob.id.desc()).limit(10)
        )).scalars().all()
    if not jobs:
        text = "📦 <b>My APKs</b>\\n\\nNo builds yet."
    else:
        text = "📦 <b>My APKs</b>\\n\\n" + "\\n".join(
            f"#{j.id} • {j.app_name} • {j.status}" for j in jobs
        )
    await call.message.edit_text(text, reply_markup=menu(is_admin(call.from_user.id)))
    await call.answer()

@router.callback_query(F.data == "help")
async def help_cb(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ <b>How it works</b>\\n\\n1. Tap Create APK\\n2. Send URL\\n3. Choose app name\\n4. Choose package\\n5. Start build\\n6. Receive APK",
        reply_markup=menu(is_admin(call.from_user.id))
    )
    await call.answer()

@router.callback_query(F.data == "settings")
async def settings_cb(call: CallbackQuery):
    await call.message.edit_text("⚙️ User settings are currently kept minimal. Advanced build settings are controlled by the builder configuration.", reply_markup=menu(is_admin(call.from_user.id)))
    await call.answer()

@router.callback_query(F.data == "admin")
async def admin(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Unauthorized", show_alert=True); return
    b = InlineKeyboardBuilder()
    b.button(text="📊 Statistics", callback_data="admin_stats")
    b.button(text="👥 Users", callback_data="admin_users")
    b.button(text="📦 Jobs", callback_data="admin_jobs")
    b.button(text="⬅️ Back", callback_data="back")
    b.adjust(2, 1)
    await call.message.edit_text("👑 <b>Admin Panel</b>", reply_markup=b.as_markup())
    await call.answer()

@router.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Unauthorized", show_alert=True); return
    async with Session() as db:
        users = await db.scalar(select(func.count()).select_from(User))
        jobs = await db.scalar(select(func.count()).select_from(BuildJob))
        completed = await db.scalar(select(func.count()).select_from(BuildJob).where(BuildJob.status=="COMPLETED"))
        failed = await db.scalar(select(func.count()).select_from(BuildJob).where(BuildJob.status=="FAILED"))
    await call.message.edit_text(
        f"📊 <b>Statistics</b>\\n\\n👥 Users: {users}\\n📦 Jobs: {jobs}\\n"
        f"✅ Completed: {completed}\\n❌ Failed: {failed}",
        reply_markup=menu(True)
    )
    await call.answer()

@router.callback_query(F.data == "admin_users")
async def admin_users(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Unauthorized", show_alert=True); return
    async with Session() as db:
        users = (await db.execute(select(User).order_by(User.id.desc()).limit(20))).scalars().all()
    text = "👥 <b>Recent Users</b>\\n\\n" + "\\n".join(f"🆔 {u.telegram_id} • {u.username or '-'}" for u in users)
    await call.message.edit_text(text or "No users.", reply_markup=menu(True))
    await call.answer()

@router.callback_query(F.data == "admin_jobs")
async def admin_jobs(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Unauthorized", show_alert=True); return
    async with Session() as db:
        jobs = (await db.execute(select(BuildJob).order_by(BuildJob.id.desc()).limit(20))).scalars().all()
    text = "📦 <b>Recent Jobs</b>\\n\\n" + "\\n".join(f"#{j.id} • {j.status} • {j.app_name}" for j in jobs)
    await call.message.edit_text(text or "No jobs.", reply_markup=menu(True))
    await call.answer()

@router.callback_query(F.data == "back")
async def back(call: CallbackQuery):
    await call.message.edit_text("🏠 <b>Main Menu</b>", reply_markup=menu(is_admin(call.from_user.id)))
    await call.answer()
