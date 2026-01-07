import asyncio
import logging
import requests
import os
from dotenv import load_dotenv

# Библиотеки для графиков
import matplotlib.pyplot as plt
import io

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

# --- Загрузка конфигурации ---
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
WEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")

if not TOKEN or not WEATHER_API_KEY:
    print("Ошибка: Не найдены ключи в файле .env")
    exit()

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- Хранилище данных ---
users = {}


# --- Состояния FSM ---
class ProfileStates(StatesGroup):
    weight = State()
    height = State()
    age = State()
    activity = State()
    city = State()


class FoodStates(StatesGroup):
    waiting_for_food_name = State()
    waiting_for_grams = State()


# --- Вспомогательные функции ---

def get_weather(city: str):
    url = f"http://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_API_KEY}&units=metric"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return data["main"]["temp"]
        return None
    except:
        return None


def get_food_info(product_name):
    url = f"https://world.openfoodfacts.org/cgi/search.pl?action=process&search_terms={product_name}&json=true"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            products = data.get('products', [])
            if products:
                first_product = products[0]
                name = first_product.get('product_name', 'Неизвестно')
                calories = first_product.get('nutriments', {}).get('energy-kcal_100g', 0)
                return name, calories
        return None
    except:
        return None


# --- Обработчики команд ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для трекинга воды и калорий.\n\n"
        "📋 **Меню:**\n"
        "/set_profile — Настройка профиля\n"
        "/log_water <мл> — Записать воду\n"
        "/log_food <продукт> — Записать еду\n"
        "/log_workout <тип> <мин> — Записать тренировку\n"
        "/check_progress — Посмотреть прогресс (+график)"
    )


# --- Настройка профиля ---
@dp.message(Command("set_profile"))
async def cmd_set_profile(message: types.Message, state: FSMContext):
    await message.answer("Введите ваш вес (в кг):")
    await state.set_state(ProfileStates.weight)


@dp.message(ProfileStates.weight)
async def process_weight(message: types.Message, state: FSMContext):
    try:
        await state.update_data(weight=float(message.text))
        await message.answer("Введите ваш рост (в см):")
        await state.set_state(ProfileStates.height)
    except ValueError:
        await message.answer("Введите число.")


@dp.message(ProfileStates.height)
async def process_height(message: types.Message, state: FSMContext):
    try:
        await state.update_data(height=float(message.text))
        await message.answer("Введите ваш возраст:")
        await state.set_state(ProfileStates.age)
    except ValueError:
        await message.answer("Введите целое число.")


@dp.message(ProfileStates.age)
async def process_age(message: types.Message, state: FSMContext):
    try:
        await state.update_data(age=int(message.text))
        await message.answer("Сколько минут активности у вас в день?")
        await state.set_state(ProfileStates.activity)
    except ValueError:
        await message.answer("Введите число.")


@dp.message(ProfileStates.activity)
async def process_activity(message: types.Message, state: FSMContext):
    try:
        await state.update_data(activity=int(message.text))
        await message.answer("В каком городе вы находитесь?")
        await state.set_state(ProfileStates.city)
    except ValueError:
        await message.answer("Введите число.")


@dp.message(ProfileStates.city)
async def process_city(message: types.Message, state: FSMContext):
    city = message.text
    data = await state.get_data()

    weight = data.get('weight')
    height = data.get('height')
    age = data.get('age')
    activity = data.get('activity')

    # Расчет воды
    water_goal = weight * 30 + (500 * (activity // 30))

    # Погода
    temp = get_weather(city)
    weather_msg = ""
    if temp and temp > 25:
        water_goal += 500
        weather_msg = f" (На улице {temp}°C, добавлено 500 мл воды)"

    # Расчет калорий (Формула Миффлина-Сан Жеора упрощенная)
    calorie_goal = (10 * weight) + (6.25 * height) - (5 * age) + 200  # Базовый метаболизм + минимум активности
    if activity > 30:
        calorie_goal += 200  # Доп калории за активность в профиле

    user_id = message.from_user.id
    users[user_id] = {
        "weight": weight, "height": height, "age": age,
        "activity": activity, "city": city,
        "water_goal": water_goal,
        "calorie_goal": calorie_goal,
        "logged_water": 0,
        "logged_calories": 0,
        "burned_calories": 0
    }

    await message.answer(f"Профиль сохранен! Цель: {water_goal:.0f} мл воды{weather_msg}, {calorie_goal:.0f} ккал.")
    await state.clear()


# --- Логирование Воды ---
@dp.message(Command("log_water"))
async def cmd_log_water(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Сначала настройте профиль через /set_profile")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Пример: /log_water 250")
        return

    try:
        amount = int(args[1])
        users[user_id]['logged_water'] += amount
        current = users[user_id]['logged_water']
        goal = users[user_id]['water_goal']
        left = max(0, goal - current)

        await message.answer(f"💧 Записано: {amount} мл.\nВсего: {current} / {goal} мл. (Осталось: {left} мл)")
    except ValueError:
        await message.answer("Введите число (в мл).")


# --- Логирование Еды ---
@dp.message(Command("log_food"))
async def cmd_log_food(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Сначала настройте профиль!")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Пример: /log_food банан")
        return

    food_name = args[1]
    info = get_food_info(food_name)

    if not info:
        await message.answer("Продукт не найден.")
        return

    name, kcal = info
    await state.update_data(food_name=name, kcal_100g=kcal)
    await message.answer(f"🍎 {name}: {kcal} ккал/100г. Сколько грамм?")
    await state.set_state(FoodStates.waiting_for_grams)


@dp.message(FoodStates.waiting_for_grams)
async def process_food_grams(message: types.Message, state: FSMContext):
    try:
        grams = float(message.text)
        data = await state.get_data()
        calories = (grams / 100) * data['kcal_100g']

        user_id = message.from_user.id
        users[user_id]['logged_calories'] += calories

        await message.answer(f"Записано: {calories:.1f} ккал.")
        await state.clear()
    except ValueError:
        await message.answer("Введите число.")


# --- Логирование Тренировок ---
@dp.message(Command("log_workout"))
async def cmd_log_workout(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Сначала настройте профиль!")
        return

    # Формат: /log_workout бег 30
    args = message.text.split()
    if len(args) < 3:
        await message.answer("Пример: /log_workout бег 30")
        return

    workout_type = args[1]
    try:
        minutes = int(args[2])

        # Простой расчет: 10 ккал в минуту (можно усложнить словарем типов)
        burned = minutes * 10

        # Доп вода: 200 мл за каждые 30 минут
        water_needed = (minutes // 30) * 200

        users[user_id]['burned_calories'] += burned
        users[user_id]['water_goal'] += water_needed  # Увеличиваем цель по воде

        await message.answer(
            f"🏃‍♂️ {workout_type} ({minutes} мин) — сожжено {burned} ккал.\n"
            f"Дополнительно выпейте {water_needed} мл воды."
        )
    except ValueError:
        await message.answer("Время указывайте числом.")


# --- Прогресс и Графики ---
@dp.message(Command("check_progress"))
async def cmd_check_progress(message: types.Message):
    user_id = message.from_user.id
    if user_id not in users:
        await message.answer("Профиль не найден.")
        return

    u = users[user_id]

    # Подготовка данных
    water_drunk = u['logged_water']
    water_goal = u['water_goal']
    water_rem = max(0, water_goal - water_drunk)

    cal_consumed = u['logged_calories']
    cal_burned = u['burned_calories']
    cal_goal = u['calorie_goal']
    cal_balance = cal_consumed - cal_burned  # Реальный баланс потребления

    # Текстовый отчет
    text = (
        f"📊 **Прогресс:**\n\n"
        f"💧 **Вода:**\n"
        f"- Выпито: {water_drunk} / {water_goal:.0f} мл\n"
        f"- Осталось: {water_rem:.0f} мл\n\n"
        f"🔥 **Калории:**\n"
        f"- Потреблено: {cal_consumed:.0f} ккал\n"
        f"- Сожжено: {cal_burned:.0f} ккал\n"
        f"- Баланс: {cal_balance:.0f} / {cal_goal:.0f} ккал"
    )

    await message.answer(text)

    # Генерация графиков
    # Создаем фигуру с двумя графиками (Subplots)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 5))

    # График воды
    ax1.bar(['Выпито', 'Осталось'], [water_drunk, water_rem], color=['blue', 'lightgray'])
    ax1.set_title('Вода (мл)')

    # График калорий
    # Сравниваем Потреблено vs Цель+Сожжено (чтобы было наглядно)
    ax2.bar(['Потреблено', 'Цель'], [cal_consumed, cal_goal + cal_burned], color=['orange', 'green'])
    ax2.set_title('Калории (ккал)')

    # Сохраняем в буфер памяти (не в файл)
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)

    # Отправляем фото
    photo = types.BufferedInputFile(buf.read(), filename="progress.png")
    await message.answer_photo(photo, caption="Графики вашего прогресса")

    # Закрываем график, чтобы память не текла
    plt.close(fig)

# Делаем подсказки для помощи пользователю
async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="/start", description="Начать работу"),
        BotCommand(command="/set_profile", description="Настроить профиль"),
        BotCommand(command="/log_food", description="Записать еду"),
        BotCommand(command="/log_water", description="Записать воду"),
        BotCommand(command="/log_workout", description="Записать тренировку"),
        BotCommand(command="/check_progress", description="Посмотреть прогресс(+график)")
    ]

    await bot.set_my_commands(commands, BotCommandScopeDefault())

async def main():
    print("Бот запущен...")
    await set_commands(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())