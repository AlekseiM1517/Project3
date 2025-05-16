import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
import io
import re

import matplotlib.pyplot as plt
from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

BOT_TOKEN = "7224198535:AAHkkSz5VQHaT0uZVOXyi_Sd6qIfEq7-Kso"
DATABASE_NAME = "finance_bot.db"


def create_tables():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            type TEXT NOT NULL,
            category TEXT,
            amount REAL NOT NULL,
            description TEXT,
            user_id INTEGER NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reminder_time TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_goals (
            user_id INTEGER PRIMARY KEY,
            goal_amount REAL NOT NULL,
            goal_description TEXT
        )
    """)
    conn.commit()
    conn.close()


def add_transaction(user_id, date, type, category, amount, description=""):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (user_id, date, type, category, amount, description)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, date, type, category, amount, description))
    conn.commit()
    conn.close()


def get_transactions(user_id, start_date=None, end_date=None):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    query = """
        SELECT date, type, category, amount, description
        FROM transactions
        WHERE user_id = ?
    """
    params = [user_id]
    if start_date and end_date:
        query += " AND date BETWEEN ? AND ?"
        params.extend([start_date, end_date])
    query += " ORDER BY date DESC"
    cursor.execute(query, params)
    transactions = cursor.fetchall()
    conn.close()
    return transactions


def get_monthly_summary(user_id, year, month):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT type, SUM(amount)
        FROM transactions
        WHERE user_id = ? AND strftime('%Y', date) = ? AND strftime('%m', date) = ?
        GROUP BY type
    """, (user_id, str(year), str(month).zfill(2)))
    summary = cursor.fetchall()
    conn.close()
    return summary


def add_reminder(user_id, reminder_time, text):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO reminders (user_id, reminder_time, text, created_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, reminder_time, text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def get_reminders(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, reminder_time, text
        FROM reminders
        WHERE user_id = ?
        ORDER BY reminder_time ASC
    """, (user_id,))
    reminders = cursor.fetchall()
    conn.close()
    return reminders


def delete_reminder(reminder_id, user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        DELETE FROM reminders WHERE id = ? AND user_id = ?
    """, (reminder_id, user_id))
    conn.commit()
    conn.close()


def set_user_goal(user_id, goal_amount, goal_description):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO user_goals (user_id, goal_amount, goal_description)
            VALUES (?, ?, ?)
        """, (user_id, goal_amount, goal_description))
    except sqlite3.IntegrityError:
        cursor.execute("""
            UPDATE user_goals SET goal_amount = ?, goal_description = ?
            WHERE user_id = ?
        """, (goal_amount, goal_description, user_id))
    conn.commit()
    conn.close()


def get_user_goal(user_id):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT goal_amount, goal_description
        FROM user_goals
        WHERE user_id = ?
    """, (user_id,))
    goal = cursor.fetchone()
    conn.close()
    return goal


class TransactionState(StatesGroup):
    type = State()
    amount = State()
    category = State()
    description = State()


class ReminderState(StatesGroup):
    time = State()
    text = State()


class DeleteReminderState(StatesGroup):
    reminder_id = State()


class ReportState(StatesGroup):
    start_date = State()
    end_date = State()


class GoalState(StatesGroup):
    amount = State()
    description = State()


main_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Добавить доход"),
            KeyboardButton(text="Добавить расход"),
        ],
        [
            KeyboardButton(text="Отчет"),
        ],
        [
            KeyboardButton(text="Напоминания"),
            KeyboardButton(text="Добавить напоминание"),
            KeyboardButton(text="Удалить напоминание"),
        ],
        [
            KeyboardButton(text="Установить цель"),
        ],
    ],
    resize_keyboard=True,
)

cancel_keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="Отмена"),
        ],
    ],
    resize_keyboard=True,
)

router = Router()


@router.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! Я твой финансовый помощник и тайм-менеджер. Выбери действие:",
        reply_markup=main_keyboard,
    )


@router.message(F.text == "Добавить доход")
async def income_handler(message: types.Message, state: FSMContext):
    await state.set_state(TransactionState.amount)
    await state.update_data(type="income")
    await message.reply("Введи сумму дохода:", reply_markup=cancel_keyboard)


@router.message(F.text == "Добавить расход")
async def expense_handler(message: types.Message, state: FSMContext):
    await state.set_state(TransactionState.amount)
    await state.update_data(type="expense")
    await message.reply("Введи сумму расхода:", reply_markup=cancel_keyboard)


@router.message(TransactionState.amount, F.text)
async def process_amount(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    try:
        amount = float(message.text)
        await state.update_data(amount=amount)
        await state.set_state(TransactionState.category)
        await message.reply("Введи категорию:", reply_markup=cancel_keyboard)
    except ValueError:
        await message.reply("Некорректная сумма. Введи число:", reply_markup=cancel_keyboard)


@router.message(TransactionState.category, F.text)
async def process_category(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    await state.update_data(category=message.text)
    await state.set_state(TransactionState.description)
    await message.reply("Введи описание (необязательно):", reply_markup=cancel_keyboard)


@router.message(TransactionState.description, F.text)
async def process_description(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    await state.update_data(description=message.text)
    data = await state.get_data()
    add_transaction(
        message.from_user.id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        data["type"],
        data["category"],
        data["amount"],
        data["description"],
    )
    await message.reply(f"Транзакция добавлена: {data['type']} - {data['amount']} - {data['category']}",
                        reply_markup=main_keyboard)
    await state.clear()


@router.message(F.text == "Отчет")
async def report_handler(message: types.Message, state: FSMContext):
    await state.set_state(ReportState.start_date)
    await message.reply("Введи начальную дату для отчета в формате ГГГГ-ММ-ДД (или 'Отмена'):",
                        reply_markup=cancel_keyboard)


@router.message(ReportState.start_date, F.text)
async def process_report_start_date(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    try:
        start_date = datetime.strptime(message.text, "%Y-%m-%d").strftime("%Y-%m-%d %H:%M:%S")
        await state.update_data(start_date=start_date)
        await state.set_state(ReportState.end_date)
        await message.reply("Введи конечную дату для отчета в формате ГГГГ-ММ-ДД (или 'Отмена'):",
                            reply_markup=cancel_keyboard)
    except ValueError:
        await message.reply("Некорректный формат даты. Используй ГГГГ-ММ-ДД (или 'Отмена'):",
                            reply_markup=cancel_keyboard)


@router.message(ReportState.end_date, F.text)
async def process_report_end_date(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    try:
        end_date = datetime.strptime(message.text, "%Y-%m-%d").strftime("%Y-%m-%d %H:%M:%S")
        data = await state.get_data()
        start_date = data["start_date"]

        transactions = get_transactions(message.from_user.id, start_date, end_date)
        if not transactions:
            await message.reply("Нет транзакций за указанный период.", reply_markup=main_keyboard)
            await state.clear()
            return

        income = sum(t[3] for t in transactions if t[1] == "income")
        expense = sum(t[3] for t in transactions if t[1] == "expense")

        report_text = f"Отчет за период с {start_date[:10]} по {end_date[:10]}:\n"
        report_text += f"Доходы: {income}\nРасходы: {expense}\n\n"
        report_text += "Последние транзакции:\n"
        for date, type, category, amount, description in transactions[:5]:
            report_text += f"- {date[:10]}: {type} - {category} - {amount} - {description}\n"

        goal = get_user_goal(message.from_user.id)
        if goal:
            goal_amount, goal_description = goal
            report_text += f"\nТвоя цель: {goal_description} ({goal_amount})\n"

        if expense > income:
            report_text += "\nРекомендация: Твои расходы превышают доходы. Попробуй составить бюджет."
        if income == 0:
            report_text += "\nРекомендация: У тебя нет доходов. Начни зарабатывать"
        else:
            if (expense / income) > 0.5:
                report_text += "\nРекомендация: Попробуй уменьшить свои расходы!"
            else:
                report_text += "\nРекомендация: продолжай в том же духе"

        await message.reply(report_text, reply_markup=main_keyboard)
        await state.clear()

    except ValueError:
        await message.reply("Некорректный формат даты. Используй ГГГГ-ММ-ДД (или 'Отмена'):",
                            reply_markup=cancel_keyboard)


@router.message(F.text == "Отмена")
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    logging.info("Cancelling state %r", current_state)
    await state.clear()
    await message.reply("Действие отменено.", reply_markup=main_keyboard)


@router.message(F.text == "Добавить напоминание")
async def add_reminder_handler(message: types.Message, state: FSMContext):
    await state.set_state(ReminderState.time)
    await message.reply(
        "Введи время для напоминания в формате ГГГГ-ММ-ДД ЧЧ:ММ или укажите относительное время (например, 'через 2 часа'):",
        reply_markup=cancel_keyboard)


@router.message(ReminderState.time, F.text)
async def process_reminder_time(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    try:
        reminder_time_str = message.text
        match_relative = re.match(r"через\s+(\d+)\s+(час[а-я]+|минут[а-я]+)", reminder_time_str, re.IGNORECASE)
        if match_relative:
            amount = int(match_relative.group(1))
            unit = match_relative.group(2).lower()
            if "час" in unit:
                reminder_time = datetime.now() + timedelta(hours=amount)
            elif "минут" in unit:
                reminder_time = datetime.now() + timedelta(minutes=amount)
            else:
                raise ValueError("Некорректный формат времени.")
            await state.update_data(time=reminder_time.strftime("%Y-%m-%d %H:%M:%S"))
            await state.set_state(ReminderState.text)
            await message.reply("Теперь введи текст напоминания:", reply_markup=cancel_keyboard)
            return
        reminder_time = datetime.strptime(reminder_time_str, "%Y-%m-%d %H:%M")
        await state.update_data(time=reminder_time.strftime("%Y-%m-%d %H:%M:%S"))
        await state.set_state(ReminderState.text)
        await message.reply("Теперь введи текст напоминания:", reply_markup=cancel_keyboard)
    except ValueError as e:
        await message.reply(
            f"Некорректный формат времени.  Пожалуйста, используйте ГГГГ-ММ-ДД ЧЧ:ММ, укажите относительное время (например, 'через 2 часа'). Ошибка: {e}",
            reply_markup=cancel_keyboard)


@router.message(ReminderState.text, F.text)
async def process_reminder_text(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    await state.update_data(text=message.text)
    data = await state.get_data()
    add_reminder(message.from_user.id, data["time"], data["text"])
    await message.reply(f"Напоминание добавлено: {data['text']}", reply_markup=main_keyboard)
    await state.clear()


@router.message(F.text == "Напоминания")
async def list_reminders_handler(message: types.Message):
    reminders = get_reminders(message.from_user.id)
    if not reminders:
        await message.reply("Нет активных напоминаний.", reply_markup=main_keyboard)
        return
    text = "Ваши напоминания:\n"
    for id, reminder_time, reminder_text in reminders:
        text += f"- {reminder_time}: {reminder_text}\n"
    await message.reply(text, reply_markup=main_keyboard)


@router.message(F.text == "Удалить напоминание")
async def delete_reminder_handler(message: types.Message, state: FSMContext):
    reminders = get_reminders(message.from_user.id)
    if not reminders:
        await message.reply("Нет напоминаний для удаления.", reply_markup=main_keyboard)
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{reminder_time} - {reminder_text}", callback_data=f"delete_reminder:{id}")]
        for id, reminder_time, reminder_text in reminders
    ])
    await message.reply("Выберите напоминание для удаления:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("delete_reminder:"))
async def process_delete_reminder(callback_query: types.CallbackQuery):
    try:
        reminder_id = int(callback_query.data.split(":")[1])
        delete_reminder(reminder_id, callback_query.from_user.id)
        await callback_query.message.edit_reply_markup(reply_markup=None)
        await callback_query.answer("Напоминание удалено.", show_alert=True)
        await callback_query.message.answer("Напоминание удалено.", reply_markup=main_keyboard)
    except Exception as e:
        logging.exception("Ошибка при удалении напоминания:")
        await callback_query.answer(f"Ошибка при удалении напоминания: {e}", show_alert=True)


@router.message(F.text == "Установить цель")
async def set_goal_handler(message: types.Message, state: FSMContext):
    await state.set_state(GoalState.amount)
    await message.reply("Введи сумму цели (или 'Отмена'):", reply_markup=cancel_keyboard)


@router.message(GoalState.amount, F.text)
async def process_goal_amount(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    try:
        amount = float(message.text)
        await state.update_data(amount=amount)
        await state.set_state(GoalState.description)
        await message.reply("Введи описание цели (или 'Отмена'):", reply_markup=cancel_keyboard)
    except ValueError:
        await message.reply("Некорректная сумма. Используй число (или 'Отмена'):", reply_markup=cancel_keyboard)


@router.message(GoalState.description, F.text)
async def process_goal_description(message: types.Message, state: FSMContext):
    if message.text == "Отмена":
        await cancel_handler(message, state)
        return
    description = message.text
    data = await state.get_data()
    amount = data["amount"]
    set_user_goal(message.from_user.id, amount, description)
    await message.reply(f"Цель установлена: {description} ({amount})", reply_markup=main_keyboard)
    await state.clear()


async def send_reminders(bot: Bot):
    while True:
        now = datetime.now()
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id, user_id, reminder_time, text
                FROM reminders
                WHERE reminder_time <= ?
            """, (now.strftime("%Y-%m-%d %H:%M:%S"),))
            reminders_to_send = cursor.fetchall()
            for id, user_id, reminder_time, text in reminders_to_send:
                try:
                    await bot.send_message(user_id, f"Напоминание: {text}")
                    cursor.execute("""
                        DELETE FROM reminders WHERE id = ?
                    """, (id,))
                    conn.commit()
                except Exception as e:
                    logging.exception(f"Ошибка при отправке напоминания {id}: {e}")
        except Exception as e:
            logging.exception("Ошибка при выборке напоминаний:")
        finally:
            conn.close()
        await asyncio.sleep(60)


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Начало работы"),
    ]
    await bot.set_my_commands(commands)


async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    await set_commands(bot)
    create_tables()
    asyncio.create_task(send_reminders(bot))
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
