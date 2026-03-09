import os
import sys
import json
import shutil
import subprocess
import logging
import signal
import psutil
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

        # Используем абсолютные пути
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.bots_folder = os.path.join(self.base_dir, "running_bots")

        # Создаем папку для ботов
        os.makedirs(self.bots_folder, exist_ok=True)

        self.app = Application.builder().token(self.token).build()

        # Регистрация обработчиков
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("bots", self.list_bots))
        self.app.add_handler(CommandHandler("stop", self.stop_bot))
        self.app.add_handler(CommandHandler("restart", self.restart_bot))
        self.app.add_handler(CommandHandler("logs", self.view_logs))
        self.app.add_handler(CommandHandler("kill", self.kill_bot))  # Принудительное завершение
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        self.app.add_handler(MessageHandler(filters.Document.ALL, self.handle_env_file))

        # Загружаем список запущенных ботов
        self.running_bots = self.load_running_bots()

        # Проверяем реальное состояние ботов при запуске
        self.check_bots_status()

        logger.info(f"Менеджер ботов запущен! Базовая папка: {self.base_dir}")
        logger.info(f"Папка с ботами: {self.bots_folder}")

    def load_running_bots(self):
        """Загрузить список запущенных ботов"""
        bots_file = os.path.join(self.bots_folder, "bots.json")
        if os.path.exists(bots_file):
            try:
                with open(bots_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def save_running_bots(self):
        """Сохранить список запущенных ботов"""
        bots_file = os.path.join(self.bots_folder, "bots.json")
        with open(bots_file, 'w', encoding='utf-8') as f:
            json.dump(self.running_bots, f, ensure_ascii=False, indent=2)

    def check_bots_status(self):
        """Проверить реальное состояние процессов ботов"""
        for bot_id, bot_info in list(self.running_bots.items()):
            if 'pid' in bot_info and bot_info['pid']:
                if not self.is_process_running(bot_info['pid']):
                    logger.warning(f"Бот {bot_id} с PID {bot_info['pid']} не работает, обновляю статус")
                    bot_info['status'] = 'stopped'
                    bot_info['pid'] = None
        self.save_running_bots()

    def is_process_running(self, pid):
        """Проверить, запущен ли процесс"""
        try:
            process = psutil.Process(pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

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
        # Обновляем статусы перед показом
        self.check_bots_status()

        running = len([b for b in self.running_bots.values() if b.get('status') == 'running'])
        stopped = len([b for b in self.running_bots.values() if b.get('status') == 'stopped'])

        text = (
            "🤖 <b>Менеджер ботов для городов</b>\n\n"
            f"📊 Всего ботов: {len(self.running_bots)}\n"
            f"🟢 Активных: {running}\n"
            f"🔴 Остановленных: {stopped}\n"
            f"📁 Папка: {self.bots_folder}\n\n"
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
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()

        # Проверяем наличие обязательных полей
        required_fields = ['TOKEN', 'CHANNEL_ID']
        missing = [f for f in required_fields if f not in env_vars]

        if missing:
            await update.message.reply_text(f"❌ В .env файле отсутствуют: {', '.join(missing)}")
            return

        # Получаем имя бота из токена (используем первые 8 символов токена)
        bot_token = env_vars['TOKEN']
        bot_id = bot_token.split(':')[0][-8:]  # Берем последние 8 символов ID

        # Создаем папку для нового бота
        bot_folder = os.path.join(self.bots_folder, f"bot_{bot_id}")
        os.makedirs(bot_folder, exist_ok=True)

        # Копируем файлы бота из текущей папки
        template_files = ['admin_panel.py', 'database.py', 'main.py', 'config.py']
        missing_templates = []

        for file_name in template_files:
            src_path = os.path.join(self.base_dir, file_name)
            dst_path = os.path.join(bot_folder, file_name)

            if os.path.exists(src_path):
                shutil.copy2(src_path, dst_path)
                logger.info(f"Скопирован {file_name} в {bot_folder}")
            else:
                missing_templates.append(file_name)

        if missing_templates:
            await update.message.reply_text(f"❌ Отсутствуют файлы шаблона: {', '.join(missing_templates)}")
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
        success, pid_or_error = self.start_bot_process(bot_folder, bot_id)

        # Сохраняем информацию о боте
        self.running_bots[bot_id] = {
            'id': bot_id,
            'folder': bot_folder,
            'token': bot_token[:20] + '...',  # Маскируем токен
            'status': 'running' if success else 'error',
            'pid': pid_or_error if success else None,
            'created_at': datetime.now().isoformat(),
            'env': {k: v for k, v in env_vars.items() if k != 'TOKEN'}
        }

        self.save_running_bots()

        if success:
            await update.message.reply_text(
                f"✅ Бот успешно создан и запущен!\n\n"
                f"📁 Папка: {bot_folder}\n"
                f"🆔 ID бота: {bot_id}\n"
                f"📊 Статус: 🟢 Работает (PID: {pid_or_error})\n\n"
                f"Используйте /bots для просмотра всех ботов"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Бот создан, но не запустился!\n\n"
                f"📁 Папка: {bot_folder}\n"
                f"🆔 ID бота: {bot_id}\n"
                f"❌ Ошибка: {pid_or_error}\n\n"
                f"Попробуйте запустить вручную или проверьте логи"
            )

    def start_bot_process(self, folder, bot_id):
        """Запустить процесс бота"""
        try:
            # Определяем путь к python
            python_path = sys.executable

            # Путь к main.py
            main_py = os.path.join(folder, 'main.py')

            if not os.path.exists(main_py):
                return False, f"main.py не найден в {folder}"

            # Создаем или очищаем лог-файл
            log_file = os.path.join(folder, 'bot.log')

            # Запускаем main.py в отдельном процессе
            if os.name == 'nt':  # Windows
                process = subprocess.Popen(
                    [python_path, main_py],
                    cwd=folder,
                    stdout=open(log_file, 'a'),
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:  # Linux/Mac
                process = subprocess.Popen(
                    [python_path, main_py],
                    cwd=folder,
                    stdout=open(log_file, 'a'),
                    stderr=subprocess.STDOUT,
                    start_new_session=True
                )

            # Даем время на запуск
            import time
            time.sleep(2)

            # Проверяем, запустился ли процесс
            if process.poll() is None:
                logger.info(f"Бот {bot_id} запущен с PID {process.pid}")
                return True, process.pid
            else:
                # Процесс сразу завершился - читаем ошибку
                with open(log_file, 'r') as f:
                    error = f.read()[-500:]  # Последние 500 символов
                return False, f"Процесс завершился сразу. Ошибка: {error}"

        except Exception as e:
            logger.error(f"Ошибка запуска бота {bot_id}: {e}")
            return False, str(e)

    def stop_bot_process(self, bot_id):
        """Остановить процесс бота"""
        bot_info = self.running_bots.get(bot_id)
        if not bot_info or 'pid' not in bot_info or not bot_info['pid']:
            return False, "PID не найден"

        try:
            pid = bot_info['pid']

            if os.name == 'nt':  # Windows
                result = subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                                        capture_output=True, text=True)
                success = result.returncode == 0
            else:  # Linux/Mac
                try:
                    os.kill(pid, signal.SIGTERM)
                    success = True
                except ProcessLookupError:
                    success = False

            if success:
                logger.info(f"Бот {bot_id} остановлен")
                return True, "Остановлен"
            else:
                return False, "Не удалось остановить"

        except Exception as e:
            logger.error(f"Ошибка остановки бота {bot_id}: {e}")
            return False, str(e)

    async def list_bots(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список ботов"""
        query = update.callback_query
        if query:
            await query.answer()

        # Обновляем статусы
        self.check_bots_status()

        if not self.running_bots:
            text = "📋 Нет запущенных ботов"
        else:
            text = "📋 <b>Список ботов:</b>\n\n"
            for bot_id, bot_info in self.running_bots.items():
                status_emoji = "🟢" if bot_info.get('status') == 'running' else "🔴"
                pid_info = f" (PID: {bot_info['pid']})" if bot_info.get('pid') else ""
                text += f"{status_emoji} <b>Бот {bot_id}</b>{pid_info}\n"
                text += f"   📁 {os.path.basename(bot_info['folder'])}\n"
                text += f"   📅 {bot_info['created_at'][:16]}\n\n"

        # Создаем клавиатуру с кнопками для каждого бота
        keyboard = []
        for bot_id in self.running_bots.keys():
            keyboard.append([
                InlineKeyboardButton(f"🤖 {bot_id}", callback_data=f"bot_menu_{bot_id}")
            ])

        keyboard.append([InlineKeyboardButton("🔄 Обновить", callback_data="list_bots")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="main_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def bot_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id):
        """Меню конкретного бота"""
        query = update.callback_query

        if bot_id not in self.running_bots:
            await query.message.edit_text("❌ Бот не найден")
            return

        bot_info = self.running_bots[bot_id]
        status_emoji = "🟢" if bot_info.get('status') == 'running' else "🔴"

        text = (
            f"🤖 <b>Управление ботом {bot_id}</b>\n\n"
            f"Статус: {status_emoji} {bot_info.get('status', 'unknown')}\n"
            f"PID: {bot_info.get('pid', 'Нет')}\n"
            f"Папка: {os.path.basename(bot_info['folder'])}\n"
            f"Создан: {bot_info['created_at'][:16]}\n"
        )

        keyboard = [
            [InlineKeyboardButton("🔄 Перезапустить", callback_data=f"restart_bot_{bot_id}")],
            [InlineKeyboardButton("⏹ Остановить", callback_data=f"stop_bot_{bot_id}")],
            [InlineKeyboardButton("🔪 Принудительно убить", callback_data=f"kill_bot_{bot_id}")],
            [InlineKeyboardButton("📋 Логи", callback_data=f"logs_bot_{bot_id}")],
            [InlineKeyboardButton("🗑 Удалить", callback_data=f"delete_bot_{bot_id}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="list_bots")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def stop_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Остановить бота"""
        # Обработка из команды
        if update.message and context.args:
            user_id = update.effective_user.id
            if not self.is_admin(user_id):
                await update.message.reply_text("❌ У вас нет доступа!")
                return

            bot_id = context.args[0]

            if bot_id not in self.running_bots:
                await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
                return

            success, message = self.stop_bot_process(bot_id)

            if success:
                self.running_bots[bot_id]['status'] = 'stopped'
                self.running_bots[bot_id]['pid'] = None
                self.save_running_bots()
                await update.message.reply_text(f"✅ Бот {bot_id} остановлен")
            else:
                await update.message.reply_text(f"❌ Не удалось остановить бота: {message}")

        # Обработка из кнопки
        elif update.callback_query:
            query = update.callback_query
            data = query.data
            bot_id = data.replace('stop_bot_', '')

            await query.answer()

            success, message = self.stop_bot_process(bot_id)

            if success:
                self.running_bots[bot_id]['status'] = 'stopped'
                self.running_bots[bot_id]['pid'] = None
                self.save_running_bots()
                await query.message.edit_text(f"✅ Бот {bot_id} остановлен")
            else:
                await query.message.edit_text(f"❌ Не удалось остановить бота: {message}")

    async def kill_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Принудительно убить процесс бота"""
        # Обработка из команды
        if update.message and context.args:
            user_id = update.effective_user.id
            if not self.is_admin(user_id):
                await update.message.reply_text("❌ У вас нет доступа!")
                return

            bot_id = context.args[0]

            if bot_id not in self.running_bots:
                await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
                return

            bot_info = self.running_bots[bot_id]
            if 'pid' not in bot_info or not bot_info['pid']:
                await update.message.reply_text(f"❌ У бота нет PID")
                return

            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/F', '/PID', str(bot_info['pid'])], check=True)
                else:
                    os.kill(bot_info['pid'], signal.SIGKILL)

                self.running_bots[bot_id]['status'] = 'stopped'
                self.running_bots[bot_id]['pid'] = None
                self.save_running_bots()
                await update.message.reply_text(f"✅ Бот {bot_id} убит")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")

        # Обработка из кнопки
        elif update.callback_query:
            query = update.callback_query
            data = query.data
            bot_id = data.replace('kill_bot_', '')

            await query.answer()

            bot_info = self.running_bots.get(bot_id)
            if not bot_info or not bot_info.get('pid'):
                await query.message.edit_text(f"❌ У бота нет PID")
                return

            try:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/F', '/PID', str(bot_info['pid'])], check=True)
                else:
                    os.kill(bot_info['pid'], signal.SIGKILL)

                self.running_bots[bot_id]['status'] = 'stopped'
                self.running_bots[bot_id]['pid'] = None
                self.save_running_bots()
                await query.message.edit_text(f"✅ Бот {bot_id} убит")
            except Exception as e:
                await query.message.edit_text(f"❌ Ошибка: {e}")

    async def restart_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Перезапустить бота"""
        # Обработка из команды
        if update.message and context.args:
            user_id = update.effective_user.id
            if not self.is_admin(user_id):
                await update.message.reply_text("❌ У вас нет доступа!")
                return

            bot_id = context.args[0]

            if bot_id not in self.running_bots:
                await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
                return

            await self.perform_restart(update, context, bot_id)

        # Обработка из кнопки
        elif update.callback_query:
            query = update.callback_query
            data = query.data
            bot_id = data.replace('restart_bot_', '')

            await query.answer()
            await self.perform_restart(update, context, bot_id)

    async def perform_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id):
        """Выполнить перезапуск бота"""
        bot_info = self.running_bots[bot_id]

        # Останавливаем
        self.stop_bot_process(bot_id)

        # Запускаем заново
        success, pid_or_error = self.start_bot_process(bot_info['folder'], bot_id)

        if success:
            bot_info['status'] = 'running'
            bot_info['pid'] = pid_or_error
            self.save_running_bots()

            if update.message:
                await update.message.reply_text(f"✅ Бот {bot_id} перезапущен (PID: {pid_or_error})")
            else:
                await update.callback_query.message.edit_text(f"✅ Бот {bot_id} перезапущен (PID: {pid_or_error})")
        else:
            bot_info['status'] = 'error'
            bot_info['pid'] = None
            self.save_running_bots()

            if update.message:
                await update.message.reply_text(f"❌ Не удалось перезапустить бота: {pid_or_error}")
            else:
                await update.callback_query.message.edit_text(f"❌ Не удалось перезапустить бота: {pid_or_error}")

    async def view_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр логов бота"""
        # Обработка из команды
        if update.message and context.args:
            user_id = update.effective_user.id
            if not self.is_admin(user_id):
                await update.message.reply_text("❌ У вас нет доступа!")
                return

            bot_id = context.args[0]
            lines = int(context.args[1]) if len(context.args) > 1 else 50

            if bot_id not in self.running_bots:
                await update.message.reply_text(f"❌ Бот с ID {bot_id} не найден")
                return

            await self.show_logs(update, context, bot_id, lines)

        # Обработка из кнопки
        elif update.callback_query:
            query = update.callback_query
            data = query.data
            bot_id = data.replace('logs_bot_', '')

            await query.answer()
            await self.show_logs(update, context, bot_id, 50)

    async def show_logs(self, update: Update, context: ContextTypes.DEFAULT_TYPE, bot_id, lines=50):
        """Показать логи бота"""
        bot_info = self.running_bots.get(bot_id)
        if not bot_info:
            if update.message:
                await update.message.reply_text("❌ Бот не найден")
            else:
                await update.callback_query.message.edit_text("❌ Бот не найден")
            return

        log_file = os.path.join(bot_info['folder'], 'bot.log')

        if not os.path.exists(log_file):
            if update.message:
                await update.message.reply_text("📝 Лог-файл еще не создан")
            else:
                await update.callback_query.message.edit_text("📝 Лог-файл еще не создан")
            return

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_logs = f.readlines()
                logs = all_logs[-lines:]

            log_text = f"📋 <b>Последние {len(logs)} строк лога бота {bot_id}:</b>\n\n"
            log_text += "<code>" + "".join(logs) + "</code>"

            # Telegram ограничение на длину сообщения
            if len(log_text) > 4000:
                log_text = log_text[:4000] + "...\n(сообщение обрезано)"

            if update.message:
                await update.message.reply_text(log_text, parse_mode='HTML')
            else:
                await update.callback_query.message.edit_text(log_text, parse_mode='HTML')

        except Exception as e:
            error_msg = f"❌ Ошибка чтения лога: {e}"
            if update.message:
                await update.message.reply_text(error_msg)
            else:
                await update.callback_query.message.edit_text(error_msg)

    async def delete_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Удалить бота"""
        query = update.callback_query
        data = query.data
        bot_id = data.replace('delete_bot_', '')

        await query.answer()

        if bot_id not in self.running_bots:
            await query.message.edit_text("❌ Бот не найден")
            return

        bot_info = self.running_bots[bot_id]

        # Останавливаем процесс если запущен
        if bot_info.get('status') == 'running' and bot_info.get('pid'):
            self.stop_bot_process(bot_id)

        # Удаляем папку
        import shutil
        try:
            shutil.rmtree(bot_info['folder'])
            logger.info(f"Папка бота {bot_id} удалена")
        except Exception as e:
            logger.error(f"Ошибка удаления папки бота {bot_id}: {e}")

        # Удаляем из списка
        del self.running_bots[bot_id]
        self.save_running_bots()

        await query.message.edit_text(f"✅ Бот {bot_id} удален")

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать статистику"""
        query = update.callback_query
        await query.answer()

        self.check_bots_status()

        total = len(self.running_bots)
        running = len([b for b in self.running_bots.values() if b.get('status') == 'running'])
        stopped = len([b for b in self.running_bots.values() if b.get('status') == 'stopped'])

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
            f"📁 Папка с ботами: {self.bots_folder}\n"
            f"📂 Базовая папка: {self.base_dir}"
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
        errors = []

        for bot_id, bot_info in self.running_bots.items():
            # Останавливаем
            self.stop_bot_process(bot_id)

            # Запускаем заново
            success, pid_or_error = self.start_bot_process(bot_info['folder'], bot_id)

            if success:
                bot_info['status'] = 'running'
                bot_info['pid'] = pid_or_error
                restarted += 1
            else:
                bot_info['status'] = 'error'
                bot_info['pid'] = None
                failed += 1
                errors.append(f"{bot_id}: {pid_or_error}")

        self.save_running_bots()

        result_text = f"✅ Перезапуск завершен!\n🟢 Успешно: {restarted}\n🔴 Ошибок: {failed}"

        if errors:
            result_text += "\n\n❌ Ошибки:\n" + "\n".join(errors[:5])

        await query.message.edit_text(result_text)

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
        elif data.startswith("bot_menu_"):
            bot_id = data.replace("bot_menu_", "")
            await self.bot_menu(update, context, bot_id)
        elif data.startswith("stop_bot_"):
            await self.stop_bot(update, context)
        elif data.startswith("restart_bot_"):
            await self.restart_bot(update, context)
        elif data.startswith("kill_bot_"):
            await self.kill_bot(update, context)
        elif data.startswith("logs_bot_"):
            await self.view_logs(update, context)
        elif data.startswith("delete_bot_"):
            await self.delete_bot(update, context)

    def run(self):
        """Запуск менеджера"""
        self.app.run_polling()


if __name__ == "__main__":
    # Убеждаемся, что psutil установлен
    try:
        import psutil
    except ImportError:
        print("Устанавливаем psutil...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil"])
        import psutil

    manager = BotManager()
    manager.run()