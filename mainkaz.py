import os
import sys
import json
import shutil
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from dotenv import load_dotenv

# Загрузка конфига менеджера
load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


class BotManager:
    def __init__(self):
        self.token = os.getenv("MANAGER_TOKEN")
        self.admin_ids = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x]
        self.bots_folder = "running_bots"

        # Создаем папку для ботов
        os.makedirs(self.bots_folder, exist_ok=True)

        self.app = Application.builder().token(self.token).build()

        # Регистрация обработчиков
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("bots", self.list_bots))
        self.app.add_handler(CommandHandler("stop", self.stop_bot))
        self.app.add_handler(CommandHandler("restart", self.restart_bot))
        self.app.add_handler(CommandHandler("logs", self.view_logs))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.handle_env_file))

        # Загружаем список запущенных ботов
        self.running_bots = self.load_running_bots()

        logger.info("Менеджер ботов запущен!")

    def load_running_bots(self):
        """Загрузить список запущенных ботов"""
        bots_file = os.path.join(self.bots_folder, "bots.json")
        if os.path.exists(bots_file):
            with open(bots_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def save_running_bots(self):
        """Сохранить список запущенных ботов"""
        bots_file = os.path.join(self.bots_folder, "bots.json")
        with open(bots_file, 'w', encoding='utf-8') as f:
            json.dump(self.running_bots, f, ensure_ascii=False, indent=2)

    def is_admin(self, user_id):
        """Проверка на админа"""
        return user_id in self.admin_ids

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Старт менеджера"""
        user_id = update.effective_user.id

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа к этому боту!")
            return

        await self.show_main_menu(update, context)

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать главное меню"""
        text = (
            "🤖 <b>Менеджер ботов для городов</b>\n\n"
            f"📊 Всего ботов: {len(self.running_bots)}\n"
            f"🟢 Активных: {len([b for b in self.running_bots.values() if b['status'] == 'running'])}\n"
            f"🔴 Остановленных: {len([b for b in self.running_bots.values() if b['status'] == 'stopped'])}\n\n"
            "📥 <b>Как создать нового бота:</b>\n"
            "1. Получите токен у @BotFather\n"
            "2. Отправьте мне .env файл с настройками\n\n"
            "📋 <b>Формат .env файла:</b>\n"
            "<code>TOKEN=токен_бота\n"
            "CHANNEL_ID=ID_канала\n"
            "ADMIN_IDS=ваш_telegram_id\n"
            "ADMIN_PASSWORD=admin123</code>"
        )

        keyboard = [
            [InlineKeyboardButton("📋 Список ботов", callback_data="list_bots")],
            [InlineKeyboardButton("📊 Статистика", callback_data="stats")],
            [InlineKeyboardButton("🔄 Перезапустить всех", callback_data="restart_all")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if update.callback_query:
            await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def handle_env_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка .env файла для создания нового бота"""
        user_id = update.effective_user.id

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа!")
            return

        document = update.message.document

        if not document.file_name.endswith('.env'):
            await update.message.reply_text("❌ Пожалуйста, отправьте файл с расширением .env")
            return

        # Скачиваем файл
        file = await document.get_file()
        env_content = await file.download_as_bytearray()
        env_content = env_content.decode('utf-8')

        # Парсим .env файл
        env_vars = {}
        for line in env_content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                env_vars[key] = value

        # Проверяем наличие обязательных полей
        required_fields = ['TOKEN', 'CHANNEL_ID']
        missing = [f for f in required_fields if f not in env_vars]

        if missing:
            await update.message.reply_text(f"❌ В .env файле отсутствуют: {', '.join(missing)}")
            return

        # Получаем имя бота из токена
        bot_token = env_vars['TOKEN']
        bot_name = bot_token.split(':')[0]  # Используем ID бота как имя

        # Создаем папку для нового бота
        bot_folder = os.path.join(self.bots_folder, f"bot_{bot_name}")
        os.makedirs(bot_folder, exist_ok=True)

        # Копируем файлы бота
        template_files = ['admin_panel.py', 'database.py', 'main.py', 'config.py']
        for file_name in template_files:
            if os.path.exists(file_name):
                shutil.copy(file_name, os.path.join(bot_folder, file_name))
            else:
                await update.message.reply_text(f"❌ Файл {file_name} не найден в шаблоне!")
                return

        # Сохраняем .env файл
        env_path = os.path.join(bot_folder, '.env')
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(env_content)

        # Создаем папку для карточек
        cards_path = os.path.join(bot_folder, 'data')
        os.makedirs(cards_path, exist_ok=True)

        # Создаем стандартные папки редкостей
        rarities = ['Обычный', 'Редкий', 'Мифик', 'Легендарный', 'Секрет']
        for rarity in rarities:
            os.makedirs(os.path.join(cards_path, rarity), exist_ok=True)

        # Запускаем бота
        process = self.start_bot_process(bot_folder, bot_name)

        # Сохраняем информацию о боте
        self.running_bots[bot_name] = {
            'name': bot_name,
            'folder': bot_folder,
            'token': bot_token,
            'status': 'running',
            'pid': process.pid if process else None,
            'created_at': datetime.now().isoformat(),
            'env': {k: v for k, v in env_vars.items() if k != 'TOKEN'}  # Не храним токен в открытом виде
        }

        self.save_running_bots()

        await update.message.reply_text(
            f"✅ Бот успешно создан и запущен!\n\n"
            f"📁 Папка: {bot_folder}\n"
            f"🆔 ID бота: {bot_name}\n"
            f"📊 Статус: 🟢 Работает\n\n"
            f"Используйте /bots для просмотра всех ботов"
        )

    def start_bot_process(self, folder, bot_name):
        """Запустить процесс бота"""
        try:
            # Определяем путь к python
            python_path = sys.executable

            # Запускаем main.py в отдельном процессе
            process = subprocess.Popen(
                [python_path, 'main.py'],
                cwd=folder,
                stdout=open(os.path.join(folder, 'bot.log'), 'a'),
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
            )

            logger.info(f"Бот {bot_name} запущен с PID {process.pid}")
            return process
        except Exception as e:
            logger.error(f"Ошибка запуска бота {bot_name}: {e}")
            return None

    def stop_bot_process(self, bot_name):
        """Остановить процесс бота"""
        bot_info = self.running_bots.get(bot_name)
        if not bot_info or 'pid' not in bot_info:
            return False

        try:
            if os.name == 'nt':  # Windows
                subprocess.run(['taskkill', '/F', '/PID', str(bot_info['pid'])], capture_output=True)
            else:  # Linux/Mac
                os.kill(bot_info['pid'], 9)

            logger.info(f"Бот {bot_name} остановлен")
            return True
        except Exception as e:
            logger.error(f"Ошибка остановки бота {bot_name}: {e}")
            return False

    async def list_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список ботов"""
        query = update.callback_query
        if query:
            await query.answer()

        if not self.running_bots:
            text = "📋 Нет запущенных ботов"
        else:
            text = "📋 <b>Список ботов:</b>\n\n"
            for bot_id, bot_info in self.running_bots.items():
                status_emoji = "🟢" if bot_info['status'] == 'running' else "🔴"
                text += f"{status_emoji} <b>{bot_info.get('name', bot_id)}</b>\n"
                text += f"   📁 Папка: {bot_info['folder']}\n"
                text += f"   📊 Статус: {bot_info['status']}\n"
                text += f"   📅 Создан: {bot_info['created_at'][:16]}\n\n"

        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="list_bots")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Остановить бота по команде /stop <id>"""
        user_id = update.effective_user.id

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа!")
            return

        if not context.args:
            await update.message.reply_text("Использование: /stop <id_бота>")
            return

        bot_id = context.args[0]

        if bot_id not in self.running_bots:
            await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
            return

        if self.stop_bot_process(bot_id):
            self.running_bots[bot_id]['status'] = 'stopped'
            self.save_running_bots()
            await update.message.reply_text(f"✅ Бот {bot_id} остановлен")
        else:
            await update.message.reply_text(f"❌ Не удалось остановить бота {bot_id}")

    async def restart_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перезапустить бота"""
        user_id = update.effective_user.id

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа!")
            return

        if not context.args:
            await update.message.reply_text("Использование: /restart <id_бота>")
            return

        bot_id = context.args[0]

        if bot_id not in self.running_bots:
            await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
            return

        # Останавливаем
        self.stop_bot_process(bot_id)

        # Запускаем заново
        bot_info = self.running_bots[bot_id]
        process = self.start_bot_process(bot_info['folder'], bot_id)

        if process:
            bot_info['status'] = 'running'
            bot_info['pid'] = process.pid
            self.save_running_bots()
            await update.message.reply_text(f"✅ Бот {bot_id} перезапущен")
        else:
            bot_info['status'] = 'error'
            await update.message.reply_text(f"❌ Не удалось перезапустить бота {bot_id}")

    async def view_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр логов бота"""
        user_id = update.effective_user.id

        if not self.is_admin(user_id):
            await update.message.reply_text("❌ У вас нет доступа!")
            return

        if not context.args:
            await update.message.reply_text("Использование: /logs <id_бота> [строк]")
            return

        bot_id = context.args[0]
        lines = int(context.args[1]) if len(context.args) > 1 else 50

        if bot_id not in self.running_bots:
            await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
            return

        log_file = os.path.join(self.running_bots[bot_id]['folder'], 'bot.log')

        if not os.path.exists(log_file):
            await update.message.reply_text("📝 Лог-файл еще не создан")
            return

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                logs = f.readlines()[-lines:]

            log_text = f"📋 <b>Последние {len(logs)} строк лога бота {bot_id}:</b>\n\n"
            log_text += "<code>" + "".join(logs[-50:]) + "</code>"

            # Telegram ограничение на длину сообщения
            if len(log_text) > 4000:
                log_text = log_text[:4000] + "...\n(сообщение обрезано)"

            await update.message.reply_text(log_text, parse_mode='HTML')
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка чтения лога: {e}")

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать статистику"""
        query = update.callback_query
        await query.answer()

        total = len(self.running_bots)
        running = len([b for b in self.running_bots.values() if b['status'] == 'running'])
        stopped = len([b for b in self.running_bots.values() if b['status'] == 'stopped'])

        # Считаем общее дисковое пространство
        total_size = 0
        for bot in self.running_bots.values():
            folder = bot['folder']
            if os.path.exists(folder):
                for path in Path(folder).rglob('*'):
                    if path.is_file():
                        total_size += path.stat().st_size

        text = (
            "📊 <b>Статистика менеджера</b>\n\n"
            f"🤖 Всего ботов: {total}\n"
            f"🟢 Активных: {running}\n"
            f"🔴 Остановленных: {stopped}\n"
            f"💾 Занимаемое место: {total_size / 1024 / 1024:.2f} MB\n\n"
            f"📁 Папка с ботами: {self.bots_folder}"
        )

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def restart_all(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перезапустить всех ботов"""
        query = update.callback_query
        await query.answer()

        await query.message.edit_text("🔄 Перезапуск всех ботов...")

        restarted = 0
        failed = 0

        for bot_id, bot_info in self.running_bots.items():
            self.stop_bot_process(bot_id)
            process = self.start_bot_process(bot_info['folder'], bot_id)

            if process:
                bot_info['status'] = 'running'
                bot_info['pid'] = process.pid
                restarted += 1
            else:
                bot_info['status'] = 'error'
                failed += 1

        self.save_running_bots()

        await query.message.edit_text(
            f"✅ Перезапуск завершен!\n"
            f"🟢 Успешно: {restarted}\n"
            f"🔴 Ошибок: {failed}"
        )

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопок"""
        query = update.callback_query
        data = query.data

        await query.answer()

        user_id = query.from_user.id
        if not self.is_admin(user_id):
            await query.message.edit_text("❌ У вас нет доступа!")
            return

        if data == "main_menu":
            await self.show_main_menu(update, context)
        elif data == "list_bots":
            await self.list_bots(update, context)
        elif data == "stats":
            await self.show_stats(update, context)
        elif data == "restart_all":
            await self.restart_all(update, context)

    def run(self):
        """Запуск менеджера"""
        self.app.run_polling()


if __name__ == "__main__":
    manager = BotManager()
    manager.run()