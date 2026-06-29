import logging
import random
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes, CallbackQueryHandler
)
from telegram.error import TelegramError

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8665328135:AAH4IeFAF_V6niWdxxOemyhdcLZaoNsocds"
ALLOWED_CHAT_ID = -1004489445301
OWNER_ID = 8663399544  # Твой Telegram ID

GIFTS = ["5170233102089322756", "5168043875654180966"]
CHECK_INTERVAL_MIN = 1
CHECK_INTERVAL_MAX = 2
# ====================================================

logging.basicConfig(level=logging.INFO)

# ==================== ХРАНИЛИЩЕ ====================
warns = defaultdict(int)
daily_messages = defaultdict(int)
user_names = {}

# Ранги: user_id -> 1..5
admin_ranks = {}

RANK_NAMES = {
    1: "🔹 Младший модератор",
    2: "🔸 Модератор",
    3: "💠 Старший модератор",
    4: "👑 Администратор",
    5: "🌟 Создатель",
}

RANK_PERMISSIONS = {
    1: ["warn", "unwarn", "mute", "unmute"],
    2: ["warn", "unwarn", "mute", "unmute", "ban", "unban"],
    3: ["warn", "unwarn", "mute", "unmute", "ban", "unban", "kick"],
    4: ["warn", "unwarn", "mute", "unmute", "ban", "unban", "kick", "admins", "st"],
    5: ["warn", "unwarn", "mute", "unmute", "ban", "unban", "kick", "admins", "st", "send", "sendall", "stats", "reset", "announce", "pin", "del"],
}

def get_rank(user_id: int) -> int:
    if user_id == OWNER_ID:
        return 5
    return admin_ranks.get(user_id, 0)

def has_perm(user_id: int, perm: str) -> bool:
    rank = get_rank(user_id)
    if rank == 0:
        return False
    return perm in RANK_PERMISSIONS.get(rank, [])

# ==================== УТИЛИТЫ ====================
def is_allowed_chat(update: Update) -> bool:
    return update.effective_chat.id == ALLOWED_CHAT_ID

async def get_user_from_args(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith("@"):
        username = context.args[0][1:]
        try:
            chat = await context.bot.get_chat(f"@{username}")
            return chat, context.args[1:]
        except TelegramError:
            await update.message.reply_text(f"❌ Не нашёл @{username}")
            return None, []
    elif update.message.reply_to_message:
        user = update.message.reply_to_message.from_user
        chat = await context.bot.get_chat(user.id)
        return chat, list(context.args)
    else:
        await update.message.reply_text("❌ Укажи @username или ответь на сообщение")
        return None, []

def parse_duration(text: str) -> timedelta | None:
    units = {
        "секунда": 1, "секунды": 1, "секунд": 1,
        "минута": 60, "минуты": 60, "минут": 60,
        "час": 3600, "часа": 3600, "часов": 3600,
        "день": 86400, "дня": 86400, "дней": 86400,
        "неделя": 604800, "недели": 604800, "недель": 604800,
    }
    parts = text.lower().strip().split()
    for i in range(len(parts) - 1):
        try:
            num = int(parts[i])
            unit = parts[i + 1]
            if unit in units:
                return timedelta(seconds=num * units[unit])
        except ValueError:
            continue
    return None

async def check_perm(update: Update, perm: str) -> bool:
    uid = update.effective_user.id
    if not has_perm(uid, perm):
        rank = get_rank(uid)
        if rank == 0:
            await update.message.reply_text("❌ У тебя нет прав в этом боте")
        else:
            await update.message.reply_text(f"❌ Твой ранг ({RANK_NAMES[rank]}) не позволяет это делать")
        return False
    return True

# ==================== АКТИВНОСТЬ + ПОДАРКИ ====================
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update):
        return
    if not update.message or not update.effective_user:
        return
    user = update.effective_user
    daily_messages[user.id] += 1
    user_names[user.id] = user.first_name

async def gift_job(context: ContextTypes.DEFAULT_TYPE):
    if not daily_messages:
        await schedule_next_gift(context)
        return

    winner_id = max(daily_messages, key=lambda uid: daily_messages[uid])
    winner_count = daily_messages[winner_id]
    winner_name = user_names.get(winner_id, f"id{winner_id}")

    sorted_users = sorted(daily_messages.items(), key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    top_lines = []
    for i, (uid, cnt) in enumerate(sorted_users[:3]):
        name = user_names.get(uid, f"id{uid}")
        medal = medals[i] if i < 3 else "▪️"
        top_lines.append(f"{medal} {name} — {cnt} сообщ.")

    daily_messages.clear()

    gift_id = random.choice(GIFTS)
    gift_sent = False
    try:
        await context.bot.send_gift(user_id=winner_id, gift_id=gift_id)
        gift_sent = True
    except TelegramError as e:
        logging.warning(f"Подарок не отправлен: {e}")

    top_text = "\n".join(top_lines)
    gift_label = "получает подарок! 🎁" if gift_sent else "должен получить подарок 🎁"

    await context.bot.send_message(
        chat_id=ALLOWED_CHAT_ID,
        text=(
            f"🏆 <b>Итоги активности!</b>\n\n"
            f"<b>Топ участников:</b>\n{top_text}\n\n"
            f"👑 Победитель: <b>{winner_name}</b> ({winner_count} сообщ.) — {gift_label}"
        ),
        parse_mode="HTML"
    )
    await schedule_next_gift(context)

async def schedule_next_gift(context: ContextTypes.DEFAULT_TYPE):
    delay = random.randint(CHECK_INTERVAL_MIN * 3600, CHECK_INTERVAL_MAX * 3600)
    h, m = delay // 3600, (delay % 3600) // 60
    logging.info(f"Следующий подарок через {h}ч {m}мин")
    context.job_queue.run_once(gift_job, when=delay, name="gift_job")

async def post_init(application):
    delay = random.randint(CHECK_INTERVAL_MIN * 3600, CHECK_INTERVAL_MAX * 3600)
    application.job_queue.run_once(gift_job, when=delay, name="gift_job")
    # Выдаём владельцу ранг 5 сразу
    admin_ranks[OWNER_ID] = 5
    logging.info("Бот запущен, таймер активности установлен")

# ==================== /st — ВЫДАТЬ РАНГ ====================
async def st_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "st"): return

    if len(context.args) < 2:
        return await update.message.reply_text(
            "❌ Использование: /st (1-5) @username\n"
            "Пример: /st 3 @username"
        )

    try:
        rank = int(context.args[0])
        if rank < 1 or rank > 5:
            return await update.message.reply_text("❌ Ранг должен быть от 1 до 5")
    except ValueError:
        return await update.message.reply_text("❌ Укажи ранг числом: /st 3 @username")

    # Берём юзера из второго аргумента
    context.args = context.args[1:]
    target, _ = await get_user_from_args(update, context)
    if not target: return

    # Создатель не может быть изменён кроме как самим владельцем
    if target.id == OWNER_ID:
        return await update.message.reply_text("❌ Нельзя изменить ранг создателя")

    # Нельзя выдать ранг выше своего
    my_rank = get_rank(update.effective_user.id)
    if rank >= my_rank:
        return await update.message.reply_text(f"❌ Нельзя выдать ранг >= своего ({RANK_NAMES[my_rank]})")

    admin_ranks[target.id] = rank
    user_names[target.id] = target.first_name

    await update.message.reply_text(
        f"✅ <b>{target.first_name}</b> получил ранг:\n"
        f"{RANK_NAMES[rank]}",
        parse_mode="HTML"
    )

    # Объявление в чат
    await context.bot.send_message(
        chat_id=ALLOWED_CHAT_ID,
        text=(
            f"🎖 <b>Новый администратор!</b>\n\n"
            f"👤 {target.first_name} теперь <b>{RANK_NAMES[rank]}</b>"
        ),
        parse_mode="HTML"
    )

# ==================== /admins — СПИСОК АДМИНОВ ====================
async def admins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "admins"): return

    lines = []
    # Группируем по рангу (5 → 1)
    by_rank = defaultdict(list)
    for uid, rank in admin_ranks.items():
        name = user_names.get(uid, f"id{uid}")
        by_rank[rank].append(name)

    # Добавляем владельца если не в списке
    if OWNER_ID not in admin_ranks:
        by_rank[5].append(user_names.get(OWNER_ID, "Владелец"))

    if not by_rank:
        return await update.message.reply_text("📋 Список администраторов пуст")

    text = "👥 <b>Список администраторов</b>\n\n"
    for rank in sorted(by_rank.keys(), reverse=True):
        names = ", ".join(by_rank[rank])
        text += f"{RANK_NAMES[rank]}\n└ {names}\n\n"

    await update.message.reply_text(text, parse_mode="HTML")

# ==================== /send — ОТПРАВИТЬ В ЧАТ ====================
async def send_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Работает только в личке с ботом
    if update.effective_chat.type != "private":
        return await update.message.reply_text("❌ Эту команду используй в личке с ботом")
    if not await check_perm(update, "send"): return

    if not context.args:
        return await update.message.reply_text(
            "❌ Использование: /send текст сообщения\n"
            "Пример: /send Привет всем!"
        )

    text = " ".join(context.args)
    try:
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            text=f"📢 {text}",
            parse_mode="HTML"
        )
        await update.message.reply_text("✅ Сообщение отправлено в чат!")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /announce — ОБЪЯВЛЕНИЕ С КНОПКОЙ ====================
async def announce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private": return
    if not await check_perm(update, "announce"): return

    if not context.args:
        return await update.message.reply_text(
            "❌ Использование: /announce заголовок | текст\n"
            "Пример: /announce Важно! | Сегодня конкурс"
        )

    full = " ".join(context.args)
    if "|" in full:
        parts = full.split("|", 1)
        title = parts[0].strip()
        body = parts[1].strip()
    else:
        title = "📣 Объявление"
        body = full

    try:
        await context.bot.send_message(
            chat_id=ALLOWED_CHAT_ID,
            text=f"📣 <b>{title}</b>\n\n{body}",
            parse_mode="HTML"
        )
        await update.message.reply_text("✅ Объявление отправлено!")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /stats — СТАТИСТИКА АКТИВНОСТИ ====================
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_perm(update, "stats"): return

    if not daily_messages:
        return await update.message.reply_text("📊 Пока никто ничего не писал в этом периоде")

    sorted_users = sorted(daily_messages.items(), key=lambda x: x[1], reverse=True)
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, (uid, cnt) in enumerate(sorted_users[:10]):
        name = user_names.get(uid, f"id{uid}")
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} {name} — {cnt} сообщ.")

    await update.message.reply_text(
        f"📊 <b>Активность (текущий период)</b>\n\n" + "\n".join(lines),
        parse_mode="HTML"
    )

# ==================== /reset — СБРОСИТЬ СЧЁТЧИКИ ====================
async def reset_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_perm(update, "reset"): return
    daily_messages.clear()
    await update.message.reply_text("🔄 Счётчики активности сброшены")

# ==================== /pin — ЗАКРЕПИТЬ СООБЩЕНИЕ ====================
async def pin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "pin"): return

    if not update.message.reply_to_message:
        return await update.message.reply_text("❌ Ответь на сообщение которое нужно закрепить")

    try:
        await context.bot.pin_chat_message(
            chat_id=ALLOWED_CHAT_ID,
            message_id=update.message.reply_to_message.message_id
        )
        await update.message.reply_text("📌 Сообщение закреплено")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /del — УДАЛИТЬ СООБЩЕНИЕ ====================
async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "del"): return

    if not update.message.reply_to_message:
        return await update.message.reply_text("❌ Ответь на сообщение которое нужно удалить")

    try:
        await context.bot.delete_message(
            chat_id=ALLOWED_CHAT_ID,
            message_id=update.message.reply_to_message.message_id
        )
        await update.message.delete()
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /kick — КИКНУТЬ ====================
async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "kick"): return

    target, rest = await get_user_from_args(update, context)
    if not target: return

    reason = " ".join(rest) if rest else "без причины"
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(
            f"👢 <b>Кик</b>\n👤 {target.first_name}\n📋 Причина: {reason}",
            parse_mode="HTML"
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /warn ====================
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "warn"): return

    target, rest = await get_user_from_args(update, context)
    if not target: return

    reason = " ".join(rest) if rest else "без причины"
    warns[target.id] += 1
    count = warns[target.id]

    text = (
        f"⚠️ <b>Предупреждение</b>\n"
        f"👤 {target.first_name}\n"
        f"📋 Причина: {reason}\n"
        f"🔢 Варнов: {count}/3"
    )

    if count >= 3:
        try:
            await context.bot.ban_chat_member(update.effective_chat.id, target.id)
            text += "\n\n🔨 <b>Забанен за 3 предупреждения!</b>"
            warns[target.id] = 0
        except TelegramError as e:
            text += f"\n❌ Не смог забанить: {e}"

    await update.message.reply_text(text, parse_mode="HTML")

# ==================== /unwarn ====================
async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "unwarn"): return

    target, _ = await get_user_from_args(update, context)
    if not target: return

    if warns[target.id] > 0:
        warns[target.id] -= 1

    await update.message.reply_text(
        f"✅ Снято предупреждение с {target.first_name}\n"
        f"🔢 Осталось варнов: {warns[target.id]}/3"
    )

# ==================== /ban ====================
async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "ban"): return

    target, rest = await get_user_from_args(update, context)
    if not target: return

    duration = None
    reason = "без причины"
    if len(rest) >= 2:
        dur_try = parse_duration(" ".join(rest[-2:]))
        if dur_try:
            duration = dur_try
            reason = " ".join(rest[:-2]) if len(rest) > 2 else "без причины"
        else:
            reason = " ".join(rest)
    elif rest:
        reason = " ".join(rest)

    until_date = datetime.now(timezone.utc) + duration if duration else None
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, target.id, until_date=until_date)
        dur_text = f"на {' '.join(rest[-2:])}" if duration else "навсегда"
        await update.message.reply_text(
            f"🔨 <b>Бан</b>\n👤 {target.first_name}\n📋 Причина: {reason}\n⏱ Срок: {dur_text}",
            parse_mode="HTML"
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /unban ====================
async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "unban"): return

    target, _ = await get_user_from_args(update, context)
    if not target: return

    try:
        await context.bot.unban_chat_member(update.effective_chat.id, target.id)
        await update.message.reply_text(f"✅ {target.first_name} разбанен")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /mute ====================
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "mute"): return

    target, rest = await get_user_from_args(update, context)
    if not target: return

    duration = None
    reason = "без причины"
    if len(rest) >= 2:
        dur_try = parse_duration(" ".join(rest[-2:]))
        if dur_try:
            duration = dur_try
            reason = " ".join(rest[:-2]) if len(rest) > 2 else "без причины"
        else:
            reason = " ".join(rest)
    elif rest:
        reason = " ".join(rest)

    until_date = datetime.now(timezone.utc) + duration if duration else None
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date
        )
        dur_text = f"на {' '.join(rest[-2:])}" if duration else "навсегда"
        await update.message.reply_text(
            f"🔇 <b>Мут</b>\n👤 {target.first_name}\n📋 Причина: {reason}\n⏱ Срок: {dur_text}",
            parse_mode="HTML"
        )
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /unmute ====================
async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed_chat(update): return
    if not await check_perm(update, "unmute"): return

    target, _ = await get_user_from_args(update, context)
    if not target: return

    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, target.id,
            permissions=ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
            )
        )
        await update.message.reply_text(f"✅ {target.first_name} размьючен")
    except TelegramError as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

# ==================== /help — ПАНЕЛЬ КОМАНД ====================
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rank = get_rank(uid)

    if rank == 0:
        return await update.message.reply_text("❌ У тебя нет доступа к командам бота")

    perms = RANK_PERMISSIONS.get(rank, [])

    sections = {
        "👮 Модерация": [],
        "👥 Управление": [],
        "📢 Контент": [],
        "📊 Статистика": [],
    }

    perm_map = {
        "warn":     ("👮 Модерация",  "/warn @username причина"),
        "unwarn":   ("👮 Модерация",  "/unwarn @username"),
        "mute":     ("👮 Модерация",  "/mute @username причина 1 час"),
        "unmute":   ("👮 Модерация",  "/unmute @username"),
        "ban":      ("👮 Модерация",  "/ban @username причина 1 день"),
        "unban":    ("👮 Модерация",  "/unban @username"),
        "kick":     ("👮 Модерация",  "/kick @username причина"),
        "st":       ("👥 Управление", "/st (1-5) @username — выдать ранг"),
        "admins":   ("👥 Управление", "/admins — список администраторов"),
        "send":     ("📢 Контент",    "/send текст — отправить от бота"),
        "announce": ("📢 Контент",    "/announce заголовок | текст"),
        "pin":      ("📢 Контент",    "/pin — закрепить (ответом)"),
        "del":      ("📢 Контент",    "/del — удалить (ответом)"),
        "stats":    ("📊 Статистика", "/stats — активность"),
        "reset":    ("📊 Статистика", "/reset — сбросить счётчики"),
    }

    for perm in perms:
        if perm in perm_map:
            section, desc = perm_map[perm]
            sections[section].append(desc)

    text = f"🛡 <b>Панель команд</b>\nТвой ранг: {RANK_NAMES[rank]}\n\n"
    for section, cmds in sections.items():
        if cmds:
            text += f"<b>{section}</b>\n"
            text += "\n".join(f"  └ {c}" for c in cmds)
            text += "\n\n"

    # /send и /announce работают только в личке
    if rank == 5:
        text += "💡 /send и /announce — только в личке с ботом"

    await update.message.reply_text(text, parse_mode="HTML")

# ==================== /myrank — МОЙ РАНГ ====================
async def myrank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    rank = get_rank(uid)
    if rank == 0:
        await update.message.reply_text("❌ У тебя нет ранга в системе")
    else:
        await update.message.reply_text(
            f"🎖 Твой ранг: <b>{RANK_NAMES[rank]}</b>",
            parse_mode="HTML"
        )

# ==================== ЗАПУСК ====================
def main():
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Чат-команды
    app.add_handler(CommandHandler("warn",    warn_cmd))
    app.add_handler(CommandHandler("unwarn",  unwarn_cmd))
    app.add_handler(CommandHandler("ban",     ban_cmd))
    app.add_handler(CommandHandler("unban",   unban_cmd))
    app.add_handler(CommandHandler("mute",    mute_cmd))
    app.add_handler(CommandHandler("unmute",  unmute_cmd))
    app.add_handler(CommandHandler("kick",    kick_cmd))
    app.add_handler(CommandHandler("pin",     pin_cmd))
    app.add_handler(CommandHandler("del",     del_cmd))
    app.add_handler(CommandHandler("st",      st_cmd))
    app.add_handler(CommandHandler("admins",  admins_cmd))
    app.add_handler(CommandHandler("stats",   stats_cmd))
    app.add_handler(CommandHandler("reset",   reset_cmd))
    app.add_handler(CommandHandler("help",    help_cmd))
    app.add_handler(CommandHandler("myrank",  myrank_cmd))

    # Личка-команды (владелец)
    app.add_handler(CommandHandler("send",     send_cmd))
    app.add_handler(CommandHandler("announce", announce_cmd))

    # Счётчик сообщений
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    print("Бот запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
