import logging
import asyncio
import os
import random
from datetime import date, datetime
from dotenv import load_dotenv

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    CallbackQueryHandler,
    PreCheckoutQueryHandler
)

from openai import OpenAI

# --- Загружаем переменные окружения ---
load_dotenv()
TOKEN = os.getenv("TOKEN")

# --- 🔐 Администраторы (кому разрешено запускать рассылку) ---
ADMIN_USER_IDS = {780161853}

# --- 🔑 КОНСТАНТЫ ДЛЯ БЫСТРОЙ НАСТРОЙКИ ---
BOT_VERSION = "v1.11"  # <-- МЕНЯЙ ЭТУ ВЕРСИЮ ПРИ КАЖДОМ ДЕПЛОЕ
ACTIVE_USERS_DAYS = 7  # Рассылка обновления пользователям, активным за последние N дней
STAR_PRICE_PER_READING = 50  # Цена одного расклада в ⭐
REFERRAL_BONUS_READINGS = 1  # Сколько раскладов даём за приглашение

# --- Пакеты для покупки ---
PACKAGES = {
    "pack_1": {"name": "1 расклад", "price_stars": STAR_PRICE_PER_READING, "readings": 1},
    "pack_5": {"name": "5 раскладов", "price_stars": STAR_PRICE_PER_READING * 4, "readings": 5},
    "pack_30": {"name": "Подписка на месяц (30 шт.)", "price_stars": STAR_PRICE_PER_READING * 10, "readings": 30},
}

# --- Состояния диалога ---
GET_NAME, MAIN_MENU, CONFIRM_READING, AWAITING_QUESTION, AWAITING_READING_TYPE = range(5)

# --- Настройки логирования ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Инициализация OpenRouter ---
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    default_headers={
        "HTTP-Referer": "https://t.me/speculora_bot",
        "X-Title": "Speculo Tarot Bot"
    }
)

# --- Импортируем БД ---
from db import (
    init_db, get_user, update_user_name, update_user_balance, increment_total_used,
    save_purchase, save_reading, update_daily_card, increment_referral_count,
    update_user_last_active, increment_free_readings_used, update_conversion_step,
    update_user_last_update_notified, get_active_users
)

# --- 🎴 Списки карт ---
TAROT_PREVIEW_CARDS = [
    {"card": "Шут", "hint": "Тебя ждёт неожиданный поворот — готов ли ты рискнуть?"},
    {"card": "Маг", "hint": "Сегодня ты можешь создать реальность — какой жест сделаешь первым?"},
    {"card": "Жрица", "hint": "Интуиция шепчет — прислушайся к ней до полудня."},
    {"card": "Императрица", "hint": "Энергия изобилия рядом — открой дверь для неё."},
    {"card": "Император", "hint": "Для успеха нужна структура — распланируй день."},
    {"card": "Жрец", "hint": "Совет мудреца придет оттуда, откуда не ждёшь."},
    {"card": "Влюблённые", "hint": "Выбор сердца или разума? Слушай первое."},
    {"card": "Колесница", "hint": "Ты на пороге победы — не сбавляй темп."},
    {"card": "Сила", "hint": "Твоя внутренняя сила просит проявиться — где ты её подавляешь?"},
    {"card": "Отшельник", "hint": "Пора уединиться — ответ внутри тебя."},
    {"card": "Колесо Фортуны", "hint": "Удача на подходе — не упусти момент после 18:00."},
    {"card": "Справедливость", "hint": "Вселенная восстанавливает баланс — будь честен с собой."},
    {"card": "Повешенный", "hint": "Иногда нужно остановиться — чтобы увидеть путь."},
    {"card": "Смерть", "hint": "Старое уходит — не цепляйся, освободи место для нового."},
    {"card": "Умеренность", "hint": "Ищи золотую середину — в этом твой ключ."},
    {"card": "Дьявол", "hint": "Что держит тебя в плену? Осознай — и освободись."},
    {"card": "Башня", "hint": "Рухнет иллюзия — но за ней будет правда."},
    {"card": "Звезда", "hint": "Надежда возвращается — что ты должен отпустить, чтобы встретить её?"},
    {"card": "Луна", "hint": "Не всё то, чем кажется — доверься интуиции, а не страху."},
    {"card": "Солнце", "hint": "Ты на свету — действуй, не бойся быть собой."},
    {"card": "Суд", "hint": "Пришло время пробуждения — ответь на зов души."},
    {"card": "Мир", "hint": "Цикл завершён — ты готов к новому уровню."},
]

EXCLUSIVE_CARDS = [
    {"card": "Ангел Хранитель", "meaning": "Ты под защитой высших сил. Проси — и получишь."},
    {"card": "Зеркало Кармы", "meaning": "Сегодня твои поступки вернутся утроенными. Действуй с любовью."},
    {"card": "Врата Времени", "meaning": "Тебе открыта возможность изменить прошлое — через прощение."},
    {"card": "Ключ Судьбы", "meaning": "Ты держишь ключ от двери, за которой твой следующий уровень."},
    {"card": "Сердце Мира", "meaning": "Когда ты в гармонии с собой — весь мир откликается."},
    {"card": "Око Вселенной", "meaning": "Ты замечен. Твои намерения важны — формулируй их чётко."},
    {"card": "Река Вечности", "meaning": "Ты в потоке. Не сопротивляйся — доверься течению."},
]

# --- 🎛️ КЛАВИАТУРЫ ---
def main_menu_keyboard():
    keyboard = [
        ['🔮 Сделать расклад'],
        ['⭐ Мой профиль', '🃏 Карта дня'],
        ['📜 О боте'],
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

# --- 🧩 ОСНОВНЫЕ ОБРАБОТЧИКИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)

    referrer_id = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0].replace('ref_', ''))
            if referrer_id == user_id:
                referrer_id = None
        except ValueError:
            referrer_id = None

    user_name = user['name'] if user['name'] else ""

    if user_name:
        await update.message.reply_text(
            f"🌑 *Ты вернулся, {user_name}...*\n"
            "Зеркало Судеб вновь открыто для тебя. Выбери путь:",
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    else:
        if referrer_id:
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

    referrer_id = context.user_data.get('referrer_id')
    bonus_message = ""

    current_balance = get_user(user_id)['readings_balance']
    update_user_balance(user_id, current_balance + 1)

    if referrer_id:
        try:
            referrer = get_user(referrer_id)
            if referrer and referrer.get('name'):
                ref_balance = referrer['readings_balance']
                update_user_balance(referrer_id, ref_balance + REFERRAL_BONUS_READINGS)
                increment_referral_count(referrer_id)

                save_purchase(
                    user_id=referrer_id,
                    payload="referral_bonus",
                    readings=REFERRAL_BONUS_READINGS,
                    price_stars=0,
                    actual_amount=0,
                    charge_id=f"ref_{user_id}"
                )

                try:
                    await context.bot.send_message(
                        chat_id=referrer_id,
                        text=f"✨ *Твой друг {user_name} присоединился по твоей ссылке!*\n"
                             f"В награду ты получаешь +{REFERRAL_BONUS_READINGS} бесплатный расклад. Всего приглашено: {referrer.get('referral_count', 0)}",
                        parse_mode='Markdown'
                    )
                except Exception as e:
                    logger.warning(f"Не удалось отправить сообщение рефереру {referrer_id}: {e}")

                bonus_message = "\n\nP.S. Ты был приглашён другом — спасибо, что присоединился к Кругу Зеркала!"

        except Exception as e:
            logger.error(f"Ошибка при обработке реферера {referrer_id} для пользователя {user_id}: {e}")

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
    user_id = update.message.from_user.id
    user_input = update.message.text

    update_user_last_active(user_id)

    if user_input == '⭐ Мой профиль':
        await show_profile(update, context)
        return MAIN_MENU
    elif user_input == '📜 О боте':
        await about_command(update, context)
        return MAIN_MENU
    elif user_input == '🃏 Карта дня':
        await card_of_day(update, context)
        return MAIN_MENU
    elif user_input == '🔮 Сделать расклад':
        await update.message.reply_text(
            "🕯️ *Выбери путь, по которому ступишь в тумане предсказаний...*\n\n"
            "Карты ждут твоего выбора:",
            parse_mode='Markdown',
            reply_markup=reading_type_keyboard()
        )
        return AWAITING_READING_TYPE
    elif user_input == '🤝 Пригласить друга':
        await invite_friend(update, context)
        return MAIN_MENU
    elif user_input == '🛍️ Купить расклады':
        await buy_readings(update, context)
        return MAIN_MENU
    elif user_input == '📜 Мои последние расклады':
        await show_reading_history(update, context)
        return MAIN_MENU
    else:
        await update.message.reply_text(
            "🌑 Я не понял твой знак... Выбери путь из меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

# --- 🎴 ГЕНЕРАЦИЯ РАСКЛАДОВ ---
async def generate_full_reading(reading_type, user_question=None, user_name="Искатель", forced_card=None):
    if forced_card:
        prompt = f"""
        Ты — опытный таролог с 20-летним стажем. Пользователь {user_name} уже увидел карту: **{forced_card['card']}** — "{forced_card['hint']}".
        Сделай расклад на тему: "{reading_type}", **обязательно включив эту карту как одну из трёх ключевых** (прошлое, настоящее или будущее — выбери логично).
        Также включи:
        1. Ещё 2 карты — с детальной трактовкой.
        2. Какая стихия (огонь, вода, воздух, земля) управляет этим раскладом? Почему?
        3. Какое одно действие (ритуал/жест/мысль) усилит позитивную энергию? Опиши его просто — чтобы можно было сделать сегодня.
        4. Какая карта защищает тебя в этот период? Как использовать её энергию?
        5. Прогноз на завтра — что тебя ждёт, если следовать советам карт?
        Объём: 250-400 слов. Только на русском. Обращайся на "ты".
        """
    else:
        base_prompt = f"""
        Ты — опытный таролог и мистик. {"Пользователь " + user_name + " задал вопрос: \"" + user_question + "\"." if user_question else f"Для пользователя {user_name} сделай расклад на тему: \"{reading_type}\"."}
        Сгенерируй глубокий и детализированный расклад Таро из трех карт.
        Также включи:
        - Стихию дня
        - Ритуал/действие
        - Защитную карту
        - Прогноз на завтра
        Будь мудрым, образным, но прямым. Обращайся на "ты".
        Объем: 250-400 слов. Только на русском.
        """
        prompt = base_prompt

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

def generate_free_preview(reading_type, user_name):
    card_data = random.choice(TAROT_PREVIEW_CARDS)
    return card_data, f"""
🔮 *{reading_type}* — Зеркало показывает тебе первую карту...
🃏 *Карта Судьбы:* **{card_data['card']}**  
{card_data['hint']}  
✨ *Полная трактовка + ритуал дня + защитная карта — доступна за {STAR_PRICE_PER_READING} ⭐ или при приглашении друга 🌙*
Ты держишь нить своей судьбы, {user_name}. Решай — дернуть за неё или отпустить...
"""

def fallback_reading(reading_type, user_name):
    return f"""
🔮 *Расклад на тему: {reading_type}* 🔮
Карты выложены на алтарь, и вот что они говорят о твоей ситуации, {user_name}...
🃏 *Карта 1: Сила* — Ты обладаешь огромным внутренним ресурсом, который пока не полностью раскрыт.
🃏 *Карта 2: Звезда* — Тебя ждёт светлое будущее, если сохранишь веру и продолжишь движение вперед.
🃏 *Карта 3: Император* — Для успеха потребуется дисциплина и структурированный подход.
Помни: карты показывают потенциал, а не стопроцентный результат. Ты держишь перо, которым пишешь свою судьбу.
"""

# --- 🔄 ОБРАБОТЧИКИ ДИАЛОГОВ ---
async def handle_reading_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text

    if user_input == '⬅️ Назад':
        await update.message.reply_text("🌑 Ты возвратился в Зал Зеркал. Выбери путь:", reply_markup=main_menu_keyboard())
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
        user_name = user['name'] if user['name'] else "Искатель"

        if user['readings_balance'] > 0:
            return await confirm_reading_now(update, context, clean_type)
        else:
            card_data, preview_text = generate_free_preview(clean_type, user_name)
            context.user_data['preview_card'] = card_data

            increment_free_readings_used(user_id)
            update_conversion_step(user_id, 'saw_preview')

            await update.message.reply_text(preview_text, parse_mode='Markdown', reply_markup=main_menu_keyboard())

            keyboard = [
                [InlineKeyboardButton(f"🪙 Купить за {STAR_PRICE_PER_READING} ⭐", callback_data="buy_pack_1")],
                [InlineKeyboardButton("🤝 Получить за приглашение друга", callback_data="get_by_referral")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text("💫 Хочешь полную версию? Выбери способ:", reply_markup=reply_markup)
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

async def confirm_reading_now(update: Update, context: ContextTypes.DEFAULT_TYPE, reading_type):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Искатель"

    new_balance = user['readings_balance'] - 1
    update_user_balance(user_id, new_balance)
    increment_total_used(user_id)
    update_conversion_step(user_id, 'used_reading')

    await update.message.reply_text("Приступаю к ритуалу... Зеркало наполняется туманом... 🔮", reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text("🕯️ Карты выбирают тебя... Это займёт 10-20 секунд.")

    custom_question = context.user_data.get('custom_question')
    forced_card = context.user_data.get('preview_card')

    reading = await generate_full_reading(
        reading_type=reading_type,
        user_question=custom_question,
        user_name=user_name,
        forced_card=forced_card
    )

    context.user_data.pop('preview_card', None)
    save_reading(user_id, reading_type, reading)

    await update.message.reply_text(reading, parse_mode='Markdown', reply_markup=main_menu_keyboard())

    await update.message.reply_text(
        "✨ Понравилось? Поделись с подругой — пусть и она узнает свою судьбу!",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("📤 Поделиться", switch_inline_query="Попробуй бота Таро!")
        ]])
    )
    return MAIN_MENU

# --- 🎁 ПРОФИЛЬ, КАРТА ДНЯ, РЕФЕРАЛЫ ---
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

async def card_of_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    user_data = get_user(user_id)
    user_name = user_data['name'] if user_data['name'] else "Искатель"
    today = date.today().isoformat()

    if user_data['last_card_date'] and user_data['last_card_date'].isoformat() == today and user_data['daily_card']:
        await update.message.reply_text(f"🃏 *Твоя Карта Дня (уже получена сегодня):*\n\n{user_data['daily_card']}", parse_mode='Markdown')
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
        card = random.choice(major_arcana)
        message = f"🃏 {card} — Вселенная молчит... но я знаю: доверься интуиции — сегодня она не подведёт."

    await msg.edit_text(f"🃏 *Твоя Карта Дня, {user_name}:* 🃏\n\n{message}", parse_mode='Markdown')
    update_daily_card(user_id, message)

    if context.job_queue:
        context.job_queue.run_once(
            send_feedback_request,
            when=86400,
            data={"user_id": user_id, "card_text": message},
            name=f"feedback_{user_id}_{today}"
        )

async def invite_friend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    bot_username = "speculora_bot"
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    await update.message.reply_text(
        "✨ *Твоя магическая ссылка готова!* ✨\n\n"
        "Отправь её подруге/другу — когда он/она зарегистрируется, ты получишь +1 бесплатный расклад 🌙\n"
        "А она начнёт с бесплатного пророчества!",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    await update.message.reply_text(ref_link, reply_markup=main_menu_keyboard())

# --- 💰 ПОКУПКИ И ПЛАТЕЖИ ---
async def buy_readings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"🔮 1 расклад — {PACKAGES['pack_1']['price_stars']} ⭐", callback_data="buy_pack_1")],
        [InlineKeyboardButton(f"🔮 5 раскладов — {PACKAGES['pack_5']['price_stars']} ⭐ (скидка!)", callback_data="buy_pack_5")],
        [InlineKeyboardButton(f"🔮 30 раскладов — {PACKAGES['pack_30']['price_stars']} ⭐ (экономия!)", callback_data="buy_pack_30")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "🪙 *Выбери пакет магической силы:* 🪙\n\n"
        "Оплата производится в Telegram Stars — внутри приложения, без перенаправлений.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )
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
    else:
        logger.error(f"❌ Неизвестный payload: {payload} | User: {user_id} | Charge ID: {charge_id}")
        await update.message.reply_text("🌑 Что-то пошло не так... Обратись к создателю Зеркала.", reply_markup=main_menu_keyboard())

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    await query.answer(ok=True)

# --- 🎯 ЭКСКЛЮЗИВЫ И ФИДБЕК ---
async def send_feedback_request(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id = job.data['user_id']
    card_text = job.data['card_text']

    keyboard = [
        [InlineKeyboardButton("✅ Да, сбылось!", callback_data=f"feedback_yes_{user_id}")],
        [InlineKeyboardButton("❌ Нет, не сбылось", callback_data=f"feedback_no_{user_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🌙 Привет! Вчера тебе выпала карта дня:\n\n{card_text}\n\nСбылось ли предсказание? Выбери:",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.warning(f"Не удалось отправить фидбек-напоминание пользователю {user_id}: {e}")

async def handle_feedback_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split('_')[-1])
    if "yes" in query.data:
        exclusive_card = random.choice(EXCLUSIVE_CARDS)
        await query.message.reply_text(
            f"✨ *Ты в клубе избранных!* 🌙\n"
            f"За то, что доверяешь Зеркалу — дарю тебе доступ к **эксклюзивной карте**:\n\n"
            f"🃏 *{exclusive_card['card']}*\n"
            f"🔮 {exclusive_card['meaning']}\n\n"
            f"Эту карту видят только те, кто верит в магию. Носи её символ при себе 😉",
            parse_mode='Markdown'
        )
    else:
        await query.message.reply_text(
            "✨ *Вселенная корректирует курс... Хочешь новый, более точный расклад?*\n"
            f"🔸 За {STAR_PRICE_PER_READING} ⭐ — сразу получишь полную трактовку\n"
            "🔸 Или бесплатно — пригласив друга по своей ссылке\n\n"
            "👇 Выбери способ:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"🪙 Купить за {STAR_PRICE_PER_READING} ⭐", callback_data="buy_pack_1")],
                [InlineKeyboardButton("🤝 Получить за приглашение", callback_data="get_by_referral")]
            ])
        )

async def get_by_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    user = get_user(user_id)

    if user['referral_count'] >= 1:
        new_balance = user['readings_balance'] + 1
        update_user_balance(user_id, new_balance)
        update_conversion_step(user_id, 'got_by_referral')

        await query.edit_message_text(
            "🎉 Ура! Ты пригласил хотя бы одного друга — дарю тебе 1 бесплатный полный расклад! 🌙\n"
            "Используй его сейчас — выбери «🔮 Сделать расклад»!",
            reply_markup=main_menu_keyboard()
        )
    else:
        ref_link = f"https://t.me/speculora_bot?start=ref_{user_id}"
        await query.edit_message_text(
            "✨ Чтобы получить бесплатный расклад — пригласи хотя бы одного друга!\n"
            f"Твоя ссылка: {ref_link}\n\n"
            "Когда друг зарегистрируется — ты сразу получишь +1 расклад!",
            reply_markup=main_menu_keyboard()
        )

# --- 📜 ПРОЧИЕ УТИЛИТЫ ---
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
        await update.message.reply_text("🔮 Ты ещё не делал раскладов. Начни — и история твоих пророчеств начнётся!", reply_markup=main_menu_keyboard())
        return MAIN_MENU

    sorted_readings = sorted(readings, key=lambda x: x['date'], reverse=True)
    history_text = "📜 *Твои последние пророчества:*\n\n"
    keyboard = []

    for i, entry in enumerate(sorted_readings[:5], 1):
        date_str = entry['date'][:16] if isinstance(entry['date'], str) and len(entry['date']) > 16 else entry['date']
        history_text += f"{i}. *{entry['type']}* ({date_str})\n"
        lines = entry['text'].split('\n')
        preview = '\n'.join(lines[:2])
        if len(lines) > 2:
            preview += "..."
        history_text += f"{preview}\n\n"
        callback_data = f"full_reading_{i-1}"
        keyboard.append([InlineKeyboardButton(f"📖 Показать полностью #{i}", callback_data=callback_data)])

    history_text += "🔮 Нажми на кнопку, чтобы перечитать расклад полностью."
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await update.message.reply_text(history_text, parse_mode='Markdown', reply_markup=reply_markup)
    context.user_data['full_readings'] = sorted_readings[:5]
    return MAIN_MENU

async def show_full_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.split('_')[-1])
        readings = context.user_data.get('full_readings', [])
        if index < 0 or index >= len(readings):
            raise ValueError("Неверный индекс")

        reading = readings[index]
        full_text = reading['text']

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
        await query.message.reply_text("🌑 Не удалось показать расклад. Попробуй снова.", reply_markup=main_menu_keyboard())

# --- 🚨 ОБРАБОТЧИКИ ОБНОВЛЕНИЯ И ФОЛБЭКИ ---
async def force_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вызывает /start при нажатии кнопки обновления."""
    # Определяем user_id в зависимости от типа обновления
    if update.message:
        user_id = update.message.from_user.id
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
        # Отвечаем на callback_query, чтобы убрать "часики" на кнопке
        await update.callback_query.answer()
    else:
        return

    # Создаём "искусственное" сообщение /start
    fake_update = Update(
        update_id=update.update_id,
        message=update.message or update.callback_query.message
    )
    fake_update.message.from_user = update.effective_user
    fake_update.message.text = "/start"

    await start(fake_update, context)

async def global_fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return

    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else ""

    if not user_name:
        await update.message.reply_text(
            "🌙 *Кажется, мы не закончили знакомство...*\n"
            "Как мне звать тебя в Книге Судеб?",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardRemove()
        )
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
        context.user_data.clear()
        context.user_data['state'] = MAIN_MENU
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

# --- 📢 Рассылка обновления (только для админов) ---
async def handle_update_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /update_broadcast — только для админов."""
    user_id = update.effective_user.id

    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("🌑 Ты не имеешь доступа к этой команде.", parse_mode='Markdown')
        return

    bot_version = BOT_VERSION  # Берём версию из константы

    users = get_active_users(days=ACTIVE_USERS_DAYS)
    sent_count = 0

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=f"✨ *Speculo обновился до версии {bot_version}!* 🌙\n"
                     "Чтобы активировать все улучшения — нажми кнопку ниже.\n"
                     "Твои данные, баланс и история — в полной сохранности.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🌀 Обновить Зеркало", callback_data="force_update")]
                ])
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить обновление пользователю {user['user_id']}: {e}")

    await update.message.reply_text(
        f"✅ Рассылка обновления `{bot_version}` отправлена {sent_count} пользователям.",
        parse_mode='Markdown'
    )

# --- 🏁 ЗАПУСК БОТА ---
def main():
    init_db()
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            AWAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_question)],
            AWAITING_READING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reading_type_selection)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.TEXT & ~filters.COMMAND, global_fallback_handler)
        ],
    )

    application.add_handler(conv_handler)
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    application.add_handler(MessageHandler(filters.Regex('^🛍️ Купить расклады$'), buy_readings))
    application.add_handler(CallbackQueryHandler(button_buy_pack, pattern="^buy_pack_"))
    application.add_handler(CallbackQueryHandler(get_by_referral, pattern="^get_by_referral$"))
    application.add_handler(CallbackQueryHandler(handle_feedback_button, pattern="^feedback_(yes|no)_"))
    application.add_handler(CallbackQueryHandler(show_full_reading, pattern="^full_reading_"))
    application.add_handler(CallbackQueryHandler(force_update_handler, pattern="^force_update$"))
    application.add_handler(CommandHandler("update_broadcast", handle_update_broadcast))

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()