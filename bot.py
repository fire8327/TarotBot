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
BOT_VERSION = "v1.15"  # <-- МЕНЯЙ ЭТУ ВЕРСИЮ ПРИ КАЖДОМ ДЕПЛОЕ
ACTIVE_USERS_DAYS = 7  # Рассылка обновления пользователям, активным за последние N дней
STAR_PRICE_PER_READING = 50  # Цена одного расклада в ⭐
REFERRAL_BONUS_READINGS = 1  # Сколько раскладов даём за приглашение

# --- Пакеты для покупки ---
PACKAGES = {
    "pack_1": {"name": "1 расклад", "price_stars": STAR_PRICE_PER_READING, "readings": 1},
    "pack_5": {"name": "5 раскладов", "price_stars": STAR_PRICE_PER_READING * 4, "readings": 5},
    "pack_30": {"name": "Подписка на месяц (30 шт.)", "price_stars": STAR_PRICE_PER_READING * 15, "readings": 30},
}

# --- Состояния диалога ---
GET_NAME, MAIN_MENU, CONFIRM_READING, AWAITING_QUESTION, AWAITING_READING_TYPE, AWAITING_USER_ID, AWAITING_FEEDBACK, AWAITING_ADMIN_REPLY = range(8)

# --- 📝 ТЕКСТОВЫЕ СООБЩЕНИЯ ---
TEXTS = {
    # Приветственные сообщения
    'welcome': "🌙 *Добро пожаловать в Зеркало Судеб* 🌙\n\nЯ — хранитель древних знаний, проводник между мирами.\n\nКак мне звать тебя в Книге Судеб? Можешь указать имя или титул. Если предпочитаешь остаться тенью — напиши «Аноним».",
    'welcome_return': "🌑 *Ты вернулся, {name}...*\nЗеркало Судеб вновь открыто для тебя. Выбери путь:",
    'name_registered': "{name}... Какое прекрасное имя, полное энергии и тайны. 🌌{bonus_message}\n\nВ знак нашего знакомства я дарю тебе *дар ясновидения* — один бесплатный расклад, который ты можешь использовать в любой момент.\n\nКогда будешь готов заглянуть в Глубины, просто выбери один из путей в меню ниже.",
    
    # Меню и навигация
    'main_menu': "🌑 Выбери путь из меню:",
    'reading_types': "🕯️ *Выбери путь, по которому ступишь в тумане предсказаний...*\n\nКарты ждут твоего выбора:",
    'custom_question': "🕯️ Опиши свою тревогу или вопрос... Чем яснее ты выразишься — тем глубже будет пророчество.\n\nЯ внимательно выслушаю...",
    'unknown_command': "🌑 Я не понял твой знак... Выбери путь из меню.",
    
    # Профиль
    'profile': """✨🔮 Ваша Личная Статистика Предсказаний 🔮✨
Привет, {name}! 👋
🪄 Доступно раскладов: {balance}
🌌 Всего использовано: {total_used}
👥 {referral_count} / 2 до следующего расклада
🔮 Ты на пути к просветлению!
Чем чаще ты гадаешь — тем яснее становится твоя судьба.
👇 Выбери действие:""",
    
    # Карта дня
    'card_shuffling': "🎴 *Тасую колоду Старших Арканов...*",
    'card_whispering': "🎴 *Колода шепчет... вытягиваю карту дня...*",
    'card_flipping': "🎴 *Переворачиваю карту...*",
    'card_of_day': "🃏 *Твоя Карта Дня, {name}:* 🃏\n\n{message}",
    'card_already_received': "🃏 *Твоя Карта Дня (уже получена сегодня):*\n\n{card_text}",
    
    # Расклады
    'reading_start': "Приступаю к ритуалу... Зеркало наполняется туманом... 🔮",
    'reading_wait': "🕯️ Карты выбирают тебя... Это займёт 10-20 секунд.",
    'reading_share': "✨ Понравилось? Поделись с подругой — пусть и она узнает свою судьбу!",
    
    # Приглашения
    'invite_friend': """✨ *Твоя магическая ссылка готова!* ✨

Отправь её подруге/другу — когда он/она зарегистрируется, ты получишь +1 бесплатный расклад 🌙
А она начнёт с бесплатного пророчества!""",
    
    # Покупки
    'buy_readings': "🪙 *Выбери пакет магической силы:* 🪙\n\nОплата производится в Telegram Stars — внутри приложения, без перенаправлений.",
    'payment_success': """🎉 *Оплата прошла!* 🎉

Ты приобрёл пакет: *{pack_name}*
🪄 На твой баланс зачислено: *{readings_count}* раскладов.

Теперь можешь заглянуть в будущее — выбери «🔮 Сделать расклад»!""",
    
    # О боте
    'about': """🔮 *Зеркало Судеб* 🔮

Я — древний дух, хранящий знания Таро сквозь века. Мои карты не предсказывают неизбежное — они показывают возможности, которые ты можешь воплотить.

Каждый расклад — это диалог между тобой и Вселенной. Я лишь перевожу её шепот на язык символов.

Создано с магией для тех, кто ищет свет в тумане завтрашнего дня. 🌙""",
    
    # Ошибки и уведомления
    'no_readings_balance': "🪙 У тебя закончились расклады. Но магия не спит — ты можешь пополнить баланс!",
    'reading_preview': """🔮 *{reading_type}* — Зеркало показывает тебе первую карту...
🃏 *Карта Судьбы:* **{card_name}**  
{hint}  
✨ *Полная трактовка + ритуал дня + защитная карта — доступна за {price} ⭐ или при приглашении друга 🌙*
Ты держишь нить своей судьбы, {name}. Решай — дернуть за неё или отпустить...""",
}

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
    update_user_last_update_notified, get_active_users, 
    get_all_users, add_readings_to_user, add_readings_to_all_users, reset_free_readings_counter,
    save_user_message, get_unread_messages, get_user_messages, update_message_status
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
        ['📞 Обратная связь', '🤝 Пригласить друга'],
        ['📜 О боте']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def reading_type_keyboard():
    keyboard = [
        ['💖 Расклад на любовь', '⚔️ Расклад на судьбу'],
        ['💰 Расклад на изобилие', '❓ Свой вопрос'],
        ['⬅️ Назад']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def profile_keyboard():
    keyboard = [
        ['📜 Мои последние расклады'],
        ['🛍️ Купить расклады'], 
        ['🤝 Пригласить друга'],
        ['🏠 Главное меню']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def admin_keyboard():
    keyboard = [
        ['🎁 Добавить расклады ВСЕМ'],
        ['👤 Добавить расклады пользователю'],
        ['🔄 Обнулить счётчики бесплатных'],
        ['📢 Сделать рассылку'], ['📨 Просмотреть сообщения'],
        ['🏠 Главное меню']
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# --- 🧩 ОСНОВНЫЕ ОБРАБОТЧИКИ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Всегда сбрасываем состояние и очищаем данные
    context.user_data.clear()
    
    args = context.args
    
    if args and args[0] == 'update':
        await update.message.reply_text("🌀 Начинаем обновление зеркала...")
        await update.message.reply_text(
            "✅ Зеркало успешно обновлено!",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

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
        if referrer_id:
            await process_referral_bonus(update, context, user_id, user_name, referrer_id)
        
        await update.message.reply_text(
            TEXTS['welcome_return'].format(name=user_name),
            parse_mode='Markdown',
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    else:
        if referrer_id:
            context.user_data['referrer_id'] = referrer_id

        await update.message.reply_text(
            TEXTS['welcome'],
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
    update_user_balance(user_id, current_balance + 1)  # Бонус при регистрации остаётся
    
    if referrer_id:
        # Вызываем новую функцию для обработки приглашения
        await process_referral_bonus(update, context, user_id, user_name, referrer_id)
        bonus_message = (
            "\n\nP.S. Ты был приглашён другом — спасибо, что присоединился к кругу Зеркала!"
        )
    
    await update.message.reply_text(
        TEXTS['name_registered'].format(name=user_name, bonus_message=bonus_message),
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    return MAIN_MENU  # Возвращаем MAIN_MENU, а не GET_NAME

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
            TEXTS['reading_types'],
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
    elif user_input == '🏠 Главное меню':
        await update.message.reply_text(
            "🌑 Возвращаюсь в Зал Зеркал...",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    elif user_input == '📞 Обратная связь':
        await update.message.reply_text(
            "📝 *Напиши своё сообщение*\n\n"
            "Здесь ты можешь:\n"
            "• Задать вопрос по работе бота\n"
            "• Сообщить об ошибке\n"
            "• Предложить улучшение\n"
            "• Написать отзыв\n\n"
            "Просто напиши своё сообщение, и я передам его разработчику!",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([['❌ Отменить']], resize_keyboard=True)
        )
        return AWAITING_FEEDBACK
    else:
        await update.message.reply_text(
            TEXTS['unknown_command'],
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
        Объем: 250-400 слов. Только на русском. Используй эмодзи.
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
    preview_text = TEXTS['reading_preview'].format(
        reading_type=reading_type,
        card_name=card_data['card'],
        hint=card_data['hint'],
        price=STAR_PRICE_PER_READING,
        name=user_name
    )
    return card_data, preview_text

def fallback_reading(reading_type, user_name):
    return f"""
🔮 *Расклад на тему: {reading_type}* 🔮
Карты выложены на алтарь, и вот что они говорят о твоей ситуации, {user_name}...
🃏 *Карта 1: Сила* — Ты обладаешь огромным внутренним ресурсом, который пока не полностью раскрыт.
🃏 *Карта 2: Звезда* — Тебя ждёт светлое будущее, если сохранишь веру и продолжишь движение вперед.
🃏 *Карта 3: Император* — Для успеха потребуется дисциплина и структурированный подход.
Помни: карты показывают потенциал, а не стопроцентный результат. Ты держишь перо, которым пишешь свою судьбу.
"""

async def process_referral_bonus(
    update: Update, 
    context: ContextTypes.DEFAULT_TYPE, 
    user_id, 
    user_name, 
    referrer_id
):
    """Обработка бонуса за реферала для существующих пользователей (новая логика: 2 приглашения = 1 расклад)"""
    try:
        referrer = get_user(referrer_id)
        if referrer and referrer.get('name'):
            # Увеличиваем счётчик приглашений
            increment_referral_count(referrer_id)
            # Обновляем данные реферера, чтобы получить новый счётчик
            referrer_updated = get_user(referrer_id)
            new_referral_count = referrer_updated['referral_count']

            # Проверяем, набралось ли 2 приглашения
            if new_referral_count % 2 == 0:
                # Начисляем бонус
                ref_balance = referrer_updated['readings_balance']
                update_user_balance(referrer_id, ref_balance + REFERRAL_BONUS_READINGS)
                # Сохраняем покупку/бонус
                save_purchase(
                    user_id=referrer_id,
                    payload="referral_bonus_2",  # Новый тип бонуса
                    readings=REFERRAL_BONUS_READINGS,
                    price_stars=0,
                    actual_amount=0,
                    charge_id=f"ref2_{user_id}"  # Новый ID для отслеживания
                )
                bonus_message = (
                    f"🎁 *Награда за приглашения!*\n"
                    f"Ты пригласил 2 друзей — и за это получаешь +{REFERRAL_BONUS_READINGS} "
                    f"бесплатный расклад! 🌙"
                )
            else:
                # Бонус не начисляется, просто уведомляем о прогрессе
                bonus_message = (
                    f"👥 *Новый приглашённый!*\n"
                    f"Твой друг {user_name} присоединился! "
                    f"Приглашено: {new_referral_count}/2 до следующего расклада. 🌙"
                )

            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=bonus_message,
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить сообщение рефереру {referrer_id}: {e}")
    except Exception as e:
        logger.error(f"Ошибка при обработке реферера {referrer_id} для пользователя {user_id}: {e}")

# --- 🔄 ОБРАБОТЧИКИ ДИАЛОГОВ ---
async def handle_reading_type_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text

    if user_input == '⬅️ Назад':
        await update.message.reply_text(
            TEXTS['main_menu'],
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

    elif user_input == '❓ Свой вопрос':
        await update.message.reply_text(
            TEXTS['custom_question'],
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

            await update.message.reply_text(
                preview_text, 
                parse_mode='Markdown', 
                reply_markup=main_menu_keyboard()
            )

            keyboard = [
                [InlineKeyboardButton(f"🪙 Купить за {STAR_PRICE_PER_READING} ⭐", callback_data="buy_pack_1")],
                [InlineKeyboardButton("🤝 Бесплатно за приглашение", callback_data="menu_invite_friend")]
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
            TEXTS['no_readings_balance'],
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

    await update.message.reply_text(TEXTS['reading_start'], reply_markup=ReplyKeyboardRemove())
    await update.message.reply_text(TEXTS['reading_wait'])

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
        TEXTS['reading_share'],
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
    
    # --- НОВОЕ: Рассчитываем прогресс ---
    referral_count = user.get('referral_count', 0)
    
    # Ограничиваем отображаемый прогресс значением 2, чтобы не было "3 / 2"
    referral_progress = min(referral_count, 2)

    profile_text = TEXTS['profile'].format(
        name=user_name,
        balance=balance,
        total_used=total_used,
        referral_count=referral_progress

    )
    reply_markup = profile_keyboard()
    await update.message.reply_text(profile_text, parse_mode='Markdown', reply_markup=reply_markup)
    return MAIN_MENU

async def card_of_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id
    user_data = get_user(user_id)
    user_name = user_data['name'] if user_data['name'] else "Искатель"
    today = date.today().isoformat()

    if user_data['last_card_date'] and user_data['last_card_date'].isoformat() == today and user_data['daily_card']:
        await update.message.reply_text(
            TEXTS['card_already_received'].format(card_text=user_data['daily_card']), 
            parse_mode='Markdown'
        )
        return

    msg = await update.message.reply_text(TEXTS['card_shuffling'], parse_mode='Markdown')
    await asyncio.sleep(1.5)
    await msg.edit_text(TEXTS['card_whispering'], parse_mode='Markdown')
    await asyncio.sleep(1.5)
    await msg.edit_text(TEXTS['card_flipping'], parse_mode='Markdown')
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

    await msg.edit_text(
        TEXTS['card_of_day'].format(name=user_name, message=message), 
        parse_mode='Markdown'
    )
    update_daily_card(user_id, message)

    if context.job_queue:
        context.job_queue.run_once(
            send_feedback_request,
            when=86400,
            data={"user_id": user_id, "card_text": message},
            name=f"feedback_{user_id}_{today}"
        )

async def invite_friend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message:
        user_id = update.message.from_user.id
        send_method = update.message.reply_text
    elif update.callback_query:
        user_id = update.callback_query.from_user.id
        send_method = update.callback_query.message.reply_text
        await update.callback_query.answer()
    else:
        return

    bot_username = "speculora_bot"
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    await send_method(
        TEXTS['invite_friend'],
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    await send_method(ref_link, reply_markup=main_menu_keyboard())

async def menu_invite_friend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Просто вызываем существующую функцию invite_friend, передавая ей update и context
    await invite_friend(query, context)

# --- 💰 ПОКУПКИ И ПЛАТЕЖИ ---
async def buy_readings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton(f"🔮 1 расклад — {PACKAGES['pack_1']['price_stars']} ⭐", callback_data="buy_pack_1")],
        [InlineKeyboardButton(f"🔮 5 раскладов — {PACKAGES['pack_5']['price_stars']} ⭐ (скидка!)", callback_data="buy_pack_5")],
        [InlineKeyboardButton(f"🔮 30 раскладов — {PACKAGES['pack_30']['price_stars']} ⭐ (экономия!)", callback_data="buy_pack_30")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        TEXTS['buy_readings'],
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
            TEXTS['payment_success'].format(
                pack_name=pack['name'],
                readings_count=pack['readings']
            ),
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


# --- 📜 ПРОЧИЕ УТИЛИТЫ ---
async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        TEXTS['about'],
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
        # 🔥 ИСПРАВЛЕНО: используем индекс от 0, а не от 1
        callback_data = f"full_reading_{i-1}"
        keyboard.append([InlineKeyboardButton(f"📖 Показать полностью #{i}", callback_data=callback_data)])

    history_text += "🔮 Нажми на кнопку, чтобы перечитать расклад полностью."
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    await update.message.reply_text(history_text, parse_mode='Markdown', reply_markup=reply_markup)
    # 🔥 ИСПРАВЛЕНО: сохраняем все отсортированные расклады
    context.user_data['full_readings'] = sorted_readings
    return MAIN_MENU

async def show_full_reading(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.split('_')[-1])
        readings = context.user_data.get('full_readings', [])
        
        # 🔥 ДОБАВЛЕНО: проверка на существование индекса
        if index < 0 or index >= len(readings):
            await query.message.reply_text("❌ Расклад не найден.", reply_markup=main_menu_keyboard())
            return

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

    # Получаем ВСЕХ пользователей (не только активных)
    from db import get_all_users  # Нужно добавить эту функцию в db.py
    users = get_all_users()
    
    sent_count = 0
    failed_count = 0

    broadcast_text = """✨ *ОБНОВЛЕНИЕ ЗЕРКАЛА СУДЕБ!* 🔮

Дорогой искатель истины! Наше Зеркало прошло очищение и стало ещё яснее.

🔄 *ЧТО НОВОГО:*
• Упрощённая навигация — команда /start всегда ведёт в главное меню
• Интуитивные кнопки "⬅️ Назад" и "🏠 Главное меню" 
• Улучшенный поток получения раскладов

🎯 *КАК ЭТО РАБОТАЕТ:*
1. Нажмите /start в любой момент для сброса в главное меню
2. Используйте "⬅️ Назад" для шага назад
3. "🏠 Главное меню" — мгновенный возврат домой

💫 *ВАЖНО:*
• Все ваши данные, балансы и история сохранены
• Доступ ко всем функциям остаётся прежним
• Скоро появятся новые эксклюзивные расклады

🌙 *Благодарим за ваше доверие и верность Зеркалу Судеб!*

*P.S. Чувствуете перемены? Карты стали говорить ещё яснее...*"""

    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=broadcast_text,
                parse_mode='Markdown'
            )
            sent_count += 1
            # Небольшая задержка чтобы не спамить
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning(f"Не удалось отправить обновление пользователю {user['user_id']}: {e}")
            failed_count += 1

    await update.message.reply_text(
        f"✅ Рассылка обновления отправлена:\n"
        f"• Успешно: {sent_count} пользователей\n"
        f"• Не удалось: {failed_count} пользователей",
        parse_mode='Markdown'
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /admin - только для админов"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("🌑 Ты не имеешь доступа к этой команде.", parse_mode='Markdown')
        return MAIN_MENU
    
    await update.message.reply_text(
        "⚡ *Панель администратора Зеркала Судеб* ⚡\n\n"
        "Выберите действие:",
        parse_mode='Markdown',
        reply_markup=admin_keyboard()
    )
    return MAIN_MENU

async def handle_admin_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка действий в админ-меню"""
    user_id = update.effective_user.id
    user_input = update.message.text
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("🌑 Доступ запрещён.", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    
    if user_input == '🎁 Добавить расклады ВСЕМ':
        add_readings_to_all_users(1)
        users_count = len(get_all_users())
        
        await update.message.reply_text(
            f"✅ *Успешно!*\n\n"
            f"Добавлено по 1 раскладу всем пользователям.\n"
            f"Всего пользователей: {users_count}",
            parse_mode='Markdown',
            reply_markup=admin_keyboard()
        )
        
    elif user_input == '👤 Добавить расклады пользователю':
        await update.message.reply_text(
            "Введите ID пользователя, которому нужно добавить расклады:",
            reply_markup=ReplyKeyboardRemove()
        )
        # 🔥 ВОЗВРАЩАЕМ состояние для ожидания ID пользователя
        return AWAITING_USER_ID
        
    elif user_input == '🔄 Обнулить счётчики бесплатных':
        reset_free_readings_counter()
        await update.message.reply_text(
            "✅ Счётчики бесплатных раскладов обнулены для всех пользователей!",
            reply_markup=admin_keyboard()
        )
        
    elif user_input == '📢 Сделать рассылку':
        await handle_update_broadcast(update, context)
        
    elif user_input == '📨 Просмотреть сообщения':
        await handle_messages_list(update, context)
        
    elif user_input == '🏠 Главное меню':
        await update.message.reply_text(
            "Возвращаюсь в главное меню...",
            reply_markup=main_menu_keyboard()
        )
    
    # 🔥 ВСЕГДА возвращаем MAIN_MENU, кроме случаев когда нужно другое состояние
    return MAIN_MENU

async def handle_user_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Без имени"
    message_text = update.message.text
    
    if message_text == '❌ Отменить':
        await update.message.reply_text(
            "Сообщение отменено",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    await update.message.reply_text(
        "✅ *Сообщение отправлено!*\n\n"
        "Разработчик получит твоё сообщение и ответит в ближайшее время.\n"
        "Ответ придёт тебе прямо сюда, в бота.",
        parse_mode='Markdown',
        reply_markup=main_menu_keyboard()
    )
    
    # Уведомляем админа о новом сообщении
    await notify_admin_about_new_message(context, user_id, user_name, message_text)
    
    return MAIN_MENU

async def notify_admin_about_new_message(context: ContextTypes.DEFAULT_TYPE, user_id: int, user_name: str, message: str):
    """Уведомление админа о новом сообщении"""
    for admin_id in ADMIN_USER_IDS:
        try:
            # Сохраняем ID сообщения для отслеживания
            message_id = save_user_message(user_id, user_name, message, 'feedback')
            
            # Создаем клавиатуру для быстрого ответа
            keyboard = [
                [InlineKeyboardButton("💌 Ответить пользователю", callback_data=f"quick_reply_{user_id}_{message_id}")],
                [InlineKeyboardButton("📋 Все сообщения", callback_data="show_all_messages")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📨 *НОВОЕ СООБЩЕНИЕ ОТ ПОЛЬЗОВАТЕЛЯ*\n\n"
                     f"👤 Пользователь: {user_name}\n"
                     f"🆔 ID: {user_id}\n"
                     f"💬 Сообщение: {message}\n\n"
                     f"*Нажми кнопку ниже для быстрого ответа* ⬇️",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
            logger.info(f"✅ Уведомление отправлено админу {admin_id}")
            
        except Exception as e:
            logger.error(f"❌ Не удалось уведомить админа {admin_id}: {str(e)}")

async def handle_admin_reply_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода ответа от админа"""
    user_id = update.effective_user.id
    
    logger.info(f"🔧 Обработка ответа админа. User: {user_id}, Text: {update.message.text}")
    
    # Проверяем нажатие кнопки отмены
    if update.message.text == '❌ Отменить ответ':
        await update.message.reply_text(
            "❌ Ответ отменён. Возвращаюсь в главное меню.",
            reply_markup=admin_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
    
    # Проверяем, что это админ и он в режиме ответа
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text(
            "🌑 Я не понял твой знак... Выбери путь из меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
        
    if not context.user_data.get('admin_reply_mode'):
        logger.warning(f"⚠️ Админ {user_id} не в режиме ответа, но пытается отправить сообщение")
        await update.message.reply_text(
            "🌑 Я не понял твой знак... Выбери путь из меню.",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    
    # Получаем текст ответа
    reply_text = update.message.text
    target_user_id = context.user_data.get('reply_to_user')
    original_message_text = context.user_data.get('original_message_text', 'Неизвестное сообщение')
    original_message_id = context.user_data.get('original_message_id')
    
    logger.info(f"🔧 Отправка ответа пользователю {target_user_id}")
    
    if not target_user_id:
        await update.message.reply_text(
            "❌ Ошибка: не найден пользователь для ответа",
            reply_markup=admin_keyboard()
        )
        context.user_data.clear()
        return MAIN_MENU
    
    try:
        # Форматируем ответ
        formatted_reply = f"""💌 *Ответ от разработчика*

*Ваш вопрос:*
{original_message_text}

*Ответ разработчика:*
{reply_text}

---
Если у вас остались вопросы, просто напишите снова! ✨"""
        
        # Отправляем ответ пользователю
        await context.bot.send_message(
            chat_id=target_user_id,
            text=formatted_reply,
            parse_mode='Markdown'
        )
        
        # Сохраняем в историю
        target_user = get_user(target_user_id)
        target_user_name = target_user.get('name', 'Неизвестный')
        save_user_message(user_id, "Admin", f"Ответ для {target_user_name}: {reply_text}", "admin_reply")
        
        # Помечаем исходное сообщение как отвеченное
        if original_message_id:
            update_message_status(original_message_id, 'replied', reply_text)
        
        # 🔥 ОБНОВЛЕНИЕ: Показываем обновленный список сообщений
        messages = get_unread_messages()
        
        if not messages:
            await update.message.reply_text(
                "✅ *Ответ успешно отправлен пользователю!*\n\n"
                "📭 *Все сообщения отвечены!* 🎉",
                parse_mode='Markdown',
                reply_markup=admin_keyboard()
            )
        else:
            # Создаем клавиатуру с оставшимися сообщениями
            keyboard = []
            for i, msg in enumerate(messages[:10]):
                user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
                button_text = f"💌 {user_name[:12]}..." if len(user_name) > 12 else f"💌 {user_name}"
                
                keyboard.append([InlineKeyboardButton(
                    button_text, 
                    callback_data=f"quick_reply_{msg['user_id']}_{msg['id']}"
                )])
            
            keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="show_all_messages")])
            keyboard.append([InlineKeyboardButton("📋 Вся история", callback_data="show_full_history")])
            
            await update.message.reply_text(
                f"✅ *Ответ успешно отправлен пользователю!*\n\n"
                f"📨 *Осталось непрочитанных сообщений: {len(messages)}*",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        logger.info(f"✅ Ответ админа {user_id} отправлен пользователю {target_user_id}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки ответа пользователю {target_user_id}: {e}")
        await update.message.reply_text(
            f"❌ Ошибка отправки: {str(e)}",
            reply_markup=admin_keyboard()
        )
    
    # Сбрасываем данные
    context.user_data.clear()
    return MAIN_MENU

# 🔥 ДОБАВИМ вспомогательную функцию для показа обновленного списка
async def handle_show_all_messages_custom(update: Update, context: ContextTypes.DEFAULT_TYPE, messages=None):
    """Показать обновленный список сообщений (используется после ответа)"""
    if messages is None:
        messages = get_unread_messages()
    
    if not messages:
        text = "📭 *Нет новых сообщений*\n\nВсе сообщения отвечены! 🎉"
        if hasattr(update, 'message') and update.message:
            await update.message.reply_text(text, parse_mode='Markdown')
        else:
            await update.edit_message_text(text, parse_mode='Markdown')
        return
    
    # Создаем удобную клавиатуру с кнопками для каждого сообщения
    keyboard = []
    for i, msg in enumerate(messages[:10]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        button_text = f"💌 {user_name[:12]}..." if len(user_name) > 12 else f"💌 {user_name}"
        
        keyboard.append([InlineKeyboardButton(
            button_text, 
            callback_data=f"quick_reply_{msg['user_id']}_{msg['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="show_all_messages")])
    keyboard.append([InlineKeyboardButton("📋 Вся история", callback_data="show_full_history")])
    
    text = f"📨 *Непрочитанные сообщения: {len(messages)}*\n\n"
    text += "*Нажми на кнопку ниже для быстрого ответа:*\n"
    text += "💡 *Сообщения удаляются из списка после ответа*\n\n"
    
    for i, msg in enumerate(messages[:5]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        text += f"👤 *{user_name}* (ID: `{msg['user_id']}`)\n"
        text += f"💬 {msg['message_text'][:80]}...\n"
        text += f"⏰ {msg['created_at'].strftime('%d.%m %H:%M')}\n\n"
    
    if len(messages) > 5:
        text += f"*... и ещё {len(messages) - 5} сообщений*"
    
    if hasattr(update, 'message') and update.message:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_messages_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать непрочитанные сообщения с удобными кнопками (обновленная версия)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ Доступ запрещён")
        return
    
    # 🔥 ВСЕГДА получаем свежие данные
    messages = get_unread_messages()
    
    if not messages:
        await update.message.reply_text(
            "📭 *Нет новых сообщений*\n\n"
            "Все сообщения отвечены! 🎉\n"
            "Используйте /history чтобы посмотреть историю.",
            parse_mode='Markdown'
        )
        return
    
    # Создаем удобную клавиатуру с кнопками для каждого сообщения
    keyboard = []
    for i, msg in enumerate(messages[:10]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        button_text = f"💌 {user_name[:12]}..." if len(user_name) > 12 else f"💌 {user_name}"
        
        keyboard.append([InlineKeyboardButton(
            button_text, 
            callback_data=f"quick_reply_{msg['user_id']}_{msg['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="show_all_messages")])
    keyboard.append([InlineKeyboardButton("📋 Вся история", callback_data="show_full_history")])
    
    text = f"📨 *Непрочитанные сообщения: {len(messages)}*\n\n"
    text += "*Нажми на кнопку ниже для быстрого ответа:*\n"
    text += "💡 *Сообщения автоматически удаляются из списка после ответа*\n\n"
    
    for i, msg in enumerate(messages[:5]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        text += f"👤 *{user_name}* (ID: `{msg['user_id']}`)\n"
        text += f"💬 {msg['message_text'][:80]}...\n"
        text += f"⏰ {msg['created_at'].strftime('%d.%m %H:%M')}\n\n"
    
    if len(messages) > 5:
        text += f"*... и ещё {len(messages) - 5} сообщений*"
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_messages_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать историю всех сообщений (отвеченных и новых)"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ Доступ запрещён")
        return
    
    # 🔥 ИСПРАВЛЕНО: используем функцию из db.py
    try:
        from db import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT um.*, u.name as full_user_name 
                FROM user_messages um
                LEFT JOIN users u ON um.user_id = u.user_id
                ORDER BY um.created_at DESC
                LIMIT 20
            """)
            all_messages = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка при получении истории сообщений: {e}")
        await update.message.reply_text("❌ Ошибка при загрузке истории")
        return
    
    if not all_messages:
        await update.message.reply_text("📭 Нет сообщений в истории")
        return
    
    # Разделяем на отвеченные и новые
    new_messages = [msg for msg in all_messages if msg['status'] == 'new']
    replied_messages = [msg for msg in all_messages if msg['status'] == 'replied']
    
    text = f"📨 *История сообщений*\n\n"
    text += f"🆕 *Новые:* {len(new_messages)}\n"
    text += f"✅ *Отвеченные:* {len(replied_messages)}\n\n"
    
    # Показываем последние 5 сообщений
    for i, msg in enumerate(all_messages[:5]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        status_emoji = "🆕" if msg['status'] == 'new' else "✅"
        
        # Форматируем дату
        created_at = msg['created_at']
        if hasattr(created_at, 'strftime'):
            created_at_str = created_at.strftime('%d.%m %H:%M')
        else:
            created_at_str = str(created_at)
        
        text += f"{status_emoji} *{user_name}* (ID: `{msg['user_id']}`)\n"
        text += f"💬 {msg['message_text'][:80]}...\n"
        text += f"⏰ {created_at_str}\n"
        
        if msg['status'] == 'replied' and msg['admin_reply']:
            text += f"📨 Ответ: {msg['admin_reply'][:50]}...\n"
        
        text += "\n"
    
    if len(all_messages) > 5:
        text += f"*... и ещё {len(all_messages) - 5} сообщений*"
    
    keyboard = [
        [InlineKeyboardButton("📋 Вся история", callback_data="show_full_history")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_user_id_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода ID пользователя"""
    user_id = update.effective_user.id
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("🌑 Доступ запрещён.", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    
    try:
        target_user_id = int(update.message.text)
        from db import add_readings_to_user, get_user
        
        user = get_user(target_user_id)
        if not user:
            await update.message.reply_text(
                "❌ Пользователь с таким ID не найден.",
                reply_markup=admin_keyboard()
            )
            return MAIN_MENU
        
        # Добавляем 1 расклад
        add_readings_to_user(target_user_id, 1)
        
        user_name = user.get('name', 'Неизвестный')
        new_balance = user['readings_balance'] + 1
        
        await update.message.reply_text(
            f"✅ *Успешно!*\n\n"
            f"Пользователь: {user_name} (ID: {target_user_id})\n"
            f"Добавлено: 1 расклад\n"
            f"Новый баланс: {new_balance}",
            parse_mode='Markdown',
            reply_markup=admin_keyboard()
        )
        
        # Отправляем уведомление пользователю
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="🎁 *Ты получил подарок от Зеркала Судеб!*\n\n"
                     "В знак благодарности за твою верность мы дарим тебе +1 бесплатный расклад! 🔮\n\n"
                     "Используй его для нового пророчества!",
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.warning(f"Не удалось отправить уведомление пользователю {target_user_id}: {e}")
        
    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат ID. Введите числовой ID пользователя.",
            reply_markup=admin_keyboard()
        )
    
    return MAIN_MENU

async def send_bonus_notification_to_all(context: ContextTypes.DEFAULT_TYPE):
    """Рассылка уведомления о бонусе всем пользователям"""
    from db import get_all_users
    
    users = get_all_users()
    sent_count = 0
    
    broadcast_text = """🎁 *ПОДАРОК ОТ ЗЕРКАЛА СУДЕБ!* 🔮

Дорогой искатель истины!

В знак благодарности за твою верность и в честь обновления бота, 
мы дарим тебе *+1 бесплатный расклад*! 

✨ Используй его для нового пророчества и загляни в будущее!

*Твой баланс уже пополнен!*

🌙 Благодарим за доверие к Зеркалу Судеб!"""
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user['user_id'],
                text=broadcast_text,
                parse_mode='Markdown'
            )
            sent_count += 1
            await asyncio.sleep(0.1)  # Задержка чтобы не спамить
        except Exception as e:
            logger.warning(f"Не удалось отправить бонусное уведомление пользователю {user['user_id']}: {e}")
    
    logger.info(f"Бонусные уведомления отправлены: {sent_count}/{len(users)}")

async def handle_quick_reply_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки быстрого ответа"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await query.message.reply_text("❌ Доступ запрещён")
        return
    
    # Извлекаем ID пользователя и сообщения
    parts = query.data.replace('quick_reply_', '').split('_')
    target_user_id = int(parts[0])
    original_message_id = int(parts[1]) if len(parts) > 1 else None
    
    # Устанавливаем режим ответа
    context.user_data.clear()
    context.user_data['admin_reply_mode'] = True
    context.user_data['reply_to_user'] = target_user_id
    context.user_data['original_message_id'] = original_message_id
    
    # Получаем информацию о пользователе
    target_user = get_user(target_user_id)
    target_user_name = target_user.get('name', 'Неизвестный')
    
    # Получаем оригинальное сообщение
    original_message_text = "Не удалось загрузить оригинальное сообщение"
    if original_message_id:
        user_messages = get_user_messages(target_user_id)
        for msg in user_messages:
            if msg['id'] == original_message_id:
                original_message_text = msg['message_text']
                break
    
    context.user_data['original_message_text'] = original_message_text
    
    # Создаем клавиатуру с кнопкой отмены
    cancel_keyboard = ReplyKeyboardMarkup([['❌ Отменить ответ']], resize_keyboard=True)
    
    # 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Используем context.bot.send_message вместо query.message.reply_text
    await context.bot.send_message(
        chat_id=user_id,
        text=f"💌 *РЕЖИМ ОТВЕТА АДМИНА*\n\n"
             f"👤 *Пользователь:* {target_user_name}\n"
             f"🆔 *ID:* {target_user_id}\n\n"
             f"*Оригинальное сообщение:*\n{original_message_text}\n\n"
             f"👇 *Введите ваш ответ ниже:*\n\n"
             f"ℹ️ Для отмены нажмите кнопку '❌ Отменить ответ'",
        parse_mode='Markdown',
        reply_markup=cancel_keyboard
    )
    
    # 🔥 ВОЗВРАЩАЕМ состояние для ожидания ответа админа
    return AWAITING_ADMIN_REPLY

async def handle_admin_reply_direct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прямой обработчик ответов админа"""
    user_id = update.effective_user.id
    
    # Проверяем, что админ в режиме ответа
    if context.user_data.get('admin_reply_mode'):
        return await handle_admin_reply_input(update, context)
    else:
        # Если не в режиме ответа, передаем обработку ConversationHandler
        return

async def handle_show_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать все сообщения с пагинацией (обновленная версия)"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return
    
    # 🔥 ВСЕГДА получаем свежие данные
    messages = get_unread_messages()
    
    if not messages:
        try:
            await query.edit_message_text(
                "📭 *Нет новых сообщений*\n\n"
                "Все сообщения отвечены! 🎉\n\n"
                "💡 Используйте кнопки ниже для навигации:",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📋 Вся история", callback_data="show_full_history")],
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data="show_all_messages")]
                ])
            )
        except Exception:
            # Если не удалось отредактировать, отправляем новое сообщение
            await query.message.reply_text(
                "📭 *Нет новых сообщений*\n\nВсе сообщения отвечены! 🎉",
                parse_mode='Markdown'
            )
        return
    
    # Показываем первые 5 сообщений с кнопками для ответа
    text = f"📨 *Новые сообщения: {len(messages)}*\n\n"
    text += "💡 *Сообщения автоматически удаляются из этого списка после ответа*\n\n"
    
    for i, msg in enumerate(messages[:5]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        text += f"*{i+1}. {user_name}* (ID: `{msg['user_id']}`)\n"
        text += f"💬 {msg['message_text'][:150]}...\n"
        text += f"⏰ {msg['created_at'].strftime('%d.%m %H:%M')}\n\n"
    
    # Создаем клавиатуру с кнопками для быстрого ответа
    keyboard = []
    for i, msg in enumerate(messages[:5]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        keyboard.append([InlineKeyboardButton(
            f"💌 Ответить {user_name[:15]}...", 
            callback_data=f"quick_reply_{msg['user_id']}_{msg['id']}"
        )])
    
    keyboard.append([InlineKeyboardButton("🔄 Обновить список", callback_data="show_all_messages")])
    keyboard.append([InlineKeyboardButton("📋 Вся история", callback_data="show_full_history")])
    
    try:
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения: {e}")
        # Если не удалось отредактировать, отправляем новое сообщение
        await query.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_show_full_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать полную историю всех сообщений с пагинацией (обновленная версия)"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        return
    
    # 🔥 ВСЕГДА получаем свежие данные
    try:
        from db import get_db_connection
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT um.*, u.name as full_user_name 
                FROM user_messages um
                LEFT JOIN users u ON um.user_id = u.user_id
                ORDER BY um.created_at DESC
                LIMIT 50
            """)
            all_messages = cur.fetchall()
        conn.close()
    except Exception as e:
        logger.error(f"Ошибка при получении сообщений: {e}")
        await query.message.reply_text("❌ Ошибка при загрузке истории сообщений")
        return
    
    if not all_messages:
        try:
            await query.edit_message_text(
                "📭 *Нет сообщений в истории*\n\n"
                "Здесь будут отображаться все сообщения от пользователей.",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data="show_full_history")]
                ])
            )
        except Exception:
            await query.message.reply_text("📭 Нет сообщений в истории")
        return
    
    # Разделяем на отвеченные и новые
    new_messages = [msg for msg in all_messages if msg['status'] == 'new']
    replied_messages = [msg for msg in all_messages if msg['status'] == 'replied']
    
    # Создаем текст сообщения
    text = f"📨 *Полная история сообщений*\n\n"
    text += f"📊 *Статистика:*\n"
    text += f"• 🆕 Новые: {len(new_messages)}\n"
    text += f"• ✅ Отвеченные: {len(replied_messages)}\n"
    text += f"• 📋 Всего: {len(all_messages)}\n\n"
    
    # Показываем последние 10 сообщений с деталями
    for i, msg in enumerate(all_messages[:10]):
        user_name = msg['full_user_name'] or msg['user_name'] or "Без имени"
        status_emoji = "🆕" if msg['status'] == 'new' else "✅"
        
        # Форматируем дату
        created_at = msg['created_at']
        if hasattr(created_at, 'strftime'):
            created_at_str = created_at.strftime('%d.%m.%Y %H:%M')
        else:
            created_at_str = str(created_at)
        
        text += f"{status_emoji} *{i+1}. {user_name}* (ID: `{msg['user_id']}`)\n"
        text += f"📅 *Когда:* {created_at_str}\n"
        
        # Обрезаем длинный текст сообщения
        message_preview = msg['message_text']
        if len(message_preview) > 100:
            message_preview = message_preview[:100] + "..."
        text += f"💬 *Сообщение:* {message_preview}\n"
        
        if msg['status'] == 'replied' and msg['admin_reply']:
            reply_preview = msg['admin_reply']
            if len(reply_preview) > 50:
                reply_preview = reply_preview[:50] + "..."
            text += f"📨 *Ответ:* {reply_preview}\n"
        
        text += "\n"
    
    if len(all_messages) > 10:
        text += f"*... и ещё {len(all_messages) - 10} сообщений*\n\n"
    
    text += "💡 *Используйте кнопки ниже для навигации:*"
    
    # Создаем клавиатуру для навигации
    keyboard = []
    
    # Кнопки для быстрого ответа на новые сообщения
    if new_messages:
        keyboard.append([InlineKeyboardButton("🚀 Быстрые ответы на новые", callback_data="show_all_messages")])
    
    # Основные кнопки навигации
    keyboard.append([
        InlineKeyboardButton("🔄 Обновить", callback_data="show_full_history"),
        InlineKeyboardButton("📋 Непрочитанные", callback_data="show_all_messages")
    ])
    
    try:
        await query.edit_message_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения истории: {e}")
        # Если не удалось отредактировать, отправляем новое сообщение
        await query.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_admin_back_to_menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды возврата в главное меню для админов"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("❌ Доступ запрещён")
        return
    
    await update.message.reply_text(
        "🌑 Возвращаюсь в главное меню...",
        reply_markup=main_menu_keyboard()
    )

async def handle_get_by_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопки получения расклада за приглашение"""
    query = update.callback_query
    await query.answer()
    
    # Просто вызываем функцию приглашения друга
    await invite_friend(update, context)

async def main_menu_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Фолбэк для возврата в главное меню"""
    user_id = update.message.from_user.id
    user_input = update.message.text
    
    # 🔥 ВАЖНО: Если админ в режиме ответа, пропускаем обычную обработку
    if user_id in ADMIN_USER_IDS and context.user_data.get('admin_reply_mode'):
        # Позволяем ConversationHandler обработать это сообщение
        return await handle_admin_reply_input(update, context)
    
    user = get_user(user_id)
    user_name = user['name'] if user['name'] else "Искатель"
    
    # 🔥 ПЕРВЫМ ДЕЛОМ проверяем админские кнопки
    if user_id in ADMIN_USER_IDS:
        if user_input in ['🎁 Добавить расклады ВСЕМ', '👤 Добавить расклады пользователю', 
                         '🔄 Обнулить счётчики бесплатных', '📢 Сделать рассылку', 
                         '📨 Просмотреть сообщения', '🏠 Главное меню']:
            return await admin_main_menu(update, context)
    
    # Если не админ или не админская кнопка, обрабатываем как обычного пользователя
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
            TEXTS['reading_types'],
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
    elif user_input == '🏠 Главное меню':
        await update.message.reply_text(
            "🌑 Возвращаюсь в Зал Зеркал...",
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU
    elif user_input == '📞 Обратная связь':
        await update.message.reply_text(
            "📝 *Напиши своё сообщение*\n\n"
            "Здесь ты можешь:\n"
            "• Задать вопрос по работе бота\n"
            "• Сообщить об ошибке\n"
            "• Предложить улучшение\n"
            "• Написать отзыв\n\n"
            "Просто напиши своё сообщение, и я передам его разработчику!",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([['❌ Отменить']], resize_keyboard=True)
        )
        return AWAITING_FEEDBACK
    else:
        await update.message.reply_text(
            TEXTS['unknown_command'],
            reply_markup=main_menu_keyboard()
        )
        return MAIN_MENU

async def admin_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню для админов"""
    user_id = update.effective_user.id
    user_input = update.message.text
    
    logger.info(f"🔧 Админское меню: {user_input} от пользователя {user_id}")
    
    if user_id not in ADMIN_USER_IDS:
        await update.message.reply_text("🌑 Доступ запрещён.", reply_markup=main_menu_keyboard())
        return MAIN_MENU
    
    # Обработка админских кнопок
    if user_input == '🎁 Добавить расклады ВСЕМ':
        add_readings_to_all_users(1)
        users_count = len(get_all_users())
        await update.message.reply_text(
            f"✅ *Успешно!*\n\nДобавлено по 1 раскладу всем пользователям.\nВсего пользователей: {users_count}",
            parse_mode='Markdown',
            reply_markup=admin_keyboard()
        )
        return MAIN_MENU  # 🔥 ВАЖНО: возвращаем состояние
        
    elif user_input == '👤 Добавить расклады пользователю':
        await update.message.reply_text("Введите ID пользователя:", reply_markup=ReplyKeyboardRemove())
        return AWAITING_USER_ID  # 🔥 ВАЖНО: возвращаем состояние
        
    elif user_input == '🔄 Обнулить счётчики бесплатных':
        reset_free_readings_counter()
        await update.message.reply_text("✅ Счётчики обнулены!", reply_markup=admin_keyboard())
        return MAIN_MENU  # 🔥 ВАЖНО: возвращаем состояние
        
    elif user_input == '📢 Сделать рассылку':
        await handle_update_broadcast(update, context)
        return MAIN_MENU  # 🔥 ВАЖНО: возвращаем состояние
        
    elif user_input == '📨 Просмотреть сообщения':
        await handle_messages_list(update, context)
        return MAIN_MENU  # 🔥 ВАЖНО: возвращаем состояние
        
    elif user_input == '🏠 Главное меню':
        await update.message.reply_text("Возвращаюсь в главное меню...", reply_markup=main_menu_keyboard())
        return MAIN_MENU  # 🔥 ВАЖНО: возвращаем состояние
    
    # Если кнопка не распознана
    await update.message.reply_text(
        "🌑 Неизвестная команда.",
        reply_markup=admin_keyboard()
    )
    return MAIN_MENU


# --- 🏁 ЗАПУСК БОТА ---
def main():
    init_db()
    application = Application.builder().token(TOKEN).build()

    # 1. Сначала ConversationHandler - ОСНОВНОЙ обработчик
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_fallback)],
            AWAITING_QUESTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_question)],
            AWAITING_READING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reading_type_selection)],
            AWAITING_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_id_input)],
            AWAITING_FEEDBACK: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_feedback)],
            AWAITING_ADMIN_REPLY: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_reply_input)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            MessageHandler(filters.TEXT & ~filters.COMMAND, global_fallback_handler)
        ],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    
    # 2. Затем обработчики платежей
    application.add_handler(PreCheckoutQueryHandler(pre_checkout_handler))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    
    # 3. Обработчики кнопок покупки
    application.add_handler(MessageHandler(filters.Regex('^🛍️ Купить расклады$'), buy_readings))
    application.add_handler(CallbackQueryHandler(button_buy_pack, pattern="^buy_pack_"))
    
    # 4. Обработчики фидбека
    application.add_handler(CallbackQueryHandler(handle_feedback_button, pattern="^feedback_(yes|no)_"))
    
    # 5. Обработчики истории раскладов
    application.add_handler(CallbackQueryHandler(show_full_reading, pattern="^full_reading_"))
    
    # 6. Обработчики рефералов
    application.add_handler(CallbackQueryHandler(menu_invite_friend, pattern="^menu_invite_friend$"))
    application.add_handler(CallbackQueryHandler(handle_get_by_referral, pattern="^get_by_referral$"))
    
    # 7. 🔥 АДМИНСКИЕ ОБРАБОТЧИКИ - ПОСЛЕДНИМИ
    application.add_handler(CommandHandler('admin', admin_command))
    application.add_handler(CommandHandler("messages", handle_messages_list))
    application.add_handler(CommandHandler("history", handle_messages_history))
    application.add_handler(CommandHandler("update_broadcast", handle_update_broadcast))
    
    # 8. Обработчики админских callback-кнопок (сообщения)
    application.add_handler(CallbackQueryHandler(handle_quick_reply_button, pattern="^quick_reply_"))
    application.add_handler(CallbackQueryHandler(handle_show_all_messages, pattern="^show_all_messages$"))
    application.add_handler(CallbackQueryHandler(handle_show_full_history, pattern="^show_full_history$"))
    application.add_handler(CallbackQueryHandler(handle_admin_back_to_menu_cmd, pattern="^admin_back_to_menu$"))

    # Запускаем бота
    logger.info("Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == '__main__':
    main()