import os
import logging
import json
from datetime import datetime
import datetime as dt 
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from dotenv import load_dotenv
import gspread
from google.oauth2.service_account import Credentials

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Функция для записи debug логов (оставлена как есть)
def debug_log(hypothesis_id, location, message, data=None):
    """Запись debug лога в NDJSON формате"""
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(script_dir, '.cursor', 'debug.log')
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        log_entry = {
            "id": f"log_{int(datetime.now().timestamp() * 1000)}",
            "timestamp": int(datetime.now().timestamp() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "sessionId": "debug-session",
            "runId": "run1",
            "hypothesisId": hypothesis_id
        }
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    except Exception as e:
        import sys
        print(f"DEBUG LOG ERROR: {e}", file=sys.stderr)
        print(f"Location: {location}, Message: {message}, Data: {data}", file=sys.stderr)

# ==============================================================================
# КОНСТАНТЫ СОСТОЯНИЙ (5 ШАГОВ)
# ==============================================================================

TASK_NAME, TASK_DESCRIPTION, TASK_DEADLINE, TASK_PRIORITY, TASK_CATEGORY = range(5)
# Строка, с которой начинается блок данных (5-я строка после заголовков)
START_ROW_INDEX = 5 

# ==============================================================================
# ИНИЦИАЛИЗАЦИЯ GOOGLE SHEETS
# ==============================================================================
def init_google_sheets():
    """
    Инициализация подключения к Google Sheets.
    """
    try:
        creds_json_str = os.getenv('GOOGLE_CREDENTIALS_JSON')
        if not creds_json_str:
            logger.error("Переменная GOOGLE_CREDENTIALS_JSON не установлена.")
            return None
        
        credentials_info = json.loads(creds_json_str) 
        
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        
        creds = Credentials.from_service_account_info(credentials_info, scopes=scope)
        client = gspread.authorize(creds)
        
        spreadsheet_id = os.getenv('SPREADSHEET_ID')
        if not spreadsheet_id:
            raise ValueError("SPREADSHEET_ID не установлен.")
        
        worksheet_name = os.getenv('WORKSHEET_NAME', 'Список Задач') 
        spreadsheet = client.open_by_key(spreadsheet_id)
        worksheet = spreadsheet.worksheet(worksheet_name)
        
        return worksheet
    except Exception as e:
        logger.error(f"Ошибка при инициализации Google Sheets: {e}")
        return None

worksheet = init_google_sheets()

# ==============================================================================
# ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ДАННЫХ ИЗ ТАБЛИЦЫ
# ==============================================================================

def get_unique_values(worksheet, column_index, default_values=None):
    """
    Получает уникальные значения из указанного столбца, исключая заголовок,
    приоритезируя default_values и фильтруя "мусор".
    """
    if not worksheet:
        return default_values or []

    try:
        column_values = worksheet.col_values(column_index)
        
        if len(column_values) < START_ROW_INDEX:
            return default_values or []
        
        data_values = column_values[START_ROW_INDEX - 1:] 
        
        unique_sheet_set = set()
        for v in data_values:
            v_stripped = v.strip()
            # Фильтрация "мусора"
            if v_stripped:
                if len(v_stripped) < 1 or len(v_stripped) > 50:
                    continue
                if v_stripped.upper() in ('FALSE', 'TRUE', 'ERROR', '#N/A'):
                    continue
                
                unique_sheet_set.add(v_stripped)
        
        ordered_unique_list = []
        
        # 1. Добавляем пользовательские default_values в заданном порядке
        if default_values:
            ordered_unique_list.extend(default_values)
        
        defaults_set = set(ordered_unique_list)

        # 2. Добавляем уникальные значения из таблицы, которых нет в default_values
        sheet_items_to_add = []
        
        # Сортируем то, что осталось в таблице, для предсказуемости
        for item in sorted(list(unique_sheet_set)):
            if item not in defaults_set:
                sheet_items_to_add.append(item)

        ordered_unique_list.extend(sheet_items_to_add)

        return ordered_unique_list
        
    except Exception as e:
        logger.warning(f"Ошибка при чтении уникальных значений из столбца {column_index}: {e}")
        return default_values or []

# ==============================================================================
# ОБРАБОТЧИКИ КОМАНД И ДИАЛОГА
# ==============================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    keyboard = [
        [InlineKeyboardButton("➕ Добавить задачу", callback_data='add_task')],
        [InlineKeyboardButton("📋 Показать задачи", callback_data='show_tasks')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Привет! Я бот для управления задачами в Google Таблицах.\n\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'add_task':
        await query.message.reply_text(
            "📝 Введите название задачи (Колонка B):"
        )
        return TASK_NAME 
    
    elif query.data == 'show_tasks':
        await show_tasks(update, context, message_source='callback')
        return ConversationHandler.END

async def add_task_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 1: Получение Названия Задачи (Колонка B)"""
    task_name = update.message.text
    context.user_data['task_name'] = task_name
    
    await update.message.reply_text(
        f"✅ Название задачи: {task_name}\n\n"
        "📝 Введите Заметки/Описание задачи (Колонка H) (или отправьте '-' чтобы пропустить):"
    )
    return TASK_DESCRIPTION 

async def add_task_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 2: Получение Заметок/Описания (Колонка H)"""
    description = update.message.text
    context.user_data['description'] = description if description != '-' else ''

    await update.message.reply_text(
        f"📝 Заметки: {'Добавлены' if context.user_data['description'] else 'Пропущено'}\n\n"
        "📅 Введите Срок выполнения (Колонка C). Используйте формат **ДД.ММ** (например, '25.12' или 'завтра'):"
    )
    return TASK_DEADLINE 

async def add_task_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 3: Получение Срока (Колонка C) и запрос Приоритета (Колонка E)"""
    deadline_input = update.message.text.strip().lower()
    
    today = datetime.now().date()
    deadline_date_str = deadline_input
    
    # Логика парсинга даты
    if deadline_input == 'завтра':
        deadline_date_str = (today + dt.timedelta(days=1)).strftime('%Y-%m-%d')
    elif deadline_input.count('.') == 1 and len(deadline_input.split('.')[0]) <= 2:
        try:
            day, month = map(int, deadline_input.split('.'))
            
            year = today.year
            # Перенос на следующий год, если дата уже прошла
            if month < today.month or (month == today.month and day < today.day):
                 year += 1

            deadline_date_str = datetime(year, month, day).strftime('%Y-%m-%d')
        except ValueError:
            pass 

    context.user_data['deadline'] = deadline_date_str

    # Колонка 5 = E (для Приоритета)
    default_priorities = ['Высокий', 'Срочный', 'Средний', 'Низкий']
    priority_values = get_unique_values(worksheet, 5, default_values=default_priorities) 
    
    keyboard = []
    for value in priority_values:
        keyboard.append(InlineKeyboardButton(f"⭐ {value}", callback_data=f'priority_{value}'))
        
    reply_markup = InlineKeyboardMarkup([keyboard[i:i + 3] for i in range(0, len(keyboard), 3)])

    await update.message.reply_text(
        f"📅 Срок (для записи): {deadline_date_str}\n\n"
        "⭐ Выберите Приоритет (Колонка E) (или введите вручную):",
        reply_markup=reply_markup
    )
    return TASK_PRIORITY 

async def add_task_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 4: Получение Приоритета (Колонка E) и запрос Категории (Колонка G)"""
    query = update.callback_query
    priority_value = None
    
    if query:
        await query.answer()
        priority_value = query.data.split('_', 1)[1] 
        context.user_data['priority'] = priority_value
        message = query.message
    else:
        priority_value = update.message.text
        context.user_data['priority'] = priority_value
        message = update.message

    # Колонка 7 = G (для Категории)
    default_categories = ['Личное', 'Работа', 'Другое']
    category_values = get_unique_values(worksheet, 7, default_values=default_categories)

    keyboard = []
    for value in category_values:
        keyboard.append(InlineKeyboardButton(f"📁 {value}", callback_data=f'category_{value}'))
        
    reply_markup = InlineKeyboardMarkup([keyboard[i:i + 2] for i in range(0, len(keyboard), 2)])

    await message.reply_text(
        f"⭐ Приоритет: {priority_value}\n\n"
        "📁 Выберите Категорию (Колонка G) (или введите вручную):",
        reply_markup=reply_markup
    )
    return TASK_CATEGORY 

async def save_task_to_sheets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Шаг 5: Сохранение задачи в Google Sheets в первую пустую строку (A-H).
    Поиск идет по колонке B.
    """
    query = update.callback_query
    category = None

    if query:
        await query.answer()
        category = query.data.split('_', 1)[1] 
        message = query.message
    else:
        category = update.message.text
        message = update.message

    task_name = context.user_data.get('task_name', 'Без названия')
    deadline = context.user_data.get('deadline', '')
    priority = context.user_data.get('priority', '')
    description = context.user_data.get('description', '')
    
    if worksheet:
        try:
            # 1. Находим номер строки для вставки. Ищем по колонке 2 (B - Название задачи)
            task_column_values = worksheet.col_values(2) 
            
            last_used_row = START_ROW_INDEX - 1
            for i, value in enumerate(task_column_values[START_ROW_INDEX - 1:], START_ROW_INDEX):
                if value.strip():
                    last_used_row = i
                else:
                    break
            
            gspread_row_index = last_used_row + 1
            
            # 2. Формула для колонки D ('Дни ⏳')
            days_formula = f'=IF(ISBLANK(C{gspread_row_index}), "", C{gspread_row_index}-TODAY())'
            
            # 3. ФИНАЛЬНАЯ СТРУКТУРА СТРОКИ (8 элементов A-H)
            
            row_data = [
                '',              # A (Кол 1) - Оставляем пустым для ID/номера
                task_name,       # B (Кол 2) - Название задачи
                deadline,        # C (Кол 3) - Срок
                days_formula,    # D (Кол 4) - Дни до срока (Формула)
                priority,        # E (Кол 5) - Приоритет
                'FALSE',         # F (Кол 6) - Выполнено (Флажок)
                category,        # G (Кол 7) - Категория
                description      # H (Кол 8) - Заметки
            ]
            
            # 4. Вставка данных с помощью update в диапазон A{индекс}:H{индекс}
            # ИСПРАВЛЕННАЯ СТРОКА: Устранена синтаксическая ошибка
            range_label = f'A{gspread_row_index}:H{gspread_row_index}'
            worksheet.update(range_label, [row_data], value_input_option='USER_ENTERED')
            
            await message.reply_text(
                f"✅ Задача успешно добавлена в таблицу в строку **{gspread_row_index}**!\n\n"
                f"📋 Название: {task_name}\n"
                f"📅 Срок: {deadline}\n"
                f"⭐ Приоритет: {priority}\n"
                f"📁 Категория: {category}"
            )

        except Exception as e:
            logger.error(f"Ошибка при сохранении задачи: {e}")
            await message.reply_text(
                f"❌ Ошибка при сохранении задачи в таблицу: {str(e)}"
            )
    else:
        await message.reply_text(
            "❌ Ошибка подключения к Google Sheets. Проверьте настройки."
        )

    context.user_data.clear()
    return ConversationHandler.END


# ==============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ==============================================================================

async def show_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, message_source='message'):
    """Показать последние задачи из таблицы"""
    try:
        if message_source == 'callback' and update.callback_query:
            message_obj = update.callback_query.message
        elif update.message:
            message_obj = update.message
        else:
            logger.error("Не удалось определить объект для отправки сообщения.")
            return

        if not worksheet:
            await message_obj.reply_text("❌ Ошибка подключения к Google Sheets. Проверьте настройки.")
            return
        
        all_values = worksheet.get_all_values()
        
        if len(all_values) <= 1:
            await message_obj.reply_text("📋 В таблице пока нет задач.")
            return
        
        tasks = all_values[1:][-10:]
        tasks.reverse()
        
        message = "📋 Последние задачи:\n\n"
        for i, task in enumerate(tasks, 1):
            # Название задачи читается из индекса 1 (Колонка B)
            task_name = task[1] if len(task) > 1 else 'Без названия'
            # Срок в индексе 2 (Колонка C)
            deadline = task[2] if len(task) > 2 else 'Срок не указан'
            
            # Статус выполнения в индексе 5 (Колонка F)
            status = '✅ Выполнено' if len(task) > 5 and str(task[5]).upper() == 'TRUE' else '⏳ Не выполнено'
            
            message += f"{i}. [{status}] {task_name} (Срок: {deadline})\n"
        
        await message_obj.reply_text(message)
    
    except Exception as e:
        logger.error(f"Ошибка при чтении задач: {e}")
        if update.callback_query:
            await update.callback_query.message.reply_text(f"❌ Ошибка при чтении задач: {str(e)}")
        elif update.message:
            await update.message.reply_text(f"❌ Ошибка при чтении задач: {str(e)}")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции"""
    context.user_data.clear()
    await update.message.reply_text("❌ Операция отменена.")
    return ConversationHandler.END


def main():
    """Главная функция запуска бота"""
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    
    if not bot_token:
        logger.error("TELEGRAM_BOT_TOKEN не установлен в .env файле!")
        return
    
    if not worksheet:
        logger.error("Не удалось подключиться к Google Sheets!")
        return
    
    application = Application.builder().token(bot_token).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern='^add_task$')],
        states={
            TASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_name)],
            TASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_description)],
            TASK_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_deadline)],
            TASK_PRIORITY: [
                CallbackQueryHandler(add_task_priority, pattern='^priority_.+$'), 
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_priority) 
            ],
            TASK_CATEGORY: [
                CallbackQueryHandler(save_task_to_sheets, pattern='^category_.+$'), 
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_task_to_sheets)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)] 
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback)) 
    
    logger.info("Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
