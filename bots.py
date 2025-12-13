async def save_task_to_sheets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Шаг 5: Сохранение задачи в Google Sheets в первую пустую строку (A-H)"""
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
            # 1. Находим номер строки для вставки
            task_column_values = worksheet.col_values(1)
            
            # Находим последнюю строку, которая не пуста, начиная с 5-й строки.
            last_used_row = START_ROW_INDEX - 1
            for i, value in enumerate(task_column_values[START_ROW_INDEX - 1:], START_ROW_INDEX):
                if value.strip():
                    last_used_row = i
                else:
                    break
            
            gspread_row_index = last_used_row + 1
            
            # 2. Формула для колонки D ('Дни ⏳')
            # Переместили формулу в колонку D (4-я позиция)
            days_formula = f'=IF(ISBLANK(C{gspread_row_index}), "", C{gspread_row_index}-TODAY())'
            
            # 3. НОВАЯ СТРУКТУРА СТРОКИ ДЛЯ ВСТАВКИ (8 элементов)
            # Предполагаем, что ваша новая структура:
            # A=Задача, B=Название (повтор, оставим пустым), C=Срок, D=Дни, E=Приоритет, F=Выполнено, G=Категория, H=Заметки
            # Примечание: Мы немного адаптировали вашу структуру для устранения конфликта.
            
            row_data = [
                task_name,       # A (Кол 1) - Название
                '',              # B (Кол 2) - В вашей таблице A=№, B=Название, C=Срок
                deadline,        # C (Кол 3) - Срок
                days_formula,    # D (Кол 4) - Дни до срока (Формула) <-- НОВАЯ ПОЗИЦИЯ
                priority,        # E (Кол 5) - Приоритет <-- НОВАЯ ПОЗИЦИЯ
                'FALSE',         # F (Кол 6) - Выполнено (Флажок) <-- НОВАЯ ПОЗИЦИЯ
                category,        # G (Кол 7) - Категория <-- Сдвинулась на G
                description      # H (Кол 8) - Заметки
            ]
            
            # 4. Вставка данных с помощью update в диапазон A{индекс}:H{индекс}
            range_label = f'A{gspread_row_index}:H{gspread_row_index}'
            # Внимание: Вызов update('A:H') перезаписывает 8 колонок. 
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
