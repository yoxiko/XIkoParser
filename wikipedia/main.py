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
import aiohttp
from bs4 import BeautifulSoup
import json
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "токен"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

wiki_wiki = wikipediaapi.Wikipedia(
    user_agent='WikipediaTelegramBot/1.0',
    language='ru',
    extract_format=wikipediaapi.ExtractFormat.WIKI
)

user_sessions = {}
user_articles = {}

QUERY_PATTERNS = {
    'definition': r'(что такое|определение|что значит)\s+([^?]+)',
    'how_to': r'(как|как сделать|способ|метод)\s+([^?]+)',
    'why': r'(почему|зачем|для чего)\s+([^?]+)',
    'compare': r'(сравнение|разница между|отличие)\s+([^?]+)',
    'history': r'(история|происхождение|возникновение)\s+([^?]+)',
    'examples': r'(примеры|пример|код)\s+([^?]+)'
}

def escape_markdown(text):
    if not text:
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def analyze_query_patterns(query):
    patterns_found = []
    
    for pattern_type, pattern_regex in QUERY_PATTERNS.items():
        matches = re.findall(pattern_regex, query.lower())
        if matches:
            for match in matches:
                if len(match) == 2:
                    patterns_found.append({
                        'type': pattern_type,
                        'keyword': match[0],
                        'subject': match[1].strip()
                    })

    if not patterns_found:
        patterns_found.append({
            'type': 'general',
            'subject': query.strip()
        })
    
    return patterns_found

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

async def search_github(query):
    try:
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc"
        headers = {'Accept': 'application/vnd.github.v3+json'}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []
                    for repo in data.get('items', [])[:3]:
                        description = repo.get('description', 'Нет описания')
                        if description is None:
                            description = 'Нет описания'
                        results.append({
                            'title': repo['full_name'],
                            'description': description[:200] + "..." if len(description) > 200 else description,
                            'url': repo['html_url'],
                            'stars': repo['stargazers_count'],
                            'language': repo.get('language', 'Не указан'),
                            'source': 'GitHub',
                            'content': f"**{repo['full_name']}**\n\n⭐ **Звезды:** {repo['stargazers_count']}\n🖥 **Язык:** {repo.get('language', 'Не указан')}\n\n{description}\n\n🔗 [Открыть на GitHub]({repo['html_url']})"
                        })
                    return results
                return []
    except Exception as e:
        logger.error(f"Error searching GitHub: {e}")
        return []

async def search_stackoverflow(query):
    try:
        url = f"https://api.stackexchange.com/2.3/search/advanced"
        params = {
            'order': 'desc',
            'sort': 'relevance',
            'q': query,
            'site': 'stackoverflow',
            'pagesize': 3
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    results = []
                    for item in data.get('items', [])[:3]:
                        title = escape_markdown(item['title'])
                        description = f"Ответов: {item['answer_count']}, Просмотров: {item['view_count']}"
                        
                        content = f"**{title}**\n\n**Рейтинг:** {item['score']}\n**Ответов:** {item['answer_count']}\n**Просмотров:** {item['view_count']}\n🏷 **Теги:** {', '.join(item['tags'][:5])}\n\n🔗 [Читать на StackOverflow]({item['link']})"
                        
                        results.append({
                            'title': title,
                            'description': description,
                            'url': item['link'],
                            'score': item['score'],
                            'tags': ', '.join(item['tags'][:5]),
                            'source': 'StackOverflow',
                            'content': content
                        })
                    return results
                return []
    except Exception as e:
        logger.error(f"Error searching StackOverflow: {e}")
        return []

async def search_habr(query):
    try:
        url = f"https://habr.com/ru/search/"
        params = {'q': query}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    results = []
                    
                    articles = soup.find_all('article', class_='tm-articles-list__item')[:3]
                    for article in articles:
                        title_elem = article.find('h2')
                        if title_elem:
                            title_link = title_elem.find('a')
                            if title_link:
                                title = escape_markdown(title_link.text.strip())
                                link = "https://habr.com" + title_link['href']
                            
                                description_elem = article.find(['div', 'p'], class_=re.compile('article-formatted-body'))
                                description = ""
                                if description_elem:
                                    description = escape_markdown(description_elem.text.strip()[:200] + "...")
                                else:
                                    description = "Читать на Habr"
                                
                                content = f"**{title}**\n\n{description}\n\n🔗 [Читать на Habr]({link})"
                                
                                results.append({
                                    'title': title,
                                    'description': description,
                                    'url': link,
                                    'source': 'Habr',
                                    'content': content
                                })
                    
                    return results
                return []
    except Exception as e:
        logger.error(f"Error searching Habr: {e}")
        return []

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
            'url': page.fullurl,
            'source': 'Wikipedia'
        }
    
    except Exception as e:
        logger.error(f"Error getting wiki page: {e}")
        return None

async def send_wiki_page(message: Message, page_data, chunk_index=0):
    total_chunks = len(page_data['chunks'])

    message_text = f"*{page_data['title']}* | {page_data['source']}\n\n"
    message_text += page_data['chunks'][chunk_index]
    message_text += f"\n\nСтраница {chunk_index + 1} из {total_chunks}"
    message_text += f"\n[Открыть оригинал]({page_data['url']})"
    
    if len(message_text) > 4096:
        excess = len(message_text) - 4096
        content = page_data['chunks'][chunk_index]
        content = content[:len(content) - excess - 100] + "*Текст сокращен*"
        message_text = f"*{page_data['title']}* | {page_data['source']}\n\n{content}"
        message_text += f"\n\nСтраница {chunk_index + 1} из {total_chunks}"
        message_text += f"\n[Открыть оригинал]({page_data['url']})"
    
    keyboard = InlineKeyboardBuilder()
    
    if chunk_index > 0:
        keyboard.button(text="◀ Предыдущая", callback_data=f"prev_{chunk_index}")
    if chunk_index < total_chunks - 1:
        keyboard.button(text="Следующая ▶", callback_data=f"next_{chunk_index}")
    
    keyboard.adjust(2)
    
    try:
        if chunk_index == 0 and page_data.get('image_url'):
            caption = f"*{page_data['title']}* | {page_data['source']}\n\n"
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

async def send_source_results(message: Message, results, source_name):
    if not results:
        return
    
    for result in results:
        safe_title = escape_markdown(result['title'])
        safe_description = escape_markdown(result['description'])
        
        result_text = f"**{safe_title}** | {result['source']}\n\n"
        result_text += f"{safe_description}\n\n"
        
        if result['source'] == 'GitHub':
            result_text += f" Звезды: {result['stars']} |  Язык: {result['language']}\n"
        elif result['source'] == 'StackOverflow':
            result_text += f" Рейтинг: {result['score']} |  Теги: {result['tags']}\n"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(text=f" Открыть в {result['source']}", url=result['url'])
        
        if 'content' in result:
            article_id = str(uuid.uuid4())[:8]
            user_articles[article_id] = {
                'content': result['content'],
                'title': result['title'],
                'source': result['source'],
                'url': result['url']
            }
            keyboard.button(text=" Читать тут", callback_data=f"read_{article_id}")
        
        keyboard.adjust(1)
        
        try:
            await message.answer(
                text=result_text,
                reply_markup=keyboard.as_markup(),
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            logger.error(f"Error sending result: {e}")
            await message.answer(
                text=result_text.replace('*', '').replace('_', ''),
                reply_markup=keyboard.as_markup()
            )

async def send_article_content(message: Message, article_id, chunk_index=0):
    if article_id not in user_articles:
        await message.answer("Статья не найдена.")
        return
    
    article = user_articles[article_id]
    content_chunks = split_text(article['content'], 3000)
    total_chunks = len(content_chunks)
    
    if chunk_index >= total_chunks:
        chunk_index = total_chunks - 1
    
    message_text = content_chunks[chunk_index]
    message_text += f"\n\n*Страница {chunk_index + 1} из {total_chunks}*"
    
    keyboard = InlineKeyboardBuilder()
    
    if chunk_index > 0:
        keyboard.button(text="◀ Назад", callback_data=f"art_prev_{article_id}_{chunk_index}")
    if chunk_index < total_chunks - 1:
        keyboard.button(text="Далее ▶", callback_data=f"art_next_{article_id}_{chunk_index}")
    
    keyboard.button(text="🔗 Открыть оригинал", url=article['url'])
    keyboard.adjust(2, 1)
    
    try:
        await message.answer(
            text=message_text,
            reply_markup=keyboard.as_markup(),
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logger.error(f"Error sending article content: {e}")
        await message.answer(
            text=message_text.replace('*', '').replace('_', ''),
            reply_markup=keyboard.as_markup()
        )

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        " *Бот-поискови*\n\n"
        "Отправьте мне запрос, и я найду информацию в:\n"
        "•  Wikipedia\n"
        "•  GitHub\n"
        "•  StackOverflow\n"
        "•  Habr\n\n"
        "Я автоматически анализирую структуру вашего запроса и ищу наиболее релевантную информацию!\n\n"
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
    
    patterns = analyze_query_patterns(query)
    
    analysis_msg = " *Анализ запроса:*\n"
    for pattern in patterns:
        safe_subject = escape_markdown(pattern['subject'])
        analysis_msg += f"• **{pattern['type']}**: {safe_subject}\n"
    
    try:
        await message.answer(analysis_msg, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error sending analysis: {e}")
        await message.answer(analysis_msg.replace('*', '').replace('_', ''))
    
    search_message = await message.answer(" Поиск информации по всем источникам...")
    
    main_subject = patterns[0]['subject']
    
    wiki_task = asyncio.create_task(asyncio.to_thread(get_wiki_page, main_subject))
    github_task = asyncio.create_task(search_github(main_subject))
    stackoverflow_task = asyncio.create_task(search_stackoverflow(main_subject))
    habr_task = asyncio.create_task(search_habr(main_subject))
    
    wiki_data, github_results, stackoverflow_results, habr_results = await asyncio.gather(
        wiki_task, github_task, stackoverflow_task, habr_task,
        return_exceptions=True
    )
    
    if isinstance(wiki_data, Exception):
        logger.error(f"Error in wiki search: {wiki_data}")
        wiki_data = None
    if isinstance(github_results, Exception):
        logger.error(f"Error in github search: {github_results}")
        github_results = []
    if isinstance(stackoverflow_results, Exception):
        logger.error(f"Error in stackoverflow search: {stackoverflow_results}")
        stackoverflow_results = []
    if isinstance(habr_results, Exception):
        logger.error(f"Error in habr search: {habr_results}")
        habr_results = []
    
    await search_message.delete()
    
    all_results = []
    
    if wiki_data:
        user_sessions[user_id] = {
            'page_data': wiki_data,
            'current_chunk': 0
        }
        await send_wiki_page(message, wiki_data, 0)
        all_results.append(wiki_data)
    
    if github_results:
        await send_source_results(message, github_results, "GitHub")
        all_results.extend(github_results)
    
    if stackoverflow_results:
        await send_source_results(message, stackoverflow_results, "StackOverflow")
        all_results.extend(stackoverflow_results)
    
    if habr_results:
        await send_source_results(message, habr_results, "Habr")
        all_results.extend(habr_results)
    
    if not all_results:
        await message.answer(" По вашему запросу ничего не найдено. Попробуйте другой запрос.")

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
    message_text = f"*{page_data['title']}* | {page_data['source']}\n\n"
    message_text += page_data['chunks'][new_chunk]
    message_text += f"\n\nСтраница {new_chunk + 1} из {total_chunks}"
    message_text += f"\n[Открыть оригинал]({page_data['url']})"
    
    if len(message_text) > 4096:
        excess = len(message_text) - 4096
        content = page_data['chunks'][new_chunk]
        content = content[:len(content) - excess - 100] + "*Текст сокращен*"
        message_text = f"*{page_data['title']}* | {page_data['source']}\n\n{content}"
        message_text += f"\n\nСтраница {new_chunk + 1} из {total_chunks}"
        message_text += f"\n[Открыть оригинал]({page_data['url']})"
    
    keyboard = InlineKeyboardBuilder()
    if new_chunk > 0:
        keyboard.button(text="◀ Предыдущая", callback_data=f"prev_{new_chunk}")
    if new_chunk < total_chunks - 1:
        keyboard.button(text="Следующая ▶", callback_data=f"next_{new_chunk}")
    
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

@dp.callback_query(F.data.startswith("read_"))
async def handle_read_article(callback: CallbackQuery):
    article_id = callback.data.replace("read_", "")
    await callback.answer()
    await send_article_content(callback.message, article_id, 0)

@dp.callback_query(F.data.startswith("art_prev_") | F.data.startswith("art_next_"))
async def handle_article_navigation(callback: CallbackQuery):
    try:
        data_parts = callback.data.split("_")
        direction = data_parts[1] 
        article_id = data_parts[2]
        current_chunk = int(data_parts[3])
        
        if direction == "prev":
            new_chunk = current_chunk - 1
        else:
            new_chunk = current_chunk + 1
        
        await callback.answer()
        await send_article_content(callback.message, article_id, new_chunk)
    except Exception as e:
        logger.error(f"Error in article navigation: {e}")
        await callback.answer("Ошибка навигации", show_alert=True)

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        " *Помощь по боту*\n\n"
        "Я могу найти информацию в нескольких источниках:\n"
        "•  *Wikipedia* - энциклопедические статьи\n"
        "•  *GitHub* - репозитории и код\n"
        "•  *StackOverflow* - вопросы и ответы по программированию\n"
        "•  *Habr* - технические статьи и tutorials\n\n"
        "*Как использовать:*\n"
        "Просто отправьте мне любой запрос, и я автоматически:\n"
        "1.  Проанализирую структуру запроса\n"
        "2.  Найду информацию во всех источниках\n"
        "3.  Покажу наиболее релевантные результаты\n\n"
        "*Примеры запросов:*\n"
        "• \"что такое искусственный интеллект\"\n"
        "• \"как создать телеграм бот на Python\"\n"
        "• \"пример кода для парсинга сайта\"\n"
        "• \"разница между list и tuple в Python\"\n\n"
        "*Команды:*\n"
        "/start - начать работу\n"
        "/help - показать эту справку",
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message()
async def handle_other_messages(message: Message):
    await message.answer(
        "Я понимаю только текстовые сообщения. "
        "Просто напишите, что хотите найти, или используйте /help для справки."
    )

async def main():
    logger.info("Бот запускается...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())