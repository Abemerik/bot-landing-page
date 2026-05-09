import telebot
from telebot import types
import sqlite3
from decouple import config
import requests
import os
import time
import queue
import threading
from datetime import datetime
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime
import traceback
import uuid

#-------------------------------Конфиг----------------------------------------------------

token = config('TOKEN')
admin_id = config('ADMIN_ID', default=0, cast=int)
bot = telebot.TeleBot(token)
channel = config('CHANNEL')
channel_id = config('CHANNEL_ID')

#--------------------------------Логи-----------------------------------------------------

# 1. Создаём папку logs
os.makedirs('logs', exist_ok=True)

# 2. Уникальный ID запуска
RUN_ID = str(uuid.uuid4())[:8]

# 3. Получаем имя файла по текущему месяцу
current_month = datetime.now().strftime('%Y-%m')
log_filename = f'logs/{current_month}.log'

# 4. Обработчик для файла с ротацией по месяцам
file_handler = TimedRotatingFileHandler(
    filename=log_filename,
    when='midnight',
    interval=1,
    backupCount=12,
    encoding='utf-8'
)
file_handler.suffix = "%Y-%m"
file_handler.extMatch = r"^\d{4}-\d{2}$"


# 5. Формат для файла (с RUN_ID)
file_formatter = logging.Formatter(
    '%(asctime)s | %(run_id)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(file_formatter)
file_handler.setLevel(logging.DEBUG)

# 6. Фильтр для добавления RUN_ID в записи
class RunIDFilter(logging.Filter):
    def filter(self, record):
        record.run_id = RUN_ID
        return True

file_handler.addFilter(RunIDFilter())

# 7. Обработчик для консоли (только ERROR/CRITICAL)
console_handler = logging.StreamHandler()
console_formatter = logging.Formatter('🛑 %(levelname)s: %(message)s')
console_handler.setFormatter(console_formatter)
console_handler.setLevel(logging.ERROR)
console_handler.addFilter(RunIDFilter())  

# 8. Настройка логгера
logger = logging.getLogger('bot_logger')
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 9. Баннер старта с разделителем и ID
def log_startup_banner():
    logger.info("\n!" + "=" * 60)
    logger.info(f"ЗАПУСК БОТА | ID: {RUN_ID} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    

# 10. Пример использования
if __name__ == '__main__':
    log_startup_banner()
    
    logger.debug("Отладочная информация — пишется только в файл")
    logger.info("Информационное сообщение — пишется в файл")
    logger.warning("Предупреждение — в файл и в консоль")
    logger.error("Ошибка — в файл и в консоль!")
    logger.critical("Критическая ошибка — в файл и в консоль!!!")



#-----------------------------Подключение БД----------------------------------------------

# Подключение к БД
try:
    db = sqlite3.connect('Bot.db', check_same_thread=False)
    c = db.cursor()
    logger.info("Подключение к БД Bot.db успешно установлено")
except sqlite3.Error as e:
    logger.error(f"Ошибка подключения к БД: {e}")
    raise

# Создание таблицы с пользователями
try:
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT
    )''')
    db.commit()
    logger.info("Таблица 'users' создана или уже существует")
except sqlite3.Error as e:
    logger.error(f"Ошибка при создании таблицы 'users': {e}")


# Создание таблицы с текстами для faq, contacts, info, start, описание бота
try:
    c.execute('''CREATE TABLE IF NOT EXISTS text (
        start TEXT DEFAULT 'Hello',
        faq TEXT DEFAULT 'Введите текст',
        contacts TEXT DEFAULT 'Введите текст',
        info TEXT DEFAULT 'Введите текст'
    )''')
    db.commit()
    logger.info("Таблица 'text' создана или уже существует")
except sqlite3.Error as e:
    logger.error(f"Ошибка при создании таблицы 'text': {e}")

# Добавление новых пользователей в БД
def get_or_create_user(user):
    try:
        c.execute("SELECT * FROM users WHERE user_id=?", (user.id,))
        data = c.fetchone()
        
        if data is None:
            c.execute(
                "INSERT INTO users (user_id, username, first_name, last_name) VALUES (?, ?, ?, ?)",
                (user.id, user.username, user.first_name, user.last_name)
            )
            db.commit()
            logger.info(
                f"Добавлен новый пользователь: ID={user.id}, "
                f"username={user.username}, name={user.first_name} {user.last_name}"
            )
        else:
            logger.debug(f"Пользователь ID={user.id} уже существует в БД")
            
    except sqlite3.Error as e:
        logger.error(f"Ошибка при работе с таблицей 'users' (user_id={user.id}): {e}")

# === ИНИЦИАЛИЗАЦИЯ ТАБЛИЦЫ TEXT (если пусто) ===
try:
    c.execute("SELECT COUNT(*) FROM text")
    if c.fetchone()[0] == 0:
        c.execute('''
            INSERT INTO text (start, faq, contacts, info)
            VALUES ('Hello', 'Введите текст', 'Введите текст', 'Введите текст')
        ''')
        db.commit()
        logger.info("Инициализированы базовые тексты в таблице 'text'")
    else:
        logger.debug("Таблица 'text' уже содержит данные")
except sqlite3.Error as e:
    logger.error(f"Ошибка при работе с таблицей 'text': {e}")


#------------------------------Основная часть----------------------------------------------

# /start
@bot.message_handler(commands=["start"])
def start(message):
    user = message.from_user
    get_or_create_user(user)  

    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()

        c.execute("SELECT start FROM text")
        result = c.fetchone()

        if result is None:
            logger.error("В таблице 'text' нет данных для поля 'start'")
            start_text = "Добро пожаловать!"
        else:
            start_text = result[0]

        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        btn_1 = telebot.types.InlineKeyboardButton(text="🔗 Перейти в канал", url=channel)
        btn_2 = telebot.types.InlineKeyboardButton(text="ℹО проекте", callback_data="info")
        btn_3 = telebot.types.InlineKeyboardButton(text="❓FAQ", callback_data="faq")
        btn_4 = telebot.types.InlineKeyboardButton(text="📞Контакты", callback_data="contact")
        markup.add(btn_1, btn_2, btn_3, btn_4)

        bot.send_message(message.chat.id, start_text, reply_markup=markup)
        logger.info(f"Команда /start обработана для пользователя {user.id}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка БД в /start: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в /start: {e}")
    finally:
        if db:
            db.close()

# обработка кнопок /start
@bot.callback_query_handler(func=lambda call: call.data in ["info", "faq", "contact"])
def handle_content(call):
    try:
        if call.data == "info":
            info(call)
        elif call.data == "faq":
            faq(call)
        elif call.data == "contact":
            contact(call)
        bot.answer_callback_query(call.id)
        logger.debug(f"Обработан callback: {call.data} от пользователя {call.from_user.id}")
    except Exception as e:
        logger.error(f"Ошибка в handle_content: {e}")

# обработка кнопки Назад
@bot.callback_query_handler(func=lambda call: call.data == "back")
def handle_back(call):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()

        c.execute("SELECT start FROM text")
        result = c.fetchone()

        if result is None:
            logger.error("В таблице 'text' нет данных для поля 'start' при нажатии 'Назад'")
            start_text = "Добро пожаловать!"
        else:
            start_text = result[0]

        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        btn_1 = telebot.types.InlineKeyboardButton(text="🔗 Перейти в канал", url=channel)
        btn_2 = telebot.types.InlineKeyboardButton(text="ℹО проекте", callback_data="info")
        btn_3 = telebot.types.InlineKeyboardButton(text="❓FAQ", callback_data="faq")
        btn_4 = telebot.types.InlineKeyboardButton(text="📞Контакты", callback_data="contact")
        markup.add(btn_1, btn_2, btn_3, btn_4)

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=start_text,
            reply_markup=markup
        )
        bot.answer_callback_query(call.id)
        logger.info(f"Кнопка 'Назад' обработана для пользователя {call.from_user.id}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка БД в handle_back: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в handle_back: {e}")
    finally:
        if db:
            db.close()

# О проекте
def info(call):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()

        c.execute("SELECT info FROM text")
        result = c.fetchone()

        if result is None:
            logger.error("В таблице 'text' нет данных для поля 'info'")
            info_text = "Информация не доступна."
        else:
            info_text = result[0]

        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        btn_1 = telebot.types.InlineKeyboardButton(text="◀️ Назад", callback_data="back")
        btn_2 = telebot.types.InlineKeyboardButton(text="🔗 Перейти в канал", url=channel)
        markup.add(btn_1, btn_2)

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=info_text,
            reply_markup=markup
        )
        logger.info(f"Раздел 'О проекте' показан пользователю {call.from_user.id}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка БД в info(): {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в info(): {e}")
    finally:
        if db:
            db.close()

# FAQ
def faq(call):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()

        c.execute("SELECT faq FROM text")
        result = c.fetchone()

        if result is None:
            logger.error("В таблице 'text' нет данных для поля 'faq'")
            faq_text = "FAQ не доступен."
        else:
            faq_text = result[0]

        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        btn_1 = telebot.types.InlineKeyboardButton(text="◀️ Назад", callback_data="back")
        btn_2 = telebot.types.InlineKeyboardButton(text="🔗 Перейти в канал", url=channel)
        markup.add(btn_1, btn_2)

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=faq_text,
            reply_markup=markup
        )
        logger.info(f"Раздел FAQ показан пользователю {call.from_user.id}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка БД в faq(): {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в faq(): {e}")
    finally:
        if db:
            db.close()

# Контакты
def contact(call):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()

        c.execute("SELECT contacts FROM text")
        result = c.fetchone()

        if result is None:
            logger.error("В таблице 'text' нет данных для поля 'contacts'")
            contacts_text = "Контакты не доступны."
        else:
            contacts_text = result[0]

        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        btn_1 = telebot.types.InlineKeyboardButton(text="◀️ Назад", callback_data="back")
        btn_2 = telebot.types.InlineKeyboardButton(text="🔗 Перейти в канал", url=channel)
        markup.add(btn_1, btn_2)

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=contacts_text,
            reply_markup=markup
        )
        logger.info(f"Раздел 'Контакты' показан пользователю {call.from_user.id}")

    except sqlite3.Error as e:
        logger.error(f"Ошибка БД в contact(): {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в contact(): {e}")
    finally:
        if db:
            db.close()

#-------------------------------Админская часть--------------------------------------------

# Обработка команды /admin
@bot.message_handler(commands=['admin'])
def admin(message):
    try:
        if message.chat.id == admin_id:
            logger.info(f"Администратор {message.chat.id} открыл админ‑меню")
            
            markup = telebot.types.InlineKeyboardMarkup(row_width=2)
            btn_1 = telebot.types.InlineKeyboardButton(text="Редакт  ▶️Start", callback_data="redact_start")
            btn_2 = telebot.types.InlineKeyboardButton(text="Редакт  ❓FAQ", callback_data="redact_faq")
            btn_3 = telebot.types.InlineKeyboardButton(text="Редакт  ℹ️О проекте", callback_data="redact_info")
            btn_4 = telebot.types.InlineKeyboardButton(text="Редакт  📞Контакты", callback_data="redact_contacts")
            btn_6 = telebot.types.InlineKeyboardButton(text="Рассылка📨", callback_data="Broadcast_message")
            markup.add(btn_1, btn_2, btn_3, btn_4, btn_6)
            
            bot.send_message(message.chat.id, "Выберите действие", reply_markup=markup)
        else:
            logger.warning(f"Попытка доступа к админ‑меню от неавторизованного пользователя {message.chat.id}")
            bot.send_message(message.chat.id, "Ошибка, вы не являетесь администратором!")
    
    except Exception as e:
        logger.error(f"Ошибка в /admin: {e}", exc_info=True)


# Обработка кнопок /admin
@bot.callback_query_handler(func=lambda call: call.data in ["redact_start", "redact_faq", "redact_info", "redact_contacts", "Broadcast_message"])
def admin_handler(call):
    try:
        logger.info(f"Администратор {call.from_user.id} выбрал действие: {call.data}")
        
        if call.data == "redact_start":
            redact_start_input(call.message)
        elif call.data == "redact_faq":
            redact_faq_input(call.message)
        elif call.data == "redact_info":
            redact_info_input(call.message)
        elif call.data == "redact_contacts":
            redact_contacts_input(call.message)
        elif call.data == "Broadcast_message":
            start_broadcast(call.message)
        
        bot.answer_callback_query(call.id)
        
    except Exception as e:
        logger.error(f"Ошибка в admin_handler (действие {call.data}): {e}", exc_info=True)
        bot.answer_callback_query(call.id, text="Произошла ошибка", show_alert=True)

#-------------------------------Изменение текстов------------------------------------------

# Редактирование текста /start
def redact_start_input(message):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        c.execute("SELECT start FROM text")
        result = c.fetchone()
        db.close()
        
        current_text_start = result[0] if result else "Текст не найден"
        logger.info(f"Администратор {message.chat.id} запросил текущий текст /start")
        
        
        bot.send_message(
            message.chat.id,
            f"Текущий текст:\n\n{current_text_start}\n\n"
            "Введите новый текст для /start:"
        )
        bot.register_next_step_handler(message, redact_start)
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при получении текста /start: {e}")
        bot.send_message(message.chat.id, "Ошибка при получении текста. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_start_input: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Попробуйте снова.")

def redact_start(message):
    new_text = message.text.strip()
    
    if not new_text:
        logger.warning(f"Администратор {message.chat.id} попытался сохранить пустой текст /start")
        bot.send_message(message.chat.id, "Текст не может быть пустым!")
        return
    
    
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        # Обновляем текст в БД
        c.execute(
            "UPDATE text SET start = ? WHERE 1 = 1",
            (new_text,)
        )
        db.commit()
        db.close()
        
        logger.info(f"Текст /start успешно обновлён администратором {message.chat.id}")
        bot.send_message(message.chat.id, "✅ Текст успешно обновлён!")
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при обновлении текста /start: {e}")
        bot.send_message(message.chat.id, f"Ошибка при обновлении: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_start: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обновлении текста.")


# Редактирование текста "О проекте"
def redact_info_input(message):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        c.execute("SELECT info FROM text")
        result = c.fetchone()
        db.close()
        
        current_text_info = result[0] if result else "Текст не найден"
        logger.info(f"Администратор {message.chat.id} запросил текущий текст 'О проекте'")
        
        bot.send_message(
            message.chat.id,
            f"Текущий текст:\n\n{current_text_info}\n\n"
            "Введите новый текст для 'ℹ️О проекте':"
        )
        bot.register_next_step_handler(message, redact_info)
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при получении текста 'О проекте': {e}")
        bot.send_message(message.chat.id, "Ошибка при получении текста. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_info_input: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Попробуйте снова.")


def redact_info(message):
    new_text = message.text.strip()
    if not new_text:
        logger.warning(f"Администратор {message.chat.id} попытался сохранить пустой текст 'О проекте'")
        bot.send_message(message.chat.id, "Текст не может быть пустым!")
        return
    
    
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        # Обновляем текст в БД
        c.execute(
            "UPDATE text SET info = ? WHERE 1 = 1",
            (new_text,)
        )
        db.commit()
        db.close()
        
        logger.info(f"Текст 'О проекте' успешно обновлён администратором {message.chat.id}")
        bot.send_message(message.chat.id, "✅ Текст успешно обновлён!")
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при обновлении текста 'О проекте': {e}")
        bot.send_message(message.chat.id, f"Ошибка при обновлении: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_info: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обновлении текста.")




# Редактирование текста FAQ
def redact_faq_input(message):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        c.execute("SELECT faq FROM text")
        result = c.fetchone()
        db.close()
        
        current_text_faq = result[0] if result else "Текст не найден"
        logger.info(f"Администратор {message.chat.id} запросил текущий текст FAQ")
        
        bot.send_message(
            message.chat.id,
            f"Текущий текст:\n\n{current_text_faq}\n\n"
            "Введите новый текст для '❓FAQ':"
        )
        bot.register_next_step_handler(message, redact_faq)
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при получении текста FAQ: {e}")
        bot.send_message(message.chat.id, "Ошибка при получении текста. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_faq_input: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Попробуйте снова.")

def redact_faq(message):
    new_text = message.text.strip()
    
    if not new_text:
        logger.warning(f"Администратор {message.chat.id} попытался сохранить пустой текст FAQ")
        bot.send_message(message.chat.id, "Текст не может быть пустым!")
        return
    
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        # Обновляем текст в БД
        c.execute(
            "UPDATE text SET faq = ? WHERE 1 = 1",
            (new_text,)
        )
        db.commit()
        db.close()
        
        logger.info(f"Текст FAQ успешно обновлён администратором {message.chat.id}")
        bot.send_message(message.chat.id, "✅ Текст успешно обновлён!")
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при обновлении текста FAQ: {e}")
        bot.send_message(message.chat.id, f"Ошибка при обновлении: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_faq: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обновлении текста.")

# Редактирование текста "Контакты"
def redact_contacts_input(message):
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        c.execute("SELECT contacts FROM text")
        result = c.fetchone()
        db.close()
        
        current_text_contacts = result[0] if result else "Текст не найден"
        logger.info(f"Администратор {message.chat.id} запросил текущий текст 'Контакты'")
        
        bot.send_message(
            message.chat.id,
            f"Текущий текст:\n\n{current_text_contacts}\n\n"
            "Введите новый текст для '📞Контакты':"
        )
        bot.register_next_step_handler(message, redact_contacts)
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при получении текста 'Контакты': {e}")
        bot.send_message(message.chat.id, "Ошибка при получении текста. Попробуйте снова.")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_contacts_input: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Попробуйте снова.")

def redact_contacts(message):
    new_text = message.text.strip()
    
    if not new_text:
        logger.warning(f"Администратор {message.chat.id} попытался сохранить пустой текст 'Контакты'")
        bot.send_message(message.chat.id, "Текст не может быть пустым!")
        return
    
    
    try:
        db = sqlite3.connect('Bot.db')
        c = db.cursor()
        
        # Обновляем текст в БД
        c.execute(
            "UPDATE text SET contacts = ? WHERE 1 = 1",
            (new_text,)
        )
        db.commit()
        db.close()
        
        logger.info(f"Текст 'Контакты' успешно обновлён администратором {message.chat.id}")
        bot.send_message(message.chat.id, "✅ Текст успешно обновлён!")
        
    except sqlite3.Error as e:
        logger.error(f"Ошибка БД при обновлении текста 'Контакты': {e}")
        bot.send_message(message.chat.id, f"Ошибка при обновлении: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка в redact_contacts: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка при обновлении текста.")

        
#--------------------------------------описания--------------------------------------------

# Выбор какое описание сменить
def edit_description(message):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btn_1 = telebot.types.InlineKeyboardButton(text="Короткое", callback_data="short_description")
    btn_2 = telebot.types.InlineKeyboardButton(text="Длинное", callback_data="long_description")
    markup.add(btn_1, btn_2)
    bot.send_message(message.chat.id, "Выюерите какое описание хотите поменять: ", reply_markup=markup)


# Обработка кнопок функции edit_description
@bot.callback_query_handler(func=lambda call: call.data in ["short_description", "long_description"])
def edit_description_handler(call):
    if call.data == "short_description":
        set_short_description(call.message)
    elif call.data == "long_description":
        set_long_description(call.message)

    bot.answer_callback_query(call.id)

# Команды для длинного и короткого описаний
@bot.message_handler(commands=['setshort'])
def handle_setshort(message):
    set_short_description(message)

@bot.message_handler(commands=['setlong'])
def handle_setlong(message):
    set_long_description(message)



# Смена короткого описания(short)
def set_short_description(message):
    if message.from_user.id != admin_id:
        bot.reply_to(message, "❌ Доступ запрещён!")
        return

    # Проверка наличия текста
    if not message.text:
        bot.reply_to(message, "❌ Введите текст после команды!")
        return

    try:
        # Извлекаем текст после команды
        parts = message.text.split('/setshort', 1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(message, "❌ Укажите текст после команды:\n/setshort Новый текст")
            return

        new_text = parts[1].strip()

        # Проверка длины
        if len(new_text) > 120:
            bot.reply_to(
                message,
                f"❌ Слишком длинно! Максимум 120 символов. Сейчас: {len(new_text)}"
            )
            return

        # Корректный URL API
        url = f"https://api.telegram.org/bot{token}/setMyShortDescription"
        payload = {"description": new_text}

        # Отправка запроса с таймаутом
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()  # Вызовет исключение при HTTP-ошибке


        result = response.json()
        if result.get("ok"):
            bot.reply_to(message, "✅ Короткое описание обновлено!")
        else:
            bot.reply_to(
                message,
                f"❌ Ошибка API: {result.get('description', 'Неизвестная ошибка')}"
            )

    except requests.exceptions.RequestException as e:
        bot.reply_to(message, f"❌ Ошибка сети: {e}")
    except Exception as e:
        bot.reply_to(message, f"❌ Неожиданная ошибка: {e}")




# Смена длинного описания(long)
def set_long_description(message):
    # Проверка прав администратора
    if message.from_user.id != admin_id:
        bot.reply_to(message, "❌ Доступ запрещён!")
        return

    # Проверка наличия текста в сообщении
    if not message.text:
        bot.reply_to(message, "❌ Введите текст после команды!")
        return

    try:
        # Безопасное разделение строки (учитываем возможные пробелы)
        parts = message.text.split('/setlong', maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            bot.reply_to(
                message,
                "❌ Укажите текст после команды:\n/setlong Новый текст"
            )
            return

        new_text = parts[1].strip()

        # Проверка длины текста
        if len(new_text) > 512:
            bot.reply_to(
                message,
                f"❌ Слишком длинно! Максимум 512 символов. Сейчас: {len(new_text)}"
            )
            return

        # Формирование корректного URL
        url = f"https://api.telegram.org/bot{token}/setMyDescription"
        payload = {"description": new_text}

        # Настройка сессии с повторными попытками
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)

        # Отправка запроса
        response = session.post(url, json=payload, timeout=10)
        response.raise_for_status()

        result = response.json()

        if result.get("ok"):
            bot.reply_to(message, "✅ Длинное описание обновлено!")
        else:
            error_desc = result.get('description', 'Неизвестная ошибка')
            bot.reply_to(message, f"❌ Ошибка API: {error_desc}")

    except requests.exceptions.RequestException as e:
        bot.reply_to(message, f"❌ Ошибка сети: {e}")
    except Exception as e:
        bot.reply_to(message, f"❌ Неожиданная ошибка: {type(e).__name__}: {e}")


#-----------------------------------рассылка-----------------------------------------------

# Глобальные переменные
broadcast_data = {}
send_queue = queue.Queue()
STOP_FLAG = False

def get_db_connection():
    db_path = os.path.join(os.path.dirname(__file__), 'Bot.db')
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users';")
        if not cursor.fetchone():
            logger.error("Ошибка: таблица users не найдена в Bot.db")
            conn.close()
            return None, None
        logger.info("Успешно подключено к Bot.db, таблица users существует")
        return conn, cursor
    except Exception as e:
        logger.error(f"Ошибка подключения к Bot.db: {e}")
        return None, None

def is_user_subscribed(user_id, channel):
    try:
        chat_member = bot.get_chat_member(channel_id, user_id)
        status = chat_member.status
        if status in ['member', 'administrator', 'creator']:
            logger.debug(f"Пользователь {user_id} подписан (статус: {status})")
            return True
        else:
            logger.warning(f"Пользователь {user_id} имеет статус '{status}' в канале {channel_id}")
            return False
    except Exception as e:
        error_desc = str(e).lower()
        if 'chat not found' in error_desc:
            logger.error(f"Канал {channel_id} не найден или бот не имеет доступа. Проверьте ID/юзернейм.")
        elif 'user not found' in error_desc:
            logger.error(f"Пользователь {user_id} не существует или скрыт.")
        elif 'bot was kicked' in error_desc:
            logger.error(f"Бот исключён из канала {channel_id}. Добавьте его заново.")
        else:
            logger.error(f"Неизвестная ошибка для {user_id}: {e}")
        return False

@bot.message_handler(func=lambda message: message.text == 'Начать рассылку')
def start_broadcast(message):
    try:
        broadcast_data.clear()
        broadcast_data['chat_id'] = message.chat.id
        logger.info(f"Администратор {message.chat.id} начал создание рассылки")


        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
        markup.add("Добавить фото", "Добавить текст", "Добавить кнопки", "Предпросмотр и отправка")
        bot.send_message(
            message.chat.id,
            "Создайте рассылку. Выберите действие:",
            reply_markup=markup
        )
        bot.register_next_step_handler(message, handle_menu)
    except Exception as e:
        logger.error(f"Ошибка в start_broadcast: {e}")

def handle_menu(message):
    try:
        if message.text == "Добавить фото":
            logger.info(f"Администратор {message.chat.id} выбрал добавление фото")
            bot.send_message(message.chat.id, "Отправьте фото:")
            bot.register_next_step_handler(message, process_photo)
        elif message.text == "Добавить текст":
            logger.info(f"Администратор {message.chat.id} выбрал добавление текста")
            bot.send_message(message.chat.id, "Введите текст:")
            bot.register_next_step_handler(message, process_caption)
        elif message.text == "Добавить кнопки":
            logger.info(f"Администратор {message.chat.id} выбрал добавление кнопок")
            bot.send_message(
                message.chat.id,
                "Кнопки в формате:\nТекст|ссылка\nПример:\nСайт|https://example.com"
            )
            bot.register_next_step_handler(message, process_buttons)
        elif message.text == "Предпросмотр и отправка":
            logger.info(f"Администратор {message.chat.id} запросил предпросмотр рассылки")
            validate_and_preview(message)
        else:
            logger.warning(f"Неизвестная команда от администратора {message.chat.id}: {message.text}")
            bot.send_message(message.chat.id, "Неизвестная команда.")
            start_broadcast(message)
    except Exception as e:
        logger.error(f"Ошибка в handle_menu: {e}")

def process_photo(message):
    try:
        if message.content_type != 'photo':
            logger.warning(f"Администратор {message.chat.id} отправил не фото")
            bot.send_message(message.chat.id, "Это не фото. Попробуйте снова.")
            bot.register_next_step_handler(message, process_photo)
            return
        broadcast_data['photo'] = message.photo[-1].file_id
        logger.info(f"Фото добавлено в рассылку (fileID: {broadcast_data['photo']})")
        return_to_menu(message)
    except Exception as e:
        logger.error(f"Ошибка в process_photo: {e}")

def process_caption(message):
    try:
        broadcast_data['caption'] = message.text
        logger.info(f"Текст добавлен в рассылку: {broadcast_data['caption']}")
        return_to_menu(message)
    except Exception as e:
        logger.error(f"Ошибка в process_caption: {e}")

def process_buttons(message):
    try:
        lines = message.text.strip().split('\n')
        markup = types.InlineKeyboardMarkup()
        for line in lines:
            parts = line.split('|')
            if len(parts) == 2:
                text, url = parts
                markup.add(types.InlineKeyboardButton(text.strip(), url=url.strip()))
        broadcast_data['markup'] = markup
        logger.info(f"Кнопки добавлены в рассылку ({len(lines)} шт.)")
        return_to_menu(message)
    except Exception as e:
        logger.error(f"Ошибка в process_buttons: {e}")

def return_to_menu(message):
    try:
        markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
        markup.add("Добавить фото", "Добавить текст", "Добавить кнопки", "Предпросмотр и отправка")
        bot.send_message(
            message.chat.id,
            "Что дальше?",
            reply_markup=markup
        )
        bot.register_next_step_handler(message, handle_menu)
    except Exception as e:
        logger.error(f"Ошибка в return_to_menu: {e}")

def validate_and_preview(message):
    try:
        if 'photo' not in broadcast_data and 'caption' not in broadcast_data:
            logger.warning(f"Администратор {message.chat.id} попытался отправить пустую рассылку")
            bot.send_message(
                message.chat.id,
                "Ошибка: нужно добавить хотя бы фото ИЛИ текст!"
            )
            return_to_menu(message)
            return

        logger.info(f"Администратор {message.chat.id} получил предпросмотр рассылки")
        bot.send_message(message.chat.id, "<b>Предпросмотр рассылки:</b>", parse_mode='HTML')
        
        if 'photo' in broadcast_data:
            bot.send_photo(
                chat_id=message.chat.id,
                photo=broadcast_data['photo'],
                caption=broadcast_data.get('caption', ''),
                reply_markup=broadcast_data.get('markup'),
                parse_mode='HTML'
            )
        else:
            bot.send_message(
                chat_id=message.chat.id,
                text=broadcast_data['caption'],
                reply_markup=broadcast_data.get('markup'),
                parse_mode='HTML'
            )

        confirm_markup = types.ReplyKeyboardMarkup(one_time_keyboard=True)
        confirm_markup.add("Отправить всем", "Отменить")
        bot.send_message(
            message.chat.id,
            "Отправить всем подписчикам канала?",
            reply_markup=confirm_markup
        )
        bot.register_next_step_handler(message, confirm_sending)
        
    except Exception as e:
        logger.error(f"Ошибка в validate_and_preview: {e}")



def confirm_sending(message):
    try:
        if message.text != "Отправить всем":
            logger.info(f"Администратор {message.chat.id} отменил рассылку")
            bot.send_message(
                message.chat.id,
                "Рассылка отменена.",
                reply_markup=types.ReplyKeyboardRemove()
            )
            broadcast_data.clear()
            return

        logger.info(f"Администратор {message.chat.id} подтвердил отправку рассылки")

        conn, cursor = get_db_connection()
        users = []

        if conn and cursor:
            try:
                cursor.execute("SELECT user_id FROM users WHERE user_id IS NOT NULL")
                users = cursor.fetchall()
                conn.close()
                logger.info(f"Получено {len(users)} записей из таблицы users")
            except Exception as e:
                logger.error(f"Ошибка запроса к БД: {e}")
                bot.send_message(message.chat.id, f"Ошибка запроса к БД: {e}")
                return
        else:
            logger.error("Не удалось подключиться к Bot.db")
            bot.send_message(message.chat.id, "Ошибка: не удалось подключиться к Bot.db.")
            return

        if not users:
            logger.warning("В таблице users нет записей с user_id")
            bot.send_message(
                message.chat.id,
                "Ошибка: в таблице users нет записей с user_id!"
            )
            broadcast_data.clear()
            return

        # Заполняем очередь только для подписчиков
        subscribed_count = 0
        for user in users:
            user_id = user[0]
            if is_user_subscribed(user_id, channel):
                send_queue.put(user_id)
                subscribed_count += 1
            else:
                logger.debug(f"Пользователь {user_id} не подписан на канал {channel}")

        if subscribed_count == 0:
            logger.warning("Нет подписчиков канала для рассылки")
            bot.send_message(
                message.chat.id,
                "Нет подписчиков канала для рассылки!",
                reply_markup=types.ReplyKeyboardRemove()
            )
            broadcast_data.clear()
            return

        logger.info(f"Начата рассылка для {subscribed_count} подписчиков канала")
        bot.send_message(
            message.chat.id,
            f"Начата рассылка для {subscribed_count} подписчиков канала...",
            reply_markup=types.ReplyKeyboardRemove()
        )

        threading.Thread(target=send_messages, daemon=True).start()
        
    except Exception as e:
        logger.error(f"Ошибка в confirm_sending: {e}")



def send_messages():
    sent = 0
    failed = 0
    blocked = 0
    throttle_delay = 0.05  # начальная задержка 50 мс

    while not send_queue.empty() and not STOP_FLAG:
        user_id = send_queue.get()

        try:
            if 'photo' in broadcast_data:
                bot.send_photo(
                    chat_id=user_id,
                    photo=broadcast_data['photo'],
                    caption=broadcast_data.get('caption', ''),
                    reply_markup=broadcast_data.get('markup'),
                    parse_mode='HTML'
                )
            else:
                bot.send_message(
                    chat_id=user_id,
                    text=broadcast_data['caption'],
                    reply_markup=broadcast_data.get('markup'),
                    parse_mode='HTML'
                )
            sent += 1
            logger.info(f"Отправлено пользователю {user_id}")

        except telebot.apihelper.ApiException as e:
            error_str = str(e).lower()
            if '429' in error_str:  # Too Many Requests
                throttle_delay = min(throttle_delay * 2, 30)  # удваиваем, максимум 30 сек
                logger.warning(f"429: увеличиваем задержку до {throttle_delay} сек для пользователя {user_id}")
                time.sleep(throttle_delay)
                send_queue.put(user_id)  # возвращаем в очередь
                continue
            elif any(err in error_str for err in ['blocked', 'kicked', 'unauthorized']):
                blocked += 1
                logger.warning(f"Пользователь {user_id} заблокировал бота")
            else:
                failed += 1
                logger.error(f"API-ошибка для {user_id}: {e}")

        except Exception as e:  # Неожиданные ошибки
            failed += 1
            logger.error(f"Неожиданная ошибка для {user_id}: {e}")

        # Базовая задержка между сообщениями
        time.sleep(throttle_delay)

    # Отчёт после завершения рассылки
    report_msg = (
        f"<b>Рассылка завершена!</b>\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибки: {failed}\n"
        f"🚫 Заблокировали бота: {blocked}"
    )
    logger.info(f"Рассылка завершена. Отправлено: {sent}, ошибки: {failed}, заблокировали: {blocked}")
    
    try:
        bot.send_message(
            broadcast_data['chat_id'],
            report_msg,
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error(f"Не удалось отправить отчёт администратору: {e}")

    broadcast_data.clear()


#------------------------------------------------------------------------------------------

if __name__ == '__main__':
    logger.info("Запуск бота. Начало polling...")
    
    while True:
        try:
            bot.polling(none_stop=True, timeout=60)
            logger.info("Бот завершает работу (polling остановлен)")
            break  # Выходим, если polling явно остановлен

        except KeyboardInterrupt:
            logger.warning("Получен сигнал KeyboardInterrupt (Ctrl+C). Завершение работы...")
            print("Бот остановлен вручную.")
            break

        except Exception as e:
            error_msg = f"Критическая ошибка в основном цикле бота: {e}"
            logger.critical(error_msg, exc_info=True)
            print(f"Произошла критическая ошибка: {e}. Продолжаем работу...")

            
            clean_trace = traceback.format_exc().replace('<', '&lt;').replace('>', '&gt;')
            

        
            for i in range(10):
                try:
                    bot.send_message(
                        admin_id,
                        f"🚨 КРИТИЧЕСКАЯ ОШИБКА В БОТЕ\n\n"
                        f"Попытка {i+1}/10\n\n"
                        f"{error_msg}\n\n"
                        f"<pre>Трассировка:\n{clean_trace}</pre>",
                        parse_mode='HTML'
                    )
                    logger.info(f"Отправлено уведомление админу (попытка {i+1}/10)")
                except Exception as send_err:
                    logger.error(f"Не удалось отправить уведомление админу (попытка {i+1}): {send_err}")
                
                time.sleep(10)  

            # После отправки уведомлений продолжаем polling
            logger.info("Продолжаем работу бота после отправки уведомлений...")
            time.sleep(5)  # Небольшая пауза перед перезапуском polling
