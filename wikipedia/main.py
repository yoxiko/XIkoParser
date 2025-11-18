import wikipediaapi
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio
import requests
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = " токен  "

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

wiki_wiki = wikipediaapi.Wikipedia(
    user_agent='WikipediaTelegramBot/1.0',
    language='ru',
    extract_format=wikipediaapi.ExtractFormat.WIKI
)

user_sessions = {}

def format_wiki_text(text):
    text = re.sub(r'======(.+?)======', r'**\1**', text)
    text = re.sub(r'=====(.+?)=====', r'**\1**', text)
    text = re.sub(r'====(.+?)====', r'**\1**', text)
    text = re.sub(r'===(.+?)===', r'**\1**', text)
    text = re.sub(r'==(.+?)==', r'**\1**', text)
    text = re.sub(r"'''(.*?)'''", r'**\1**', text)
    text = re.sub(r"''(.*?)''", r'*\1*', text)
    text = re.sub(r'\[\[([^|\]]+)\|([^\]]+)\]\]', r'\2', text)
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    text = re.sub(r'{{.*?}}', '', text)
    text = re.sub(r'<.*?>', '', text)
    text = re.sub(r'^\*+', '•', text, flags=re.MULTILINE)
    text = re.sub(r' +', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    
    return text

def split_text(text, max_length=4000):
    if len(text) <= max_length:
        return [text]
    
    parts = []
    while text:
        if len(text) <= max_length:
            parts.append(text)
            break
        part = text[:max_length]
        last_newline = part.rfind('\n')
        if last_newline > 0:
            part = part[:last_newline]
        else:
            last_space = part.rfind(' ')
            if last_space > 0:
                part = part[:last_space]
        parts.append(part)
        text = text[len(part):].strip()
    return parts

def get_page_image(page_title):
    try:
        url = "https://ru.wikipedia.org/api/rest_v1/page/summary/" + page_title.replace(" ", "_")
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'thumbnail' in data and 'source' in data['thumbnail']:
                return data['thumbnail']['source']
        return None
    except Exception as e:
        logger.error(f"Error getting page image: {e}")
        return None

def get_wiki_page(query):
    try:
        page = wiki_wiki.page(query)
        if not page.exists():
            return None
        
        formatted_text = format_wiki_text(page.text)
        
        text_chunks = split_text(formatted_text, 3000)
        
        if len(text_chunks) > 10:
            text_chunks = text_chunks[:10]
            text_chunks[-1] += "\n\n*Текст сокращен*"
        
        image_url = get_page_image(page.title)
        
        return {
            'title': page.title,
            'chunks': text_chunks,
            'image_url': image_url,
            'url': page.fullurl
        }
    
    except Exception as e:
        logger.error(f"Error getting wiki page: {e}")
        return None

async def send_wiki_page(message: Message, page_data, chunk_index=0):
    total_chunks = len(page_data['chunks'])

    message_text = f"*{page_data['title']}*\n\n"
    message_text += page_data['chunks'][chunk_index]
    message_text += f"\n\nСтраница {chunk_index + 1} из {total_chunks}"
    message_text += f"\n[Открыть в Википедии]({page_data['url']})"
    
    if len(message_text) > 4096:
        excess = len(message_text) - 4096
        content = page_data['chunks'][chunk_index]
        content = content[:len(content) - excess - 100] + "*Текст сокращен*"
        message_text = f"*{page_data['title']}*\n\n{content}"
        message_text += f"\n\nСтраница {chunk_index + 1} из {total_chunks}"
        message_text += f"\n[Открыть в Википедии]({page_data['url']})"
    
    keyboard = InlineKeyboardBuilder()
    
    if chunk_index > 0:
        keyboard.button(text="Предыдущая", callback_data=f"prev_{chunk_index}")
    if chunk_index < total_chunks - 1:
        keyboard.button(text="Следующая", callback_data=f"next_{chunk_index}")
    
    keyboard.adjust(2)
    
    try:
        if chunk_index == 0 and page_data.get('image_url'):
            caption = f"*{page_data['title']}*\n\n"
            first_paragraph = page_data['chunks'][0].split('\n\n')[0]
            if len(first_paragraph) > 300:
                caption += first_paragraph[:300] + "..."
            else:
                caption += first_paragraph
            caption += f"\n\nСтраница 1 из {total_chunks}"
            
            await message.answer_photo(
                photo=page_data['image_url'],
                caption=caption,
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await message.answer(
                text=message_text,
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        await message.answer(
            text=message_text,
            reply_markup=keyboard.as_markup(),
            parse_mode=ParseMode.MARKDOWN
        )

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Отправьте мне запрос для поиска в Википедии.\n\n"
        "`by yoxiko`",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(F.text)
async def handle_text(message: Message):
    user_id = message.from_user.id
    query = message.text.strip()
    
    if len(query) < 2:
        await message.answer("Запрос слишком короткий. Попробуйте еще раз.")
        return
    
    search_message = await message.answer("Поиск в Википедии...")
    
    page_data = get_wiki_page(query)
    
    await search_message.delete()
    
    if not page_data:
        await message.answer("По вашему запросу ничего не найдено. Попробуйте другой запрос.")
        return
    
    user_sessions[user_id] = {
        'page_data': page_data,
        'current_chunk': 0
    }
    
    await send_wiki_page(message, page_data, 0)

@dp.callback_query(F.data.startswith("prev_") | F.data.startswith("next_"))
async def handle_navigation(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if user_id not in user_sessions:
        await callback.answer("Сессия истекла. Начните новый поиск.", show_alert=True)
        return
    
    session = user_sessions[user_id]
    page_data = session['page_data']
    current_chunk = session['current_chunk']
    
    if callback.data.startswith("prev_"):
        new_chunk = current_chunk - 1
    else:  
        new_chunk = current_chunk + 1
        
    if new_chunk < 0 or new_chunk >= len(page_data['chunks']):
        await callback.answer("Достигнут предел навигации.")
        return
    
    session['current_chunk'] = new_chunk
    
    total_chunks = len(page_data['chunks'])
    message_text = f"*{page_data['title']}*\n\n"
    message_text += page_data['chunks'][new_chunk]
    message_text += f"\n\nСтраница {new_chunk + 1} из {total_chunks}"
    message_text += f"\n[Открыть в Википедии]({page_data['url']})"
    
    if len(message_text) > 4096:
        excess = len(message_text) - 4096
        content = page_data['chunks'][new_chunk]
        content = content[:len(content) - excess - 100] + "*Текст сокращен*"
        message_text = f"*{page_data['title']}*\n\n{content}"
        message_text += f"\n\nСтраница {new_chunk + 1} из {total_chunks}"
        message_text += f"\n[Открыть в Википедии]({page_data['url']})"
    
    keyboard = InlineKeyboardBuilder()
    if new_chunk > 0:
        keyboard.button(text="Предыдущая", callback_data=f"prev_{new_chunk}")
    if new_chunk < total_chunks - 1:
        keyboard.button(text="Следующая", callback_data=f"next_{new_chunk}")
    
    keyboard.adjust(2)
    
    try:
        await callback.message.edit_text(
            text=message_text,
            reply_markup=keyboard.as_markup(),
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error editing message: {e}")
        await callback.answer("Ошибка при обновлении сообщения.", show_alert=True)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Помощь по боту\n\n"
        "Я могу найти информацию в Википедии по вашему запросу.\n\n"
        "Команды:\n"
        "/start - начать работу\n"
        "/help - показать эту справку\n\n"
        "Как использовать:\n"
        "Просто отправьте мне любой запрос, и я найду соответствующую статью в Википедии.",
        parse_mode=None  
    )

@dp.message()
async def handle_other_messages(message: Message):
    await message.answer(
        "Я понимаю только текстовые сообщения. "
        "Просто напишите, что хотите найти в Википедии, или используйте /help для справки."
    )

async def main():
    logger.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())