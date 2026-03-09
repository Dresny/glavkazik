import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, CommandHandler
from database import Database
import html

logger = logging.getLogger(__name__)
db = Database()


class AdminPanel:
    def __init__(self, app, config):
        self.app = app
        self.config = config

        # Регистрация админских команд
        self.app.add_handler(CommandHandler("admin", self.admin_command))
        self.app.add_handler(CallbackQueryHandler(self.admin_button_handler, pattern="^admin_"))

        # Добавляем админов из конфига в БД
        admin_ids = getattr(self.config, 'ADMIN_IDS', [])
        if isinstance(admin_ids, list):
            for admin_id in admin_ids:
                try:
                    db.add_admin(admin_id, f"admin_{admin_id}")
                except Exception as e:
                    logger.error(f"Ошибка при добавлении админа {admin_id}: {e}")
        elif admin_ids:  # Если это одиночный ID
            try:
                db.add_admin(admin_ids, f"admin_{admin_ids}")
            except Exception as e:
                logger.error(f"Ошибка при добавлении админа {admin_ids}: {e}")

    async def check_admin(self, user_id: int) -> bool:
        """Проверка прав админа"""
        # Проверяем ID из конфига
        admin_ids = getattr(self.config, 'ADMIN_IDS', [])
        if isinstance(admin_ids, list) and user_id in admin_ids:
            return True
        elif admin_ids == user_id:  # Если одиночный ID
            return True

        # Проверяем БД
        return db.is_admin(user_id)

    async def show_cards_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления карточками"""
        query = update.callback_query
        await query.answer()

        # Получаем все редкости из БД
        rarities = db.get_all_rarities()

        text = "🃏 <b>Управление карточками</b>\n\n"
        text += "<b>Существующие редкости:</b>\n"

        for rarity in rarities:
            text += f"• {rarity['name']} - {rarity['price']} тенге (вес: {rarity['weight']}%)\n"

        keyboard = [
            [InlineKeyboardButton("📁 Посмотреть карточки", callback_data="admin_view_cards")],
            [InlineKeyboardButton("➕ Добавить карточку", callback_data="admin_add_card")],
            [InlineKeyboardButton("➕ Добавить редкость", callback_data="admin_add_rarity")],
            [InlineKeyboardButton("✏️ Изменить цену", callback_data="admin_edit_price")],
            [InlineKeyboardButton("📊 Изменить вес", callback_data="admin_edit_weight")],
            [InlineKeyboardButton("🗑 Удалить редкость", callback_data="admin_delete_rarity")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def view_cards(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Просмотр карточек в папках"""
        query = update.callback_query
        await query.answer()

        rarities = db.get_all_rarities()

        text = "📁 <b>Карточки в базе:</b>\n\n"

        import os
        for rarity in rarities:
            rarity_path = os.path.join(self.config.CARDS_PATH, rarity['name'])
            if os.path.exists(rarity_path):
                cards = [f for f in os.listdir(rarity_path)
                         if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
                text += f"<b>{rarity['name']}:</b> {len(cards)} карточек\n"
                if cards:
                    for card in cards[:5]:  # Показываем первые 5
                        text += f"  • {card}\n"
                    if len(cards) > 5:
                        text += f"  ... и еще {len(cards) - 5}\n"
                text += "\n"

        keyboard = [
            [InlineKeyboardButton("🗑 Удалить карточку", callback_data="admin_delete_card")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_cards")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def add_card_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на добавление карточки"""
        query = update.callback_query
        await query.answer()

        rarities = db.get_all_rarities()

        keyboard = []
        for rarity in rarities:
            keyboard.append([InlineKeyboardButton(
                f"{rarity['name']} ({rarity['price']} тенге)",
                callback_data=f"admin_select_rarity_{rarity['name']}"
            )])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_cards")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            "🖼 <b>Добавление карточки</b>\n\n"
            "Выберите редкость карточки, затем отправьте изображение.\n"
            "Название файла станет названием карточки."
        )

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def add_rarity_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на добавление новой редкости"""
        query = update.callback_query
        await query.answer()

        text = (
            "➕ <b>Добавление новой редкости</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>Название,Цена,Вес</code>\n\n"
            "Пример: <code>Эпический,200,5</code>\n\n"
            "Вес - это шанс выпадения в %\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_rarity_add'] = True

    async def edit_price_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на изменение цены редкости"""
        query = update.callback_query
        await query.answer()

        text = (
            "✏️ <b>Изменение цены редкости</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>Название редкости,Новая цена</code>\n\n"
            "Пример: <code>Обычный,20</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_price_edit'] = True

    async def edit_weight_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на изменение веса редкости"""
        query = update.callback_query
        await query.answer()

        text = (
            "📊 <b>Изменение веса редкости</b>\n\n"
            "Вес определяет шанс выпадения карточки.\n\n"
            "Отправьте данные в формате:\n"
            "<code>Название редкости,Новый вес</code>\n\n"
            "Пример: <code>Обычный,50</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_weight_edit'] = True

    async def delete_rarity_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на удаление редкости"""
        query = update.callback_query
        await query.answer()

        rarities = db.get_all_rarities()

        text = "🗑 <b>Удаление редкости</b>\n\nВыберите редкость для удаления:\n\n"

        keyboard = []
        for rarity in rarities:
            if rarity['name'] not in ["Обычный", "Редкий", "Мифик", "Легендарный", "Секрет"]:
                keyboard.append([InlineKeyboardButton(
                    f"{rarity['name']}",
                    callback_data=f"admin_delete_rarity_conf_{rarity['name']}"
                )])

        if not keyboard:
            text += "Нет пользовательских редкостей для удаления."
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_cards")])
        else:
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="admin_cards")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def delete_card_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на удаление карточки"""
        query = update.callback_query
        await query.answer()

        text = (
            "🗑 <b>Удаление карточки</b>\n\n"
            "Отправьте путь к карточке в формате:\n"
            "<code>Редкость/Название файла</code>\n\n"
            "Пример: <code>Обычный/card1.jpg</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_card_delete'] = True

    async def handle_card_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка загруженной карточки"""
        user_id = update.effective_user.id

        if not await self.check_admin(user_id):
            return

        if not context.user_data.get('awaiting_card_rarity'):
            return

        rarity = context.user_data['awaiting_card_rarity']
        photo = update.message.photo[-1]
        file = await photo.get_file()

        # Создаем папку если её нет
        import os
        rarity_path = os.path.join(self.config.CARDS_PATH, rarity)
        os.makedirs(rarity_path, exist_ok=True)

        # Получаем имя файла
        if update.message.caption:
            file_name = update.message.caption.strip()
            if not file_name.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                file_name += '.jpg'
        else:
            from datetime import datetime
            file_name = f"card_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"

        file_path = os.path.join(rarity_path, file_name)

        # Скачиваем файл
        await file.download_to_drive(file_path)

        await update.message.reply_text(
            f"✅ Карточка успешно добавлена!\n"
            f"Редкость: {rarity}\n"
            f"Файл: {file_name}"
        )

        context.user_data.pop('awaiting_card_rarity', None)

    async def admin_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда /admin для доступа к панели"""
        user_id = update.effective_user.id

        # Проверка пароля если указан
        if context.args and self.config.ADMIN_PASSWORD:
            if context.args[0] == self.config.ADMIN_PASSWORD:
                db.add_admin(user_id, update.effective_user.username)
                await update.message.reply_text("✅ Вы получили права администратора!")
                return await self.show_admin_menu(update, context)
            else:
                await update.message.reply_text("❌ Неверный пароль!")
                return

        # Проверка прав
        if not await self.check_admin(user_id):
            await update.message.reply_text("❌ У вас нет прав администратора!")
            return

        await self.show_admin_menu(update, context)

    async def show_admin_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                              message_id: int = None):
        """Показать меню админ-панели"""
        user = update.effective_user

        keyboard = [
            [InlineKeyboardButton("🃏 Управление карточками", callback_data="admin_cards")],
            [InlineKeyboardButton("💰 Управление балансом", callback_data="admin_balance")],  # Новая кнопка
            [InlineKeyboardButton("👤 Управление пользователями", callback_data="admin_users")],
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_mailing")],
            [InlineKeyboardButton("🚫 Заблокированные", callback_data="admin_blocked")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("⚙️ Админы", callback_data="admin_admins")],
            [InlineKeyboardButton("📥 Предложения карт", callback_data="admin_suggestions")],
            [InlineKeyboardButton("🔙 Главное меню", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = f"🛠 <b>Админ-панель</b>\n\nПривет, {html.escape(user.first_name)}!\nВыберите раздел:"

        if message_id:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            if update.callback_query:
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup,
                                                               parse_mode='HTML')
            else:
                await update.message.reply_text(text, reply_markup=reply_markup,
                                                parse_mode='HTML')

    def set_balance(self, user_id, amount):
        """Установить баланс пользователя"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET balance = ? 
                    WHERE user_id = ?
                ''', (amount, user_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при установке баланса {user_id}: {e}")
            return False

    def get_referrals_count(self, user_id):
        """Получить количество рефералов"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT total_referrals FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                return result['total_referrals'] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении количества рефералов {user_id}: {e}")
            return 0

    async def show_users_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Управление пользователями"""
        query = update.callback_query
        await query.answer()

        top_players = db.get_top_players(10)

        text = "👤 <b>Последние 10 пользователей:</b>\n\n"

        if not top_players:
            text += "Пользователей нет."
        else:
            for i, player in enumerate(top_players, 1):
                username = player['username'] or f"ID: {player['user_id']}"
                # Экранируем специальные символы
                safe_username = html.escape(str(username))
                text += f"{i}. @{safe_username}\n"
                text += f"   💰 {player['balance']} тенге | 🃏 {player['card_count']} карт\n"
                text += f"   [ID: {player['user_id']}]\n\n"

        keyboard = [
            [InlineKeyboardButton("🚫 Заблокировать пользователя",
                                  callback_data="admin_block_user")],
            [InlineKeyboardButton("✅ Разблокировать",
                                  callback_data="admin_unblock_user")],
            [InlineKeyboardButton("📊 Подробная статистика",
                                  callback_data="admin_user_stats")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def show_blocked_users(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать заблокированных пользователей"""
        query = update.callback_query
        await query.answer()

        blocked_users = db.get_blocked_users()

        text = "🚫 <b>Заблокированные пользователи:</b>\n\n"

        if not blocked_users:
            text += "Нет заблокированных пользователей."
        else:
            for i, user in enumerate(blocked_users, 1):
                username = user['username'] or f"ID: {user['user_id']}"
                safe_username = html.escape(str(username))
                safe_blocked_by = html.escape(str(user['blocked_by']))
                safe_reason = html.escape(str(user['reason']))

                text += f"{i}. @{safe_username}\n"
                text += f"   👤 Заблокировал: {safe_blocked_by}\n"
                text += f"   📝 Причина: {safe_reason}\n"
                text += f"   🕐 {user['blocked_at']}\n"
                text += f"   [ID: {user['user_id']}]\n\n"

        keyboard = [
            [InlineKeyboardButton("✅ Разблокировать всех",
                                  callback_data="admin_unblock_all")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать статистику"""
        query = update.callback_query
        await query.answer()

        stats = db.get_user_stats()

        text = (
            "📊 <b>Статистика бота:</b>\n\n"
            f"👥 Всего пользователей: {stats['total_users']}\n"
            f"🚫 Заблокированных: {stats['blocked_users']}\n"
            f"💰 Общий баланс: {stats['total_balance']} тенге\n"
            f"🃏 Всего карточек: {stats['total_cards']}\n"
            f"🎴 Активных карточек: {stats['active_cards']}\n"
        )

        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="admin_stats")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def show_admins(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать список админов"""
        query = update.callback_query
        await query.answer()

        admins = db.get_admins()

        text = "⚙️ <b>Администраторы:</b>\n\n"

        if not admins:
            text += "Нет администраторов."
        else:
            for i, admin in enumerate(admins, 1):
                username = admin['username'] or f"ID: {admin['user_id']}"
                safe_username = html.escape(str(username))
                text += f"{i}. @{safe_username}\n"
                text += f"   🆔 ID: {admin['user_id']}\n"
                text += f"   📅 Добавлен: {admin['added_at']}\n\n"

        keyboard = [
            [InlineKeyboardButton("➕ Добавить админа", callback_data="admin_add_admin")],
            [InlineKeyboardButton("➖ Удалить админа", callback_data="admin_remove_admin")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def block_user_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на блокировку пользователя"""
        query = update.callback_query
        await query.answer()

        text = (
            "🚫 <b>Блокировка пользователя</b>\n\n"
            "Отправьте ID пользователя для блокировки.\n"
            "Формат: <code>123456789 Причина блокировки</code>\n\n"
            "Пример: <code>123456789 Нарушение правил</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_block'] = True

    async def unblock_user_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на разблокировку пользователя"""
        query = update.callback_query
        await query.answer()

        text = (
            "✅ <b>Разблокировка пользователя</b>\n\n"
            "Отправьте ID пользователя для разблокировки.\n"
            "Формат: <code>123456789</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_unblock'] = True

    async def search_user_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на поиск пользователя"""
        query = update.callback_query
        await query.answer()

        text = (
            "🔍 <b>Поиск пользователя</b>\n\n"
            "Отправьте ID или имя пользователя для поиска.\n"
            "Формат: <code>123456789</code> или <code>username</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_search'] = True

    async def add_admin_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на добавление админа"""
        query = update.callback_query
        await query.answer()

        text = (
            "➕ <b>Добавление администратора</b>\n\n"
            "Отправьте ID пользователя для добавления в админы.\n"
            "Формат: <code>123456789</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_add_admin'] = True

    async def show_suggestions_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления предложенными карточками"""
        query = update.callback_query
        await query.answer()

        suggestions = db.get_pending_suggestions()

        text = "📥 <b>Предложенные карточки:</b>\n\n"

        if not suggestions:
            text += "Нет новых предложений."
        else:
            for i, sug in enumerate(suggestions, 1):
                user = db.get_user(sug['user_id'])
                username = user['username'] if user else f"ID: {sug['user_id']}"
                text += f"{i}. От @{html.escape(str(username))}\n"
                text += f"   🕐 {sug['submitted_at']}\n"
                text += f"   🆔 Предложение №: {sug['id']}\n\n"

        keyboard = [
            [InlineKeyboardButton("✅ Одобрить", callback_data="admin_approve_suggestion")],
            [InlineKeyboardButton("❌ Отклонить", callback_data="admin_reject_suggestion")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def approve_suggestion_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос ID предложения для одобрения"""
        query = update.callback_query
        await query.answer()

        text = (
            "✅ <b>Одобрение предложения</b>\n\n"
            "Отправьте ID предложения для одобрения.\n"
            "Формат: <code>123</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_approve_suggestion'] = True

    async def reject_suggestion_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос ID предложения для отклонения"""
        query = update.callback_query
        await query.answer()

        text = (
            "❌ <b>Отклонение предложения</b>\n\n"
            "Отправьте ID предложения для отклонения.\n"
            "Формат: <code>123</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_reject_suggestion'] = True

    async def show_balance_management(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Меню управления балансом"""
        query = update.callback_query
        await query.answer()

        text = (
            "💰 <b>Управление балансом</b>\n\n"
            "Выберите действие:"
        )

        keyboard = [
            [InlineKeyboardButton("➕ Добавить тенге", callback_data="admin_balance_add")],
            [InlineKeyboardButton("➖ Снять тенге", callback_data="admin_balance_remove")],
            [InlineKeyboardButton("✏️ Установить баланс", callback_data="admin_balance_set")],
            [InlineKeyboardButton("🔍 Проверить баланс", callback_data="admin_balance_check")],
            [InlineKeyboardButton("🔙 Назад", callback_data="admin_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def balance_add_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на добавление тенге"""
        query = update.callback_query
        await query.answer()

        text = (
            "➕ <b>Добавление тенге</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>ID пользователя Сумма</code>\n\n"
            "Пример: <code>123456789 500</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_balance_add'] = True

    async def balance_remove_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на снятие тенге"""
        query = update.callback_query
        await query.answer()

        text = (
            "➖ <b>Снятие тенге</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>ID пользователя Сумма</code>\n\n"
            "Пример: <code>123456789 200</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_balance_remove'] = True

    async def balance_set_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на установку баланса"""
        query = update.callback_query
        await query.answer()

        text = (
            "✏️ <b>Установка баланса</b>\n\n"
            "Отправьте данные в формате:\n"
            "<code>ID пользователя Новый баланс</code>\n\n"
            "Пример: <code>123456789 1000</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_balance_set'] = True

    async def balance_check_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на проверку баланса"""
        query = update.callback_query
        await query.answer()

        text = (
            "🔍 <b>Проверка баланса</b>\n\n"
            "Отправьте ID пользователя для проверки баланса.\n"
            "Формат: <code>123456789</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_balance_check'] = True
    async def remove_admin_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запрос на удаление админа"""
        query = update.callback_query
        await query.answer()

        text = (
            "➖ <b>Удаление администратора</b>\n\n"
            "Отправьте ID пользователя для удаления из админов.\n"
            "Формат: <code>123456789</code>\n\n"
            "Для отмены отправьте /cancel"
        )

        await query.message.edit_text(text, parse_mode='HTML')
        context.user_data['awaiting_remove_admin'] = True

    async def handle_admin_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка сообщений для админ-панели"""
        user_id = update.effective_user.id


        if not await self.check_admin(user_id):
            return

        message_text = update.message.text

        # Обработка отмены
        if message_text.lower() == '/cancel':
            context.user_data.clear()
            await update.message.reply_text("❌ Действие отменено.")
            await self.show_admin_menu(update, context)
            return
        elif context.user_data.get('awaiting_approve_suggestion'):
            try:
                suggestion_id = int(message_text)
                user_id = db.approve_suggestion(suggestion_id, update.effective_user.id)

                # Уведомляем пользователя
                try:
                    await self.app.bot.send_message(
                        chat_id=user_id,
                        text="✅ Ваша предложенная карточка была одобрена!\n"
                             "Вам начислено 500 тенге!"
                    )
                except:
                    pass

                await update.message.reply_text(f"✅ Предложение #{suggestion_id} одобрено!")
            except ValueError:
                await update.message.reply_text("❌ Неверный ID предложения!")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        elif context.user_data.get('awaiting_reject_suggestion'):
            try:
                suggestion_id = int(message_text)
                db.reject_suggestion(suggestion_id, update.effective_user.id)

                # Уведомляем пользователя
                cursor = db.get_connection().cursor()
                cursor.execute('SELECT user_id FROM suggested_cards WHERE id = ?', (suggestion_id,))
                user_id = cursor.fetchone()['user_id']

                try:
                    await self.app.bot.send_message(
                        chat_id=user_id,
                        text="❌ Ваша предложенная карточка была отклонена.\n"
                             "Попробуйте предложить другую карточку!"
                    )
                except:
                    pass

                await update.message.reply_text(f"❌ Предложение #{suggestion_id} отклонено!")
            except ValueError:
                await update.message.reply_text("❌ Неверный ID предложения!")
        elif context.user_data.get('awaiting_balance_add'):
            try:
                parts = update.message.text.split()
                if len(parts) >= 2:
                    target_id = int(parts[0])
                    amount = int(parts[1])

                    user = db.get_user(target_id)
                    if user:
                        old_balance = user['balance']
                        db.update_balance(target_id, amount)
                        db.add_balance_history(target_id, amount, 'admin_add')

                        new_user = db.get_user(target_id)

                        await update.message.reply_text(
                            f"✅ Баланс пользователя изменен!\n\n"
                            f"👤 ID: {target_id}\n"
                            f"💰 Было: {old_balance} тенге\n"
                            f"➕ Добавлено: +{amount} тенге\n"
                            f"💵 Стало: {new_user['balance']} тенге"
                        )

                        # Уведомляем пользователя
                        try:
                            await self.app.bot.send_message(
                                chat_id=target_id,
                                text=f"💰 Вам начислено {amount} тенге администратором!\n"
                                     f"💵 Новый баланс: {new_user['balance']} тенге"
                            )
                        except:
                            pass
                    else:
                        await update.message.reply_text("❌ Пользователь с таким ID не найден!")
                else:
                    await update.message.reply_text("❌ Неверный формат! Используйте: ID Сумма")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! ID и сумма должны быть числами")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Снятие баланса
        elif context.user_data.get('awaiting_balance_remove'):
            try:
                parts = update.message.text.split()
                if len(parts) >= 2:
                    target_id = int(parts[0])
                    amount = int(parts[1])

                    user = db.get_user(target_id)
                    if user:
                        if user['balance'] >= amount:
                            old_balance = user['balance']
                            db.update_balance(target_id, -amount)
                            db.add_balance_history(target_id, -amount, 'admin_remove')

                            new_user = db.get_user(target_id)

                            await update.message.reply_text(
                                f"✅ Баланс пользователя изменен!\n\n"
                                f"👤 ID: {target_id}\n"
                                f"💰 Было: {old_balance} тенге\n"
                                f"➖ Снято: -{amount} тенге\n"
                                f"💵 Стало: {new_user['balance']} тенге"
                            )

                            # Уведомляем пользователя
                            try:
                                await self.app.bot.send_message(
                                    chat_id=target_id,
                                    text=f"💰 С вашего счета списано {amount} тенге администратором!\n"
                                         f"💵 Новый баланс: {new_user['balance']} тенге"
                                )
                            except:
                                pass
                        else:
                            await update.message.reply_text(
                                f"❌ Недостаточно средств! Баланс пользователя: {user['balance']} тенге")
                    else:
                        await update.message.reply_text("❌ Пользователь с таким ID не найден!")
                else:
                    await update.message.reply_text("❌ Неверный формат! Используйте: ID Сумма")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! ID и сумма должны быть числами")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Установка баланса
        elif context.user_data.get('awaiting_balance_set'):
            try:
                parts = update.message.text.split()
                if len(parts) >= 2:
                    target_id = int(parts[0])
                    new_balance = int(parts[1])

                    user = db.get_user(target_id)
                    if user:
                        old_balance = user['balance']
                        db.set_balance(target_id, new_balance)
                        db.add_balance_history(target_id, new_balance - old_balance, 'admin_set')

                        await update.message.reply_text(
                            f"✅ Баланс пользователя установлен!\n\n"
                            f"👤 ID: {target_id}\n"
                            f"💰 Было: {old_balance} тенге\n"
                            f"✏️ Установлено: {new_balance} тенге"
                        )

                        # Уведомляем пользователя
                        try:
                            await self.app.bot.send_message(
                                chat_id=target_id,
                                text=f"💰 Ваш баланс изменен администратором!\n"
                                     f"💵 Новый баланс: {new_balance} тенге"
                            )
                        except:
                            pass
                    else:
                        await update.message.reply_text("❌ Пользователь с таким ID не найден!")
                else:
                    await update.message.reply_text("❌ Неверный формат! Используйте: ID Новый_баланс")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! ID и баланс должны быть числами")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Проверка баланса
        elif context.user_data.get('awaiting_balance_check'):
            try:
                target_id = int(update.message.text.strip())

                user = db.get_user(target_id)
                if user:
                    cards_count = db.get_card_count(target_id)
                    referrals_count = db.get_referrals_count(target_id)

                    text = (
                        f"🔍 <b>Информация о пользователе</b>\n\n"
                        f"👤 ID: {target_id}\n"
                        f"📝 Username: @{user['username'] or 'Не указан'}\n"
                        f"💰 Баланс: {user['balance']} тенге\n"
                        f"🃏 Карточек: {cards_count}\n"
                        f"👥 Рефералов: {referrals_count}\n"
                        f"📅 Регистрация: {user['created_at']}"
                    )

                    await update.message.reply_text(text, parse_mode='HTML')
                else:
                    await update.message.reply_text("❌ Пользователь с таким ID не найден!")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! ID должен быть числом")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Блокировка пользователя
        if context.user_data.get('awaiting_block'):
            parts = message_text.split(' ', 1)
            if len(parts) >= 1:
                try:
                    target_id = int(parts[0])
                    reason = parts[1] if len(parts) > 1 else "Не указана"

                    try:
                        user = await self.app.bot.get_chat(target_id)
                        username = user.username or user.first_name
                    except:
                        username = "Unknown"

                    db.block_user(target_id, username, update.effective_user.username, reason)

                    await update.message.reply_text(
                        f"✅ Пользователь @{username} (ID: {target_id}) заблокирован!\n"
                        f"Причина: {reason}"
                    )

                    try:
                        await self.app.bot.send_message(
                            chat_id=target_id,
                            text=f"🚫 Вы были заблокированы в боте!\nПричина: {reason}"
                        )
                    except:
                        pass

                except ValueError:
                    await update.message.reply_text("❌ Неверный ID пользователя!")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Разблокировка пользователя
        elif context.user_data.get('awaiting_unblock'):
            try:
                target_id = int(message_text)
                db.unblock_user(target_id)
                await update.message.reply_text(f"✅ Пользователь (ID: {target_id}) разблокирован!")
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя!")

            context.user_data.clear()
            await self.show_admin_menu(update, context)
        elif context.user_data.get('awaiting_rarity_add'):
            try:
                parts = update.message.text.split(',')
                if len(parts) >= 2:
                    name = parts[0].strip()
                    price = int(parts[1].strip())
                    weight = int(parts[2].strip()) if len(parts) > 2 else 10

                    if db.add_rarity(name, price, weight):
                        # Создаем папку для новой редкости
                        import os
                        rarity_path = os.path.join(self.config.CARDS_PATH, name)
                        os.makedirs(rarity_path, exist_ok=True)

                        await update.message.reply_text(
                            f"✅ Редкость '{name}' добавлена!\n"
                            f"Цена: {price} тенге\n"
                            f"Вес: {weight}%"
                        )
                    else:
                        await update.message.reply_text("❌ Такая редкость уже существует!")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! Используйте: Название,Цена,Вес")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Изменение цены
        elif context.user_data.get('awaiting_price_edit'):
            try:
                parts = update.message.text.split(',')
                if len(parts) >= 2:
                    name = parts[0].strip()
                    price = int(parts[1].strip())

                    if db.update_rarity_price(name, price):
                        await update.message.reply_text(
                            f"✅ Цена редкости '{name}' изменена на {price} тенге!"
                        )
                    else:
                        await update.message.reply_text("❌ Редкость не найдена!")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! Используйте: Название,Цена")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Изменение веса
        elif context.user_data.get('awaiting_weight_edit'):
            try:
                parts = update.message.text.split(',')
                if len(parts) >= 2:
                    name = parts[0].strip()
                    weight = int(parts[1].strip())

                    if db.update_rarity_weight(name, weight):
                        await update.message.reply_text(
                            f"✅ Вес редкости '{name}' изменен на {weight}%!"
                        )
                    else:
                        await update.message.reply_text("❌ Редкость не найдена!")
            except ValueError:
                await update.message.reply_text("❌ Неверный формат! Используйте: Название,Вес")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Удаление карточки
        elif context.user_data.get('awaiting_card_delete'):
            try:
                path_parts = update.message.text.split('/')
                if len(path_parts) == 2:
                    rarity = path_parts[0].strip()
                    card_name = path_parts[1].strip()

                    import os
                    file_path = os.path.join(self.config.CARDS_PATH, rarity, card_name)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                        await update.message.reply_text(f"✅ Карточка '{card_name}' удалена!")
                    else:
                        await update.message.reply_text("❌ Карточка не найдена!")
                else:
                    await update.message.reply_text("❌ Неверный формат! Используйте: Редкость/Название")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {e}")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Поиск пользователя
        elif context.user_data.get('awaiting_search'):
            users = db.search_users(message_text)

            if not users:
                await update.message.reply_text("❌ Пользователи не найдены!")
            else:
                text = "🔍 <b>Результаты поиска:</b>\n\n"
                for i, user in enumerate(users, 1):
                    username = user['username'] or f"ID: {user['user_id']}"
                    safe_username = html.escape(str(username))
                    text += f"{i}. @{safe_username}\n"
                    text += f"   💰 Баланс: {user['balance']} тенге\n"
                    text += f"   📅 Регистрация: {user['created_at']}\n"
                    text += f"   [ID: {user['user_id']}]\n\n"

                await update.message.reply_text(text, parse_mode='HTML')

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Добавление админа
        elif context.user_data.get('awaiting_add_admin'):
            try:
                target_id = int(message_text)
                try:
                    user = await self.app.bot.get_chat(target_id)
                    username = user.username or user.first_name
                except:
                    username = "Unknown"

                db.add_admin(target_id, username)
                await update.message.reply_text(
                    f"✅ Пользователь @{username} (ID: {target_id}) добавлен в админы!"
                )
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя!")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

        # Удаление админа
        elif context.user_data.get('awaiting_remove_admin'):
            try:
                target_id = int(message_text)
                db.remove_admin(target_id)
                await update.message.reply_text(f"✅ Админ (ID: {target_id}) удален!")
            except ValueError:
                await update.message.reply_text("❌ Неверный ID пользователя!")

            context.user_data.clear()
            await self.show_admin_menu(update, context)

    async def admin_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик кнопок админ-панели"""
        query = update.callback_query
        data = query.data

        await query.answer()

        if not await self.check_admin(query.from_user.id):
            await query.message.edit_text("❌ У вас нет прав администратора!")
            return

        if data == "admin_menu":
            await self.show_admin_menu(update, context, query.message.message_id)

        elif data == "admin_users":
            await self.show_users_management(update, context)

        elif data == "admin_blocked":
            await self.show_blocked_users(update, context)

        elif data == "admin_stats":
            await self.show_stats(update, context)

        elif data == "admin_admins":
            await self.show_admins(update, context)

        elif data == "admin_search":
            await self.search_user_prompt(update, context)

        elif data == "admin_block_user":
            await self.block_user_prompt(update, context)

        elif data == "admin_unblock_user":
            await self.unblock_user_prompt(update, context)

        elif data == "admin_add_admin":
            await self.add_admin_prompt(update, context)

        elif data == "admin_remove_admin":
            await self.remove_admin_prompt(update, context)
        # Добавьте эти условия в метод admin_button_handler

        elif data == "admin_balance":
            await self.show_balance_management(update, context)

        elif data == "admin_balance_add":
            await self.balance_add_prompt(update, context)

        elif data == "admin_balance_remove":
            await self.balance_remove_prompt(update, context)

        elif data == "admin_balance_set":
            await self.balance_set_prompt(update, context)

        elif data == "admin_balance_check":
            await self.balance_check_prompt(update, context)

        elif data == "admin_unblock_all":
            blocked_users = db.get_blocked_users()
            for user in blocked_users:
                db.unblock_user(user['user_id'])

            await query.message.edit_text(f"✅ Все пользователи ({len(blocked_users)}) разблокированы!")
        # Управление карточками
        elif data == "admin_cards":
            await self.show_cards_management(update, context)

        elif data == "admin_view_cards":
            await self.view_cards(update, context)

        elif data == "admin_add_card":
            await self.add_card_prompt(update, context)

        elif data == "admin_add_rarity":
            await self.add_rarity_prompt(update, context)

        elif data == "admin_edit_price":
            await self.edit_price_prompt(update, context)

        elif data == "admin_edit_weight":
            await self.edit_weight_prompt(update, context)

        elif data == "admin_delete_rarity":
            await self.delete_rarity_prompt(update, context)

        elif data == "admin_delete_card":
            await self.delete_card_prompt(update, context)

        elif data.startswith("admin_select_rarity_"):
            rarity = data.replace("admin_select_rarity_", "")
            context.user_data['awaiting_card_rarity'] = rarity
            await query.message.edit_text(
                f"📤 Отправьте изображение для редкости <b>{rarity}</b>\n"
                f"В подписи к фото можно указать название файла.\n\n"
                f"Для отмены отправьте /cancel",
                parse_mode='HTML'
            )

        elif data.startswith("admin_delete_rarity_conf_"):
            rarity = data.replace("admin_delete_rarity_conf_", "")
            if db.delete_rarity(rarity):
                # Удаляем папку с карточками
                import os, shutil
                rarity_path = os.path.join(self.config.CARDS_PATH, rarity)
                if os.path.exists(rarity_path):
                    shutil.rmtree(rarity_path)
                await query.message.edit_text(f"✅ Редкость '{rarity}' удалена!")
            else:
                await query.message.edit_text("❌ Не удалось удалить редкость!")