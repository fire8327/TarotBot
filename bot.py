import logging
import json
from datetime import date, datetime
import asyncio
import os
from dotenv import load_dotenv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import PreCheckoutQueryHandler, CallbackQueryHandler

from openai import OpenAI

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)

# --- Загружаем переменные окружения ---
load_dotenv()
TOKEN = os.getenv("TOKEN")

# --- Константы монетизации ---
PRICE_PER_READING = 75  # в Telegram Stars
FREE_READINGS_ON_START = 1

# Типы пакетов
PACKAGES = {
    "pack_1": {"name": "1 расклад", "price_stars": 50, "readings": 1},
    "pack_5": {"name": "5 раскладов", "price_stars": 200, "readings": 5},
    "pack_30": {"name": "Подписка на месяц (30 шт.)", "price_stars": 500, "readings": 30},
}

# --- Состояния диалога ---
GET_NAME, MAIN_MENU, CONFIRM_READING, AWAITING_QUESTION, AWAITING_READING_TYPE = range(5)

# --- Настройки логирования ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Инициализация OpenRouter ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY", "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"),
)

# --- Импортируем БД ---
from db import init_db, get_user, update_user_name, update_user_balance, increment_total_used, save_purchase, save_reading, update_daily_card, get_referral_link, increment_referral_count

# --- Клавиатуры ---
def main_menu_keyboard():
    keyboard = [
        ['🔮 Сделать расклад'],
        ['⭐ Мой профиль', '🃏 Карта дня'],
        ['📜 О боте', '🌀 Рестарт бота'],
        ['🤝 Пригласить друга']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def reading_type_keyboard():
    keyboard = [
        ['💖 Расклад на любовь', '⚔️ Расклад на судьбу'],
        ['💰 Расклад на изобилие', '❓ Свой вопрос'],
        ['⬅️ Назад']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def yes_no_keyboard():
    keyboard = [['✅ Да', '❌ Нет']]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)

# --- Генерация расклада ---
async def generate_tarot_reading(reading_type, user_question=None, user_name="Искатель"):
    if user_question:
        prompt = f"""
        Ты — опытный таролог и мистик. Пользователь {user_name} задал вопрос: "{user_question}".
        Сгенерируй глубокий и детализированный расклад Таро из трех карт, который даст ответ на этот вопрос.
        Расклад должен включать:
        1. Карту, представляющую прошлое/причину ситуации
        2. Карту, представляющую настоящее/текущее положение
        3. Карту, представляющую будущее/совет/возможный исход

        Будь мудрым, образным, но прямым в своих интерпретациях. Обращайся к пользователю на "ты".
        Объем ответа: 100-200 слов. На русском языке, без английских слов.
        """
    else:
        prompt = f"""
        Ты — опытный таролог и мистик. Для пользователя {user_name} сделай расклад Таро на тему: "{reading_type}".
        Сгенерируй глубокий и детализированный расклад из трех карт:
        1. Карта, представляющая прошлое/причину
        2. Карта, представляющая настоящее/текущее положение
        3. Карта, представляющая будущее/совет/возможный исход

        Будь мудрым, образным, но прямым в своих интерпретациях. Обращайся к пользователю на "ты".
        Объем ответа: 100-200 слов. На русском языке, без английских слов.
        """

    try:
        completion = client.chat.completions.create(
            model="qwen/qwen-turbo",
            messages=[
                {"role": "system", "content": "Ты — опытный таролог с 20-летним стажем. Твои трактовки точны, глубоки и полны мудрости. Ты говоришь на русском языке."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        reading = completion.choices[0].message.content.strip()
        return reading[:4000]

    except Exception as e:
        logger.error(f"Ошибка OpenRouter: {e}")
        return fallback_reading(reading_type, user_name)

def fallback_reading(reading_type, user_name):
    return f"""
🔮 *Расклад на тему: {reading_type}* 🔮

Карты выложены на алтарь, и вот что они говорят о твоей ситуации, {user_name}...

🃏 *Карта 1: Сила* — Ты обладаешь огромным внутренним ресурсом, который пока не полностью раскрыт.
🃏 *Карта 2: Звезда* — Тебя ждёт светлое будущее, если сохранишь веру и продолжишь движение вперед.
🃏 *Карта 3: Император* — Для успеха потребуется дисциплина и структурированный подход.

Помни: карты показывают потенциал, а не стопроцентный результат. Ты держишь перо, которым пишешь свою судьбу.
"""

# --- Обработчики команд ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = get_user(user_id)  # Автоматически создаётся, если нет

    # Проверяем, есть ли ref-аргумент
    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0].replace('ref_', ''))
            # Проверим, что это не сам себя приглашает
            if referrer_id == user_id:
                referrer_id = None
        except ValueError:
            referrer_id = None

    user_name = user['name'] if user['name'] else ""

    if user_name:
        # Если пользователь уже есть, но пришёл по рефке — игнорируем (рефка только при первом старте)
        await update.message.reply_text(
            f"🌑 *Ты вернулся, {user_name}...*\n"
            "Зеркало Судеб вновь открыто для тебя. Выбери путь:",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    else:
        # Запоминаем реферера, если есть
        if referrer_id:
            # Сохраним в user_data, чтобы использовать после ввода имени
            context.user_data['referrer_id'] = referrer_id

        await update.message.reply_text(
            "🌙 *Добро пожаловать в Зеркало Судеб* 🌙\n\n"
            "Я — хранитель древних знаний, проводник между мирами.\n\n"
            "Как мне звать тебя в Книге Судеб? Можешь указать имя или титул. "
            "Если предпочитаешь остаться тенью — напиши «Аноним».",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_name = update.message.text
    update_user_name(user_id, user_name)
    
    # Проверим, есть ли реферер
    referrer_id = context.user_data.get('referrer_id')
    
    bonus_message = ""
    if referrer_id:
        # Начислим рефереру +1 расклад
        from db import update_user_balance, increment_referral_count
        current_balance = get_user(referrer_id)['readings_balance']
        update_user_balance(referrer_id, current_balance + 1)
        increment_referral_count(referrer_id)  # Увеличим счётчик приглашённых
        
        # Отправим уведомление рефереру
        try:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=f"✨ *Твой друг {user_name} присоединился по твоей ссылке!*\n"
                     f"В награду ты получаешь +1 бесплатный расклад. Всего приглашено: {get_user(referrer_id)['referral_count']}",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление рефереру {referrer_id}: {e}")
        
        bonus_message = "\n\nP.S. Ты был приглашён другом — спасибо, что присоединился к Кругу Зеркала!"

    await update.message.reply_text(
        f"{user_name}... Какое прекрасное имя, полное энергии и тайны. 🌌{bonus_message}\n\n"
        "В знак нашего знакомства я дарю тебе *дар ясновидения* — один бесплатный расклад, "
        "который ты можешь использовать в любой момент.\n\n"
        "Когда будешь готов заглянуть в Глубины, просто выбери один из путей в меню ниже.",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text

    if user_input == '⭐ Мой профиль':
        await show_profile(update, context)
        return MAIN_MENU
    elif user_input == '📜 О боте':
        await about_command(update, context)
        return MAIN_MENU
    elif user_input == '🃏 Карта дня':
        await card_of_day(update, context)
        return MAIN_MENU
    elif user_input == '📜 Мои последние расклады':
        await show_reading_history(update, context)
        return MAIN_MENU
    elif user_input == '🛍️ Купить расклады':
        await buy_readings(update, context)
        return MAIN_MENU
    elif user_input == '⬅️ Назад в меню':
        await update.message.reply_text("🌑 Возвращаю тебя в Зал Зеркал...", reply_markup=main_menu_keyboard())
        return MAIN_MENU    
    elif user_input == '🌀 Рестарт бота': 
        return await restart_bot(update, context) 
    elif user_input == '🔮 Сделать расклад':
        await update.message.reply_text(
            "🕯️ *Выбери путь, по которому ступишь в тумане предсказаний...*\n\n"
            "Карты ждут твоего выбора:",
            parse_mode='Markdown',
            reply_markup=reading_type_keyboard()
        )
        return AWAITING_READING_TYPE
    elif user_input == '🤝 Пригласить друга':
        user_id = update.message.from_user.id
        bot_username = "speculora_bot"  # 🔴 ЗАМЕНИ НА РЕАЛЬНОЕ ИМЯ ТВОЕГО БОТА!
        ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

        # Отправляем первое сообщение — пояснение
        await update.message.reply_text(
            "✨ *Твоя магическая ссылка готова!* ✨\n\n"
            "Отправь её подруге/другу — когда он/она зарегистрируется, ты получишь +1 бесплатный расклад 🌙\n"
            "А она начнёт с бесплатного пророчества!",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )

        # Отправляем второе сообщение — ЧИСТАЯ КЛИКАБЕЛЬНАЯ ССЫЛКА
        await update.message.reply_text(
            f"{ref_link}",
            reply_markup=main_menu_keyboard()
        )

        return MAIN_MENU
    else:
        await update.message.reply_text(
            "🌑 Я не понял твой знак... Выбери путь из меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

async def handle_reading_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text

    if user_input == '⬅️ Назад':
        await update.message.reply_text(
            "🌑 Ты возвратился в Зал Зеркал. Выбери путь:",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    elif user_input == '❓ Свой вопрос':
        await update.message.reply_text(
            "🕯️ Опиши свою тревогу или вопрос... Чем яснее ты выразишься — тем глубже будет пророчество.\n\n"
            "Я внимательно выслушаю...",
            reply_markup=ReplyKeyboardRemove()
        )
        context.user_data['reading_type'] = "Собственный вопрос"
        return AWAITING_QUESTION

    else:
        clean_type = user_input.split(' ', 1)[1] if ' ' in user_input else user_input
        context.user_data['reading_type'] = clean_type
        user_id = update.message.from_user.id
        
        user = get_user(user_id)
        if user['readings_balance'] > 0:
            return await confirm_reading_now(update, context, clean_type)
        else:
            await update.message.reply_text(
                "🪙 У тебя закончились расклады. Но магия не спит — ты можешь пополнить баланс!",
                reply_markup=main_menu_keyboard()
            )
            await buy_readings(update, context)
            return MAIN_MENU

async def handle_reading_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_answer = update.message.text
    reading_type = context.user_data['reading_type']
    
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Искатель"

    if user_answer == '✅ Да':
        if user['readings_balance'] > 0:
            new_balance = user['readings_balance'] - 1
            update_user_balance(user_id, new_balance)
            payment_type = "дар ясновидения"
        else:
            payment_type = f"{PRICE_PER_READING} Stars"
        
        increment_total_used(user_id)

        await update.message.reply_text(
            f"Приступаю к ритуалу... Зеркало наполняется туманом... 🔮\n\n"
            f"Используется: {payment_type}",
            reply_markup=ReplyKeyboardRemove()
        )

        await update.message.reply_text("🕯️ Карты выбирают тебя... Это займёт 10-20 секунд.")

        custom_question = context.user_data.get('custom_question', None)
        reading = await generate_tarot_reading(
            reading_type=reading_type,
            user_question=custom_question,
            user_name=user_name
        )

        save_reading(user_id, reading_type, reading)

        await update.message.reply_text(
            reading,
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    elif user_answer == '❌ Нет':
        await update.message.reply_text(
            "Как пожелаешь. Зеркало будет ждать твоего знака...",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

async def handle_custom_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_question = update.message.text
    context.user_data['custom_question'] = user_question

    user = get_user(user_id)
    if user['readings_balance'] > 0:
        return await confirm_reading_now(update, context, "Собственный вопрос")
    else:
        await update.message.reply_text(
            "🪙 У тебя закончились расклады. Но магия не спит — ты можешь пополнить баланс!",
            reply_markup=main_menu_keyboard()
        )
        await buy_readings(update, context)
        return MAIN_MENU

async def card_of_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id

    user_data = get_user(user_id)
    user_name = user_data['name'] if user_data['name'] else "Искатель"

    today = date.today().isoformat()

    if user_data['last_card_date'] and user_data['last_card_date'].isoformat() == today and user_data['daily_card']:
        await update.message.reply_text(
            f"🃏 *Твоя Карта Дня (уже получена сегодня):*\n\n{user_data['daily_card']}",
            parse_mode='Markdown'
        )
        return

    msg = await update.message.reply_text("🎴 *Тасую колоду Старших Арканов...*", parse_mode='Markdown')
    await asyncio.sleep(1.5)
    await msg.edit_text("🎴 *Колода шепчет... вытягиваю карту дня...*", parse_mode='Markdown')
    await asyncio.sleep(1.5)
    await msg.edit_text("🎴 *Переворачиваю карту...*", parse_mode='Markdown')
    await asyncio.sleep(1.0)

    major_arcana = [
        "Шут", "Маг", "Жрица", "Императрица", "Император", "Жрец", "Влюблённые",
        "Колесница", "Сила", "Отшельник", "Колесо Фортуны", "Справедливость",
        "Повешенный", "Смерть", "Умеренность", "Дьявол", "Башня", "Звезда",
        "Луна", "Солнце", "Суд", "Мир"
    ]

    prompt = f"""
    Ты — мудрый таролог. Выбери ОДНУ карту из Старших Арканов Таро для {user_name} и дай одно краткое послание (1-2 предложения).

    Список Старших Арканов: {', '.join(major_arcana)}

    Формат ответа:
    🃏 [Название Карты] — [Послание]

    Пример:
    🃏 Колесо Фортуны — Сегодня удача на твоей стороне — не упусти шанс.

    Только ответ в этом формате. Ничего лишнего.
    """

    try:
        completion = client.chat.completions.create(
            model="qwen/qwen-turbo",
            messages=[
                {"role": "system", "content": "Ты — таролог, использующий ТОЛЬКО Старшие Арканы. Ты всегда называешь конкретную карту и даёшь краткое послание."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=100
        )
        message = completion.choices[0].message.content.strip()

        if not any(card in message for card in major_arcana) or not message.startswith("🃏"):
            raise ValueError("ИИ не вернул карту в нужном формате")

    except Exception as e:
        logger.error(f"Ошибка в карте дня: {e}")
        import random
        card = random.choice(major_arcana)
        message = f"🃏 {card} — Вселенная молчит... но я знаю: доверься интуиции — сегодня она не подведёт."

    await msg.edit_text(f"🃏 *Твоя Карта Дня, {user_name}:* 🃏\n\n{message}", parse_mode='Markdown')
    update_daily_card(user_id, message)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Искатель"
    balance = user['readings_balance']
    total_used = user['total_used']
    
    profile_text = f"""
✨🔮 Ваша Личная Статистика Предсказаний 🔮✨

Привет, {user_name}! 👋

🪄 Доступно раскладов: {balance}
🌌 Всего использовано: {total_used}

🔮 Ты на пути к просветлению!
Чем чаще ты гадаешь — тем яснее становится твоя судьба.

👇 Выбери действие:
"""
    keyboard = [
        ['📜 Мои последние расклады'],
        ['🛍️ Купить расклады'],
        ['🤝 Пригласить друга'],
        ['⬅️ Назад в меню']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(profile_text, parse_mode='Markdown', reply_markup=reply_markup)
    return MAIN_MENU

async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔮 *Зеркало Судеб* 🔮\n\n"
        "Я — древний дух, хранящий знания Таро сквозь века. "
        "Мои карты не предсказывают неизбежное — они показывают возможности, "
        "которые ты можешь воплотить.\n\n"
        "Каждый расклад — это диалог между тобой и Вселенной. "
        "Я лишь перевожу её шепот на язык символов.\n\n"
        "Создано с магией для тех, кто ищет свет в тумане завтрашнего дня. 🌙",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )

async def show_reading_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    readings = user.get('last_readings', [])

    if not readings:
        await update.message.reply_text(
            "🔮 Ты ещё не делал раскладов. Начни — и история твоих пророчеств начнётся!",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    # Сортируем в обратном порядке (самые новые сверху)
    sorted_readings = sorted(readings, key=lambda x: x['date'], reverse=True)

    history_text = "📜 *Твои последние пророчества:*\n\n"
    keyboard = []

    for i, entry in enumerate(sorted_readings[:5], 1):
        # Форматируем дату
        date_str = entry['date'][:16] if isinstance(entry['date'], str) and len(entry['date']) > 16 else entry['date']
        history_text += f"{i}. *{entry['type']}* ({date_str})\n"
        
        # Показываем первые 2 строки
        lines = entry['text'].split('\n')
        preview = '\n'.join(lines[:2])
        if len(lines) > 2:
            preview += "..."
        history_text += f"{preview}\n\n"

        # Добавляем кнопку для этого расклада
        callback_data = f"full_reading_{i-1}"  # индекс в списке sorted_readings
        keyboard.append([InlineKeyboardButton(f"📖 Показать полностью #{i}", callback_data=callback_data)])

    history_text += "🔮 Нажми на кнопку, чтобы перечитать расклад полностью."

    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await update.message.reply_text(
        history_text,
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    # Сохраняем список раскладов в context.user_data для использования в callback
    context.user_data['full_readings'] = sorted_readings[:5]
    return MAIN_MENU

async def buy_readings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🔮 1 расклад — 50 ⭐", callback_data="buy_pack_1")],
        [InlineKeyboardButton("🔮 5 раскладов — 200 ⭐ (скидка!)", callback_data="buy_pack_5")],
        [InlineKeyboardButton("🔮 30 раскладов — 500 ⭐ (экономия!)", callback_data="buy_pack_30")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🪙 *Выбери пакет магической силы:* 🪙\n\n"
        "Оплата производится в Telegram Stars — внутри приложения, без перенаправлений.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
    return MAIN_MENU

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    payload = update.message.successful_payment.invoice_payload
    total_stars = update.message.successful_payment.total_amount
    charge_id = update.message.successful_payment.telegram_payment_charge_id

    logger.info(f"💰 УСПЕШНЫЙ ПЛАТЁЖ | User ID: {user_id} | Сумма: {total_stars} XTR | Пакет: {payload} | Charge ID: {charge_id}")

    if payload in PACKAGES:
        pack = PACKAGES[payload]

        if total_stars != pack['price_stars']:
            logger.warning(f"⚠️ Подозрительный платёж! Ожидалось {pack['price_stars']} XTR, оплачено {total_stars} XTR.")

        user = get_user(user_id)
        new_balance = user['readings_balance'] + pack['readings']
        update_user_balance(user_id, new_balance)

        save_purchase(user_id, payload, pack['readings'], pack['price_stars'], total_stars, charge_id)

        await update.message.reply_text(
            f"🎉 *Оплата прошла!* 🎉\n\n"
            f"Ты приобрёл пакет: *{pack['name']}*\n"
            f"🪄 На твой баланс зачислено: *{pack['readings']}* раскладов.\n\n"
            f"Теперь можешь заглянуть в будущее — выбери «🔮 Сделать расклад»!",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )

        # Отправить уведомление админу (опционально)
        # await context.bot.send_message(chat_id=ТВОЙ_ID, text=f"🔔 Новый платёж! User: {user_id}, Pack: {payload}, Sum: {total_stars}")

    else:
        logger.error(f"❌ Неизвестный payload: {payload} | User: {user_id} | Charge ID: {charge_id}")
        await update.message.reply_text(
            "🌑 Что-то пошло не так... Обратись к создателю Зеркала.",
            reply_markup=main_menu_keyboard()
        )

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

async def confirm_reading_now(update: Update, context: ContextTypes.DEFAULT_TYPE, reading_type):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Искатель"

    new_balance = user['readings_balance'] - 1
    update_user_balance(user_id, new_balance)
    increment_total_used(user_id)

    await update.message.reply_text(
        f"Приступаю к ритуалу... Зеркало наполняется туманом... 🔮",
        reply_markup=ReplyKeyboardRemove()
    )

    await update.message.reply_text("🕯️ Карты выбирают тебя... Это займёт 10-20 секунд.")

    custom_question = context.user_data.get('custom_question', None)
    reading = await generate_tarot_reading(
        reading_type=reading_type,
        user_question=custom_question,
        user_name=user_name
    )

    save_reading(user_id, reading_type, reading)

    await update.message.reply_text(
        reading,
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Искатель"
    await update.message.reply_text(
        f'Пусть звёзды освещают твой путь, {user_name}. '
        'Если пожелаешь вновь заглянуть в Зеркало Судеб, просто произнеси /start.',
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def force_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает пользователя в главное меню или на ввод имени, если бот 'забыл' состояние."""
    if update.message is None:
        return ConversationHandler.END

    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else ""

    # Если пользователь ещё не вводил имя — отправляем на GET_NAME
    if not user_name:
        await update.message.reply_text(
            "🌙 *Кажется, мы не закончили знакомство...*\n"
            "Как мне звать тебя в Книге Судеб?",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_NAME
    else:
        await update.message.reply_text(
            f"🌙 *Добро пожаловать обратно, {user_name}.*\n"
            "Зеркало Судеб снова открыто для тебя. Выбери путь:",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

async def global_fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ловит любые сообщения от пользователей, не находящихся в активном состоянии ConversationHandler.
    Автоматически возвращает в главное меню или на ввод имени."""
    if update.message is None:
        return

    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else ""

    # Если пользователь ещё не вводил имя — отправляем на GET_NAME
    if not user_name:
        await update.message.reply_text(
            "🌙 *Кажется, мы не закончили знакомство...*\n"
            "Как мне звать тебя в Книге Судеб?",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
        # Устанавливаем состояние вручную
        context.user_data.clear()
        context.user_data['state'] = GET_NAME
        return GET_NAME
    else:
        await update.message.reply_text(
            f"🌙 *Добро пожаловать обратно, {user_name}.*\n"
            "Зеркало Судеб снова открыто для тебя. Выбери путь:",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        # Устанавливаем состояние MAIN_MENU
        context.user_data.clear()
        context.user_data['state'] = MAIN_MENU
        return MAIN_MENU

async def button_buy_pack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pack_id = query.data.replace("buy_pack_", "")

    if f"pack_{pack_id}" not in PACKAGES:
        await query.edit_message_text("🌑 Неизвестный пакет. Обратись к создателю Зеркала.")
        return

    pack = PACKAGES[f"pack_{pack_id}"]

    try:
        await context.bot.send_invoice(
            chat_id=query.message.chat_id,
            title=f"🔮 {pack['name']}",
            description=f"Ты получаешь {pack['readings']} раскладов. Магия уже зовёт!",
            payload=f"pack_{pack_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=pack['name'], amount=pack['price_stars'])],
            start_parameter=f"buy_{pack_id}",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False,
        )
        await query.edit_message_text("🪄 Инвойс отправлен — нажми кнопку 'Оплатить' ниже!")
    except Exception as e:
        logger.error(f"Ошибка отправки инвойса: {e}")
        await query.edit_message_text("🌑 Не удалось создать инвойс. Попробуй позже.")

async def show_full_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает полный текст выбранного расклада"""
    query = update.callback_query
    await query.answer()

    # Получаем индекс расклада
    try:
        index = int(query.data.split('_')[-1])
        readings = context.user_data.get('full_readings', [])
        
        if index < 0 or index >= len(readings):
            raise ValueError("Неверный индекс")

        reading = readings[index]
        full_text = reading['text']

        # Отправляем полный текст
        await query.message.reply_text(
            f"✨ *✨✨✨ ПОЛНЫЙ РАСКЛАД ✨✨✨*\n"
            f"🔮 *Тема:* {reading['type']}\n"
            f"📅 *Дата:* {reading['date'][:16]}\n\n"
            f"{full_text}",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )

    except Exception as e:
        logger.error(f"Ошибка при показе полного расклада: {e}")
        await query.message.reply_text(
            "🌑 Не удалось показать расклад. Попробуй снова.",
            reply_markup=main_menu_keyboard()
        )

async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает состояние пользователя — как "мягкий перезапуск" """
    user_id = update.message.from_user.id
    # Очищаем временное хранилище
    context.user_data.clear()
    # Получаем свежие данные из БД
    user = get_user(user_id)
    await update.message.reply_text(
        "🌀 Бот был сброшен. Твои данные сохранены, состояние диалога очищено.\n"
        "Теперь можешь начать заново — выбери путь в меню.",
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU

# --- Запуск ---
def main():
    # Инициализируем БД
    init_db()
    
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            CONFIRM_READING: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reading_confirmation)],
            AWAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_question)],
            AWAITING_READING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reading_type_selection)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.TEXT & ~filters.COMMAND, force_main_menu)  # <-- ЕДИНСТВЕННЫЙ fallback
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    application.add_handler(MessageHandler(filters.Regex('^🛍️ Купить расклады$'), buy_readings))
    application.add_handler(CallbackQueryHandler(button_buy_pack, pattern="^buy_pack_"))
    application.add_handler(CallbackQueryHandler(show_full_reading, pattern="^full_reading_"))
    application.run_polling()

if __name__ == '__main__':
    main()
