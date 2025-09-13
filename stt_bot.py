# -*- coding: utf-8 -*-
# transcribe_bot.py

import os
import asyncio
import logging
import time
from typing import Optional

# Библиотеки для работы с Telegram
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.constants import ChatAction

# Библиотеки для обработки аудио
import pydub
from pydub import AudioSegment
import speech_recognition as sr

# --- БАЗОВАЯ НАСТРОЙКА ---

# Вставь сюда токен своего бота, полученный от @BotFather
TELEGRAM_BOT_TOKEN = "token"

# Папка для временного хранения медиафайлов
TEMP_MEDIA_DIR = "temp_media"

# Настройка логирования для отладки
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- ОСНОВНАЯ ФУНКЦИЯ РАСПОЗНАВАНИЯ РЕЧИ ---
# Эта функция взята из твоего файла utils.py и немного адаптирована

async def transcribe_voice(file_path: str) -> Optional[str]:
    """
    Распознает речь из аудиофайла формата .wav с помощью Google Speech Recognition.
    Автоматически удаляет файл после обработки.
    """
    if not os.path.exists(file_path):
        logger.error(f"File not found for transcription: {file_path}")
        return "[Ошибка: Внутренняя ошибка, файл не найден]"

    logger.info(f"Начинаю распознавание файла: {file_path}")
    recognizer = sr.Recognizer()
    text = None
    
    try:
        # Используем to_thread для выполнения синхронной, блокирующей операции в асинхронном коде
        def recognize_sync():
            with sr.AudioFile(file_path) as source:
                audio_data = recognizer.record(source)
                # Распознаем речь, используя русский язык
                return recognizer.recognize_google(audio_data, language="ru-RU")

        text = await asyncio.to_thread(recognize_sync)
        logger.info(f"Успешно распознано: '{text}'")
        
    except sr.UnknownValueError:
        logger.warning("Google Speech Recognition не смогла распознать речь")
        text = "[Речь не распознана]"
    except sr.RequestError as e:
        logger.error(f"Ошибка запроса к сервису Google Speech Recognition: {e}")
        text = f"[Ошибка сервиса распознавания: {e}]"
    except Exception as e:
        logger.error(f"Произошла непредвиденная ошибка при обработке аудио: {e}", exc_info=True)
        text = "[Ошибка обработки аудио]"
    finally:
        # Гарантированно удаляем временный файл, даже если была ошибка
        try:
            os.remove(file_path)
            logger.debug(f"Временный файл удален: {file_path}")
        except OSError as e:
            logger.warning(f"Не удалось удалить временный файл {file_path}: {e}")
            
    return text


# --- ОБРАБОТЧИК ГОЛОСОВЫХ И ВИДЕОСООБЩЕНИЙ ---
# Логика из твоего handle_text_voice_video, но упрощенная только для медиа

async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает входящие голосовые и видеосообщения.
    """
    if not update.message:
        return

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    
    # Определяем, что пришло: голос или видео-кружок
    is_voice = update.message.voice is not None
    is_video_note = update.message.video_note is not None

    if not (is_voice or is_video_note):
        return

    # Отправляем уведомление пользователю, что мы начали работу
    status_message = await update.message.reply_text("🎙️ Получил, начинаю расшифровку...")
    
    temp_file_path = None # Путь к сконвертированному WAV файлу
    original_media_path = None # Путь к исходному oga/mp4 файлу

    try:
        # Создаем временную папку, если ее нет
        os.makedirs(TEMP_MEDIA_DIR, exist_ok=True)

        if is_voice:
            await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VOICE)
            media_file = await update.message.voice.get_file()
            base_name = f"voice_{user_id}_{int(time.time())}"
            original_media_path = os.path.join(TEMP_MEDIA_DIR, f"{base_name}.oga")
            temp_file_path = os.path.join(TEMP_MEDIA_DIR, f"{base_name}.wav")
            source_format = "ogg"
            
        elif is_video_note:
            await context.bot.send_chat_action(chat_id, ChatAction.RECORD_VIDEO)
            media_file = await update.message.video_note.get_file()
            base_name = f"vnote_{user_id}_{int(time.time())}"
            original_media_path = os.path.join(TEMP_MEDIA_DIR, f"{base_name}.mp4")
            temp_file_path = os.path.join(TEMP_MEDIA_DIR, f"{base_name}.wav")
            source_format = "mp4"

        # 1. Скачиваем файл
        await media_file.download_to_drive(original_media_path)
        logger.info(f"Файл скачан: {original_media_path}")

        # 2. Конвертируем в WAV с помощью pydub
        await status_message.edit_text("⏳ Конвертирую аудио...")
        
        def convert_sync():
             audio = AudioSegment.from_file(original_media_path, format=source_format)
             audio.export(temp_file_path, format="wav")

        await asyncio.to_thread(convert_sync)
        logger.info(f"Файл сконвертирован в {temp_file_path}")
        
    except Exception as e:
        logger.error(f"Ошибка на этапе скачивания или конвертации: {e}", exc_info=True)
        await status_message.edit_text("❌ Произошла ошибка при обработке файла.")
        return
    finally:
        # Удаляем исходный oga/mp4 файл, он больше не нужен
        if original_media_path and os.path.exists(original_media_path):
            os.remove(original_media_path)

    # 3. Распознаем речь из WAV файла
    await status_message.edit_text("🧠 Распознаю речь...")
    transcribed_text = await transcribe_voice(temp_file_path) # Функция сама удалит wav файл

    # 4. Отправляем результат
    if transcribed_text:
        await status_message.edit_text(f"\n\n{transcribed_text}", parse_mode='Markdown')
    else:
        # На случай если функция вернула None, хотя не должна
        await status_message.edit_text("Не удалось получить результат распознавания.")


# --- ФУНКЦИЯ ЗАПУСКА БОТА ---

def main():
    """Основная функция для запуска бота."""
    logger.info("Запуск бота...")
    
    if TELEGRAM_BOT_TOKEN == "ВАШ_ТЕЛЕГРАМ_ТОКЕН":
        logger.error("Ошибка: Вставьте ваш токен в переменную TELEGRAM_BOT_TOKEN!")
        return

    # Создаем приложение
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Добавляем обработчик для голосовых и видеосообщений
    # Фильтр `filters.VOICE | filters.VIDEO_NOTE` означает "или голосовое, или видео-кружок"
    application.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE, handle_media))

    # Запускаем бота в режиме опроса (polling)
    application.run_polling()


if __name__ == "__main__":
    main()
