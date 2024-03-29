import telebot
from telebot import types
import requests
import logging

from logging.handlers import RotatingFileHandler

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

log_file_handler = RotatingFileHandler('debug_logs.txt', maxBytes=10*1024*1024, backupCount=5)
log_file_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_file_handler.setFormatter(formatter)
logging.getLogger('').addHandler(log_file_handler)


logging.basicConfig(level=logging.INFO)
BOT_TOKEN = ''
bot = telebot.TeleBot(BOT_TOKEN)

YANDEX_TOKEN = ''
FOLDER_ID = ''
user_choices = {}

@bot.callback_query_handler(func=lambda call: call.data == 'debug')
def send_debug_logs(call):
    try:
        with open('debug_logs.txt', 'rb') as log_file:
            bot.send_document(call.message.chat.id, log_file)
    except Exception as e:
        logging.error(f"Ошибка при отправке файла с логами: {e}")
        bot.answer_callback_query(call.id, "Произошла ошибка при отправке файла с отладкой.")

def ask_gpt(prompt):
    logging.info(f"Sending prompt to GPT: {prompt}")  # Логирование запроса
    headers = {
        'Authorization': f'Bearer {YANDEX_TOKEN}',
        'Content-Type': 'application/json'
    }
    data = {
        "modelUri": f"gpt://{FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.6,
            "maxTokens": 20
        },
        "messages": [
            {
                "role": "user",
                "text": prompt
            }
        ]
    }
    response = requests.post("https://llm.api.cloud.yandex.net/foundationModels/v1/completion", headers=headers, json=data)
    if response.status_code == 200:
        result = response.json()["result"]["alternatives"][0]["message"]["text"]
        logging.info(f"Received GPT response: {result}")  # Логирование ответа
        return result
    else:
        logging.error(f'Invalid response from GPT: {response.status_code}, {response.text}')  # Логирование ошибки
        raise RuntimeError(f'Invalid response received: code: {response.status_code}, message: {response.text}')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = "Привет, {}! Я бот, который создаёт истории с помощью нейрости. Мы будем писать историю поочередно. Я начну, а ты продолжишь. Напиши /new_story, чтобы начать новую историю. А когда ты закончишь, напиши /end.".format(message.from_user.first_name)
    bot.send_message(message.chat.id, welcome_text)

@bot.message_handler(commands=['new_story'])
def new_story(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    genres = ['Детектив', 'Сказка', 'Роман']
    for genre in genres:
        button = types.InlineKeyboardButton(genre, callback_data='genre_{}'.format(genre))
        markup.add(button)
    bot.send_message(message.chat.id, "Выбери жанр для новой истории:", reply_markup=markup)
    user_choices[message.from_user.id] = {}  # Сброс/инициализация выбора пользователя

@bot.callback_query_handler(func=lambda call: call.data.startswith('genre_'))
def handle_genre_selection(call):
    genre = call.data.split('_')[1]
    user_choices[call.from_user.id]['genre'] = genre
    bot.answer_callback_query(call.id, f"Жанр {genre} выбран.")
    send_character_options(call.message)


def get_contextual_prompt(story, user_input, max_length=300):
    """
    Формирует подстроку, включающую конец истории и последний ввод пользователя,
    чтобы отправить в GPT для генерации продолжения.
    max_length - максимальное количество символов для подстроки.
    """
    combined_text = f"{story} {user_input}".strip()
    # Если общая длина не превышает максимум, возвращаем все как есть
    if len(combined_text) <= max_length:
        return combined_text
    # Иначе возвращаем последние max_length символов
    return combined_text[-max_length:]


@bot.message_handler(func=lambda message: not message.text.startswith('/'))
def handle_text_input(message):
    user_id = message.from_user.id
    if user_id in user_choices and user_choices[user_id].get('in_story_mode', False):
        user_input = message.text
        # Получаем контекст из истории и последнего ввода пользователя
        prompt = get_contextual_prompt(user_choices[user_id]['story'], user_input)

        total_prompt = "Дополни историю: " + prompt
        # Подсчет токенов для запроса
        tokens_for_request = count_tokens_for_text(YANDEX_TOKEN, FOLDER_ID, total_prompt)

        continuation = ask_gpt(total_prompt)
        # Подсчет токенов для ответа
        tokens_for_response = count_tokens_for_text(YANDEX_TOKEN, FOLDER_ID, continuation)

        # Добавляем только сгенерированное продолжение к полной истории
        user_choices[user_id]['story'] += f" {continuation}"

        # Обновляем общее количество использованных токенов для пользователя
        user_choices[user_id]['tokens_used'] = user_choices[user_id].get('tokens_used', 0) + tokens_for_request + tokens_for_response

        bot.send_message(message.chat.id, continuation)
        # Выводим информацию о количестве использованных токенов

    elif user_id in user_choices and 'setting' in user_choices[user_id] and not user_choices[user_id].get('in_story_mode', False):
        # Записываем дополнительную информацию
        user_choices[user_id]['additional_info'] = message.text
        bot.send_message(message.chat.id, "Записал твои детали. Напиши /begin, когда будешь готов начать историю.")
    else:
        bot.send_message(message.chat.id, "Напиши /new_story, чтобы начать выбор параметров для истории.")


def save_additional_info(user_id, info):
    if user_id in user_choices:
        user_choices[user_id]['additional_info'] = info
def send_character_options(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    characters = ['Маугли', 'Золушка', 'Барби', 'Роналду']
    for character in characters:
        button = types.InlineKeyboardButton(character, callback_data='character_{}'.format(character))
        markup.add(button)
    bot.send_message(message.chat.id, "Выбери главного героя:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('character_'))
def handle_character_selection(call):
    character = call.data.split('_')[1]
    user_choices[call.from_user.id]['character'] = character
    bot.answer_callback_query(call.id, f"Персонаж {character} выбран.")
    send_setting_options(call.message)

def send_setting_options(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    settings = ['Страна Лилипутов', 'Страна чудес', 'Олимпийские игры']
    for setting in settings:
        button = types.InlineKeyboardButton(setting, callback_data='setting_{}'.format(setting))
        markup.add(button)
    bot.send_message(message.chat.id, "Выбери сеттинг для истории:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('setting_'))
def handle_setting_selection(call):
    setting = call.data.split('_')[1]
    user_choices[call.from_user.id]['setting'] = setting
    bot.answer_callback_query(call.id, f"Сеттинг {setting} выбран.")
    genre = user_choices[call.from_user.id].get('genre', 'неизвестный жанр')  # Получаем сохраненный жанр
    hero = user_choices[call.from_user.id].get('character', 'неизвестный character')  # Получаем сохраненный жанр
    bot.send_message(call.message.chat.id, f"Ты выбрал сеттинг: {setting}, жанр: {genre}, герой: {hero}. Если ты хочешь, чтобы мы узнали ещё какую-то информацию, напиши её сейчас. Или ты можешь сразу перейти к истории, написав /begin.")


@bot.message_handler(commands=['begin'])
def begin_story(message):
    user_id = message.from_user.id
    if user_id in user_choices and 'genre' in user_choices[user_id] and 'character' in user_choices[
        user_id] and 'setting' in user_choices[user_id]:
        additional_info = user_choices[user_id].get('additional_info', '')
        prompt = f"Расскажи историю в жанре {user_choices[user_id]['genre']} с {user_choices[user_id]['character']} в {user_choices[user_id]['setting']}. А так же {additional_info}"

        # Подсчет токенов для запроса
        tokens_for_request = count_tokens_for_text(YANDEX_TOKEN, FOLDER_ID, prompt)

        story_beginning = ask_gpt(prompt)

        # Подсчет токенов для ответа
        tokens_for_response = count_tokens_for_text(YANDEX_TOKEN, FOLDER_ID, story_beginning)

        # Обновляем общее количество использованных токенов для пользователя
        user_choices[user_id]['tokens_used'] = user_choices[user_id].get('tokens_used',
                                                                         0) + tokens_for_request + tokens_for_response

        user_choices[user_id]['story'] = story_beginning
        user_choices[user_id]['in_story_mode'] = True  # Переводим пользователя в режим истории

        bot.send_message(message.chat.id, story_beginning)

    else:
        bot.send_message(message.chat.id, "Сначала выбери все параметры для истории с помощью /new_story.")

@bot.callback_query_handler(func=lambda call: call.data == 'all_tokens')
def show_all_tokens(call):
    user_id = call.from_user.id
    if user_id in user_choices and 'tokens_used' in user_choices[user_id]:
        tokens_used = user_choices[user_id]['tokens_used']
        bot.answer_callback_query(call.id, f"Использовано токенов: {tokens_used}")
    else:
        bot.answer_callback_query(call.id, "Информация о токенах не найдена.")

@bot.message_handler(commands=['end'])
def end_story(message):
    user_id = message.from_user.id
    if user_id in user_choices:
        prompt = get_contextual_prompt("Закончи историю в двух-трех продлежниях: ",user_choices[user_id]['story'])

        total_prompt = prompt
        # Подсчет токенов для запроса
        tokens_for_request = count_tokens_for_text(YANDEX_TOKEN, FOLDER_ID, total_prompt)

        continuation = ask_gpt(total_prompt)
        # Подсчет токенов для ответа
        tokens_for_response = count_tokens_for_text(YANDEX_TOKEN, FOLDER_ID, continuation)

        # Добавляем только сгенерированное продолжение к полной истории
        user_choices[user_id]['story'] += f" {continuation}"

        # Обновляем общее количество использованных токенов для пользователя
        user_choices[user_id]['tokens_used'] = user_choices[user_id].get('tokens_used', 0) + tokens_for_request + tokens_for_response

        bot.send_message(message.chat.id, continuation)

        # Создание разметки и кнопок
        markup = types.InlineKeyboardMarkup()
        new_story_button = types.InlineKeyboardButton("Новая история", callback_data='new_story')
        all_tokens_button = types.InlineKeyboardButton("Все токены", callback_data='all_tokens')
        whole_story_button = types.InlineKeyboardButton("Целая история", callback_data='whole_story')
        debug_button = types.InlineKeyboardButton("Отладка", callback_data='debug')

        # Добавление кнопок в разметку
        markup.add(new_story_button, all_tokens_button, whole_story_button, debug_button)

        # Отправка сообщения с текстом истории и кнопками
        bot.send_message(message.chat.id, "История завершена. Спасибо за участие!",
                         reply_markup=markup)

        #user_choices.pop(user_id, None)
    else:
        bot.send_message(message.chat.id, "Ты не начал историю. Используй /begin для старта.")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == 'new_story':
        new_story(call.message)
    elif call.data.startswith('genre_'):
        handle_genre_selection(call)
    elif call.data.startswith('character_'):
        handle_character_selection(call)
    elif call.data.startswith('setting_'):
        handle_setting_selection(call)
    elif call.data == 'all_tokens':
        show_all_tokens(call)
    elif call.data == 'whole_story':
        whole(call)

def whole(call):
    user_id = call.from_user.id
    if user_id in user_choices and 'story' in user_choices[user_id]:
        bot.send_message(call.message.chat.id, user_choices[user_id]['story'])
    else:
        bot.send_message(call.message.chat.id, "Не нашли:(")
def count_tokens_for_text(token, folder_id, text):
    """
    Подсчитывает количество токенов в данном тексте.

    :param token: Токен для аутентификации в API Yandex.
    :param folder_id: ID папки в Yandex Cloud.
    :param text: Текст, для которого нужно подсчитать количество токенов.
    :return: Количество токенов.
    """
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    data = {
        "modelUri": f"gpt://{folder_id}/yandexgpt/latest",
        "messages": [
            {
                "role": "user",
                "text": text
            }
        ]
    }

    response = requests.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/tokenizeCompletion",
        headers=headers,
        json=data
    )
    if response.status_code == 200:
        return len(response.json()["tokens"])
    else:
        print(f'Error calculating tokens: {response.status_code}, {response.text}')
        return None


if __name__ == '__main__':
    bot.infinity_polling()