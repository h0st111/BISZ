import sqlite3
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    filters, CallbackQueryHandler, ConversationHandler
)

# Состояния для диалога
SELECT_ROLE, CUSTOMER_MENU, FREELANCER_MENU, CREATE_ORDER = range(4)

# Настройки
BOT_COMMISSION = 0.15
ADMIN_ID = 123456789
DB_NAME = 'my_database.db'

# Категории услуг
SERVICE_CATEGORIES = {
    'design': 'Дизайн',
    'writing': 'Тексты',
    'dev': 'Программирование',
    'video': 'Видео',
    'marketing': 'Маркетинг',
    'other': 'Другое'
}

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# Инициализация базы данных
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()

        # Пользователи
        c.execute('''CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE,
                    username TEXT,
                    role TEXT CHECK(role IN ('customer', 'freelancer', 'admin')),
                    balance INTEGER DEFAULT 0,
                    rating REAL DEFAULT 0.0,
                    review_count INTEGER DEFAULT 0,
                    is_subscribed BOOLEAN DEFAULT FALSE)''')

        # Заказы
        c.execute('''CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY,
                    customer_id INTEGER,
                    title TEXT,
                    description TEXT,
                    budget INTEGER,
                    category TEXT,
                    deadline DATE,
                    status TEXT DEFAULT 'active',
                    freelancer_id INTEGER DEFAULT NULL,
                    FOREIGN KEY (customer_id) REFERENCES users(id),
                    FOREIGN KEY (freelancer_id) REFERENCES users(id))''')

        # Отзывы
        c.execute('''CREATE TABLE IF NOT EXISTS reviews (
                    id INTEGER PRIMARY KEY,
                    order_id INTEGER,
                    rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                    text TEXT,
                    FOREIGN KEY (order_id) REFERENCES orders(id))''')

        conn.commit()


# Кастомизированная клавиатура
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("➕ Создать заказ")],
        [KeyboardButton("💼 Мои заказы"), KeyboardButton("👤 Профиль")],
        [KeyboardButton("📚 Категории"), KeyboardButton("📊 Рейтинг")],
        [KeyboardButton("⚙️ Настройки")]
    ], resize_keyboard=True)


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM users WHERE telegram_id=?", (user_id,))
        if not c.fetchone():
            c.execute("INSERT INTO users (telegram_id, username) VALUES (?, ?)", (user_id, username))
            conn.commit()

    # Кнопка начать
    keyboard = [[InlineKeyboardButton("🚀 Начать", callback_data='start_button')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Добро пожаловать в биржу фриланса!\n\n"
        "Нажмите кнопку ниже, чтобы начать работу:",
        reply_markup=reply_markup
    )
    return SELECT_ROLE


# Обработчик кнопки начать
async def start_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Кнопки выбора роли
    keyboard = [
        [InlineKeyboardButton("🧑‍💻 Заказчик", callback_data='role_customer')],
        [InlineKeyboardButton("🧑‍🎨 Фрилансер", callback_data='role_freelancer')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "Выберите вашу роль:",
        reply_markup=reply_markup
    )
    return CUSTOMER_MENU


# Обработчик выбора роли
async def role_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    role = query.data.split('_')[1]  # 'customer' или 'freelancer'
    user_id = update.effective_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET role = ? WHERE telegram_id = ?", (role, user_id))
        conn.commit()

    if role == 'customer':
        await query.edit_message_text(
            f"Вы зарегистрированы как Заказчик! 🧑‍💻\n\n"
            "Вот что вы можете сделать:\n"
            "1. Создавать заказы\n"
            "2. Получать отклики от фрилансеров\n"
            "3. Управлять заказами\n"
            "4. Оставлять отзывы\n\n"
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Создать заказ", callback_data='create_order'),
                InlineKeyboardButton("💼 Мои заказы", callback_data='my_orders')
            ]])
        )
        return CUSTOMER_MENU
    else:
        await query.edit_message_text(
            f"Вы зарегистрированы как Фрилансер! 🧑‍🎨\n\n"
            "Вот что вы можете сделать:\n"
            "1. Получать уведомления о новых заказах\n"
            "2. Брать заказы\n"
            "3. Управлять своими заказами\n"
            "4. Получать отзывы и повышать рейтинг\n\n"
            "Подпишитесь на уведомления о заказах:",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🔔 Подписаться", callback_data='subscribe_freelancer')
            ]])
        )
        return FREELANCER_MENU


# Обработчик создания заказа
async def create_order_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text("Введите название заказа:")
    return CREATE_ORDER


# Пошаговый диалог для заказа
async def create_order_step(update: Update, context: ContextTypes.DEFAULT_TYPE, step=None):
    steps = {
        1: {"field": "title", "text": "Введите название заказа:"},
        2: {"field": "description", "text": "Опишите, что вам нужно:"},
        3: {"field": "budget", "text": "Какой бюджет? (в рублях):"},
        4: {"field": "category", "text": "Выберите категорию:"},
        5: {"field": "deadline", "text": "Введите срок выполнения (например: 7 дней):"}
    }

    if step is None:
        step = 1

    current = steps[step]

    if step == 4:  # Категории
        keyboard = []
        for i, (key, value) in enumerate(SERVICE_CATEGORIES.items()):
            if i % 2 == 0:
                keyboard.append([])
            keyboard[-1].append(InlineKeyboardButton(value, callback_data=f'cat_{key}'))

        await update.message.reply_text(current["text"], reply_markup=InlineKeyboardMarkup(keyboard))
        return step

    await update.message.reply_text(current["text"])
    return step


# Обработчик завершения заказа
async def create_order_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Сохраняем данные в контексте
    context.user_data['budget'] = int(update.message.text)

    # Сохраняем заказ в базу данных
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE telegram_id = ?", (user_id,))
        customer_id = c.fetchone()[0]

        c.execute("""INSERT INTO orders 
                  (customer_id, title, description, budget, category) 
                  VALUES (?, ?, ?, ?, ?)""",
                  (customer_id,
                   context.user_data['title'],
                   context.user_data['description'],
                   context.user_data['budget'],
                   context.user_data['category']))
        order_id = c.lastrowid
        conn.commit()

    # Уведомляем фрилансеров
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT telegram_id FROM users WHERE role = 'freelancer' AND is_subscribed = TRUE")

        keyboard = [[InlineKeyboardButton(f"Взять заказ #{order_id}", callback_data=f'take_order_{order_id}')]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        for freelancer in c.fetchall():
            try:
                await context.bot.send_message(
                    chat_id=freelancer[0],
                    text=f"Новый заказ: {context.user_data['title']}\n"
                         f"Бюджет: {context.user_data['budget']} руб.\n"
                         f"Категория: {SERVICE_CATEGORIES[context.user_data['category']]}\n"
                         f"Описание: {context.user_data['description'][:100]}...",
                    reply_markup=reply_markup
                )
            except Exception as e:
                logger.error(f"Не удалось отправить сообщение фрилансеру {freelancer[0]}: {e}")

    await update.message.reply_text(
        f"Заказ создан! Номер: #{order_id}\n"
        f"Бюджет: {context.user_data['budget']} руб.\n"
        f"Категория: {SERVICE_CATEGORIES[context.user_data['category']]}\n"
        f"Описание: {context.user_data['description'][:50]}..."
    )
    return CUSTOMER_MENU


# Обработчик выбора категории
async def category_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.split('_')[1]
    context.user_data['category'] = category

    # Переходим к следующему шагу
    return await create_order_step(update, context, step=5)


# Обработчик подписки фрилансера
async def subscribe_freelancer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("UPDATE users SET is_subscribed = TRUE WHERE telegram_id = ?", (user_id,))
        conn.commit()

    await update.callback_query.answer("Вы успешно подписались на уведомления о заказах!")
    await update.callback_query.edit_message_text("Вы подписаны на уведомления о заказах!")
    return FREELANCER_MENU


# Обработчик взятия заказа
async def take_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split('_')[2])
    user_id = update.effective_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT status, budget FROM orders WHERE id = ?", (order_id,))
        result = c.fetchone()

        if result[0] != 'active':
            await query.edit_message_text("Этот заказ уже занят.")
            return

        # Получаем ID пользователя в БД
        c.execute("SELECT id FROM users WHERE telegram_id = ?", (user_id,))
        freelancer_db_id = c.fetchone()[0]

        # Обновляем заказ
        commission = int(result[1] * BOT_COMMISSION)
        final_amount = result[1] - commission

        c.execute("UPDATE orders SET freelancer_id = ?, status = 'taken' WHERE id = ?",
                  (freelancer_db_id, order_id))
        c.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
                  (final_amount, user_id))
        conn.commit()

        await query.edit_message_text(
            f"Вы взяли заказ! Получите {final_amount} руб. после выполнения "
            f"(комиссия бота: {commission} руб.)"
        )

        # Уведомляем заказчика
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"Заказ #{order_id} взят фрилансером. Вы получите {final_amount} руб."
            )
        except Exception as e:
            print(f"Ошибка уведомления заказчика: {e}")


# Профиль пользователя
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("""SELECT role, balance, rating, review_count 
                   FROM users WHERE telegram_id = ?""", (user_id,))
        role, balance, rating, review_count = c.fetchone()

    await update.message.reply_text(
        f"👤 Ваш профиль\n\n"
        f"Роль: {'Заказчик' if role == 'customer' else 'Фрилансер'}\n"
        f"Баланс: {balance} руб.\n"
        f"Рейтинг: {rating:.1f} ★ ({review_count} отзывов)\n\n"
        f"Используйте меню ниже для управления профилем."
    )


# Категории услуг
async def show_categories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories_list = "\n".join([f"• {v}" for k, v in SERVICE_CATEGORIES.items()])

    await update.message.reply_text(
        "📚 Доступные категории услуг:\n" + categories_list
    )


# Админ-панель
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        user_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM orders")
        order_count = c.fetchone()[0]

    await update.message.reply_text(
        f"⚙️ Админ-панель:\n"
        f"Пользователи: {user_count}\n"
        f"Заказы: {order_count}"
    )


# Запуск бота
if __name__ == '__main__':
    init_db()  # Инициализация базы данных

    application = ApplicationBuilder().token('7374000299:AAHjnt66vgW1SgJl_WXrvr3DfKNdxv7yxF8').build()

    # Диалог создания заказа
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(create_order_start, pattern='^create_order$')],
        states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: create_order_step(u, c, 2))],
            2: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: create_order_step(u, c, 3))],
            3: [MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u, c: create_order_step(u, c, 4))],
            4: [CallbackQueryHandler(category_selected)],
            5: [MessageHandler(filters.TEXT & ~filters.COMMAND, create_order_finish)]
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: u.message.reply_text("Создание заказа отменено"))]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CommandHandler("profile", show_profile))
    application.add_handler(CommandHandler("categories", show_categories))
    application.add_handler(conv_handler)

    application.add_handler(CallbackQueryHandler(start_button_handler, pattern='^start_button$'))
    application.add_handler(CallbackQueryHandler(role_selected, pattern='^role_'))
    application.add_handler(CallbackQueryHandler(subscribe_freelancer, pattern='^subscribe_freelancer$'))
    application.add_handler(CallbackQueryHandler(take_order, pattern='^take_order_'))

    application.run_polling()