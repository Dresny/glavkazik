import os
import random
import logging
import asyncio
from datetime import datetime, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, JobQueue
)

from config import Config
from database import Database
from admin_panel import AdminPanel
import html

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()


class CardBot:
    def __init__(self):
        self.config = Config()
        self.app = Application.builder().token(self.config.TOKEN).build()

        # Инициализация админ-панели
        self.admin_panel = AdminPanel(self.app, self.config)

        # Регистрация обработчиков
        self.app.add_handler(CommandHandler("start", self.start))
        self.app.add_handler(CommandHandler("cards", self.show_cards_command))
        self.app.add_handler(CommandHandler("sell", self.sell_card_command))
        self.app.add_handler(CommandHandler("help", self.help_command))
        self.app.add_handler(CommandHandler("balance", self.balance_command))
        self.app.add_handler(CommandHandler("referral", self.referral_command))
        self.app.add_handler(CommandHandler("legend", self.legend_command))
        self.app.add_handler(CommandHandler("suggest", self.suggest_card_command))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))

        # Обработчики сообщений
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self.admin_panel.handle_admin_message
        ))
        self.app.add_handler(MessageHandler(
            filters.PHOTO,
            self.handle_photo
        ))

        # Планировщик задач
        self.setup_jobs()

        logger.info("Бот запущен!")

    def setup_jobs(self):
        """Настройка периодических задач"""
        job_queue = self.app.job_queue

        if job_queue:
            # Проверка обнуления балансов каждый день в 00:00
            job_queue.run_daily(
                self.check_reset_balances,
                time=time(hour=0, minute=0, second=0)
            )

            # Напоминания о бесплатном кейсе каждые 20 минут
            job_queue.run_repeating(
                self.remind_about_free_box,
                interval=600,  # 10 минут
                first=10
            )

    async def check_reset_balances(self, context: ContextTypes.DEFAULT_TYPE):
        """Проверка и обнуление балансов"""
        # Проверяем, прошло ли 3 дня с последнего обнуления
        # В реальном проекте лучше хранить дату последнего обнуления в БД
        db.reset_balances()
        logger.info("Балансы пользователей обнулены")

    async def remind_about_free_box(self, context: ContextTypes.DEFAULT_TYPE):
        """Напоминание о бесплатном кейсе"""
        # В реальном проекте можно хранить список пользователей,
        # у которых скоро будет доступен бесплатный кейс
        pass

    async def check_subscription(self, user_id: int) -> bool:
        if db.is_user_blocked(user_id):
            return False

        try:
            member = await self.app.bot.get_chat_member(
                chat_id=self.config.CHANNEL_ID,
                user_id=user_id
            )
            return member.status in ['member', 'administrator', 'creator']
        except Exception as e:
            logger.error(f"Ошибка при проверке подписки: {e}")
            return False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user

        if db.is_user_blocked(user.id):
            await update.message.reply_text(
                "🚫 Вы заблокированы в этом боте!\n"
                "Обратитесь к администратору для выяснения причин."
            )
            return

        # Проверяем реферальный код
        referrer_code = None
        if context.args and len(context.args) > 0:
            referrer_code = context.args[0]

        db.add_user(user.id, user.username, referrer_code)

        if not await self.check_subscription(user.id):
            keyboard = [
                [InlineKeyboardButton("📢 Подписаться на канал",
                                      url=f"https://t.me/podslusheno2120")],
                [InlineKeyboardButton("✅ Я подписался", callback_data="check_subscription")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                "👋 Привет! Для использования бота нужно подписаться на наш канал.\n"
                "Подпишись и нажми кнопку ниже 👇",
                reply_markup=reply_markup
            )
            return

        await self.show_main_menu(update, context)

    async def get_channel_username(self):
        try:
            chat = await self.app.bot.get_chat(self.config.CHANNEL_ID)
            return chat.username
        except:
            return "your_channel"

    async def show_main_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                             message_id: int = None):
        user = update.effective_user
        user_data = db.get_user(user.id)

        # Получаем время до следующего бесплатного кейса
        time_until_free = db.get_time_until_next_open(user.id, is_free=True)

        free_status = "✅ Доступен" if time_until_free == 0 else f"⏳ {time_until_free // 60} мин"

        keyboard = [
            [InlineKeyboardButton(f"🎁 Бесплатный кейс ({free_status})",
                                  callback_data="open_box_free")],
            [InlineKeyboardButton(f"💰 Платный кейс ({self.config.PAID_OPEN_PRICE} тенге)",
                                  callback_data="open_box_paid")],
            [InlineKeyboardButton("🃏 Мои карточки", callback_data="my_cards")],
            [InlineKeyboardButton("👥 Реферальная система", callback_data="referral_menu")],
            [InlineKeyboardButton("🏆 Топ 10", callback_data="top_players")],
            [InlineKeyboardButton("👑 Топ Легенд", callback_data="legend_top")],
            [InlineKeyboardButton("💡 Предложить карту", callback_data="suggest_card")],
            [InlineKeyboardButton("💰 Баланс", callback_data="show_balance")]
        ]

        if await self.admin_panel.check_admin(user.id):
            keyboard.append([InlineKeyboardButton("🛠 Админ-панель", callback_data="admin_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            f"🎮 Добро пожаловать, {html.escape(user.first_name)}!\n\n"
            f"💰 Баланс: {user_data['balance'] if user_data else 0} тенге\n"
            f"🃏 Карточек в коллекции: {db.get_card_count(user.id)}\n"
            f"👥 Рефералов: {user_data['total_referrals'] if user_data else 0}\n\n"
            f"⏰ Бесплатный кейс: {free_status}\n"
            "<b>Выберите действие:</b>"
        )

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

    async def referral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать реферальную информацию"""
        user = update.effective_user
        await self.show_referral_menu(user.id, update.message.chat.id, context)

    async def show_referral_menu(self, user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                                 message_id: int = None):
        """Показать реферальное меню"""
        referral_code = db.get_referral_code(user_id)
        referrals = db.get_referrals(user_id)
        user_data = db.get_user(user_id)

        text = (
            "👥 <b>Реферальная система</b>\n\n"
            f"🔗 Ваша реферальная ссылка:\n"
            f"<code>https://t.me/{context.bot.username}?start={referral_code}</code>\n\n"
            f"📊 Приглашено друзей: {len(referrals)}\n"
            f"💰 Заработано с рефералов: {user_data['referral_earnings']} тенге\n\n"
            f"🎁 <b>Бонусы:</b>\n"
            f"• За каждого друга, который набрал баланс >0 - 750 тенге\n"
            f"• Друзья получают 100 тенге при регистрации\n\n"
        )

        if referrals:
            text += "<b>Ваши рефералы:</b>\n"
            for i, ref in enumerate(referrals[:5], 1):
                username = ref['username'] or f"ID: {ref['user_id']}"
                text += f"{i}. @{html.escape(str(username))} - {ref['balance']} тенге\n"

        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🔄 Поделиться ссылкой",
                                  callback_data="share_referral")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

    async def legend_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать топ легенд"""
        await self.show_legend_top(update.message.chat.id, context)

    async def show_legend_top(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                              message_id: int = None):
        """Показать топ легенд"""
        legend_top = db.get_legend_top(10)

        if not legend_top:
            text = "👑 Топ Легенд пока пуст!"
        else:
            text = "👑 <b>Топ Легенд (вечные очки):</b>\n\n"
            emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

            for i, player in enumerate(legend_top):
                emoji = emojis[i] if i < len(emojis) else f"{i + 1}."
                username = player['username'] or f"User_{player['user_id']}"
                safe_username = html.escape(str(username))
                text += (
                    f"{emoji} @{safe_username}\n"
                    f"   👑 Очков легенд: {player['total_points']}\n"
                    f"   🏆 Побед в периодах: {player['periods_won']}\n\n"
                )

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

    async def suggest_card_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Предложить карточку"""
        await update.message.reply_text(
            "📤 Отправьте изображение карточки, которую хотите предложить.\n"
            "Если администратор одобрит, вы получите 500 тенге!"
        )

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка фото (предложение карточки или добавление админом)"""
        user_id = update.effective_user.id

        # Проверяем, не админ ли это в режиме добавления карточки
        if await self.admin_panel.check_admin(user_id) and context.user_data.get('awaiting_card_rarity'):
            await self.admin_panel.handle_card_photo(update, context)
            return

        # Обычный пользователь - предложение карточки
        photo = update.message.photo[-1]
        file = await photo.get_file()

        # Сохраняем в временную папку
        temp_dir = "temp_suggestions"
        os.makedirs(temp_dir, exist_ok=True)
        file_path = os.path.join(temp_dir, f"suggestion_{user_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
        await file.download_to_drive(file_path)

        # Добавляем в БД
        db.add_suggested_card(user_id, file_path)

        # Уведомляем админов
        admins = db.get_admins()
        for admin in admins:
            try:
                await context.bot.send_message(
                    chat_id=admin['user_id'],
                    text=f"📥 Новое предложение карточки от пользователя @{update.effective_user.username or user_id}\n"
                         f"ID предложения: {db.get_pending_suggestions()[-1]['id']}\n"
                         f"Используйте админ-панель для проверки"
                )
                # Отправляем фото админу
                with open(file_path, 'rb') as photo_file:
                    await context.bot.send_photo(
                        chat_id=admin['user_id'],
                        photo=photo_file
                    )
            except:
                pass

        await update.message.reply_text(
            "✅ Спасибо за предложение! Администратор рассмотрит его и начислит бонус в случае одобрения."
        )

    async def open_box(self, update: Update, context: ContextTypes.DEFAULT_TYPE, is_free=True):
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id

        if db.is_user_blocked(user_id):
            await query.message.reply_text("🚫 Вы заблокированы в этом боте!")
            return

        if not await self.check_subscription(user_id):
            await query.message.reply_text("❌ Вы отписались от канала! Подпишитесь снова.")
            return

        # Проверка для платного открытия
        if not is_free:
            user_data = db.get_user(user_id)
            if user_data['balance'] < self.config.PAID_OPEN_PRICE:
                await query.message.reply_text(
                    f"❌ Недостаточно средств!\n"
                    f"Требуется: {self.config.PAID_OPEN_PRICE} тенге\n"
                    f"Ваш баланс: {user_data['balance']} тенге"
                )
                return
            db.update_balance(user_id, -self.config.PAID_OPEN_PRICE)
            db.add_balance_history(user_id, -self.config.PAID_OPEN_PRICE, 'paid_box')

        # Проверка времени для бесплатного открытия
        if is_free and not db.can_open_box(user_id, is_free=True):
            time_left = db.get_time_until_next_open(user_id, is_free=True)
            minutes = time_left // 60
            seconds = time_left % 60

            await query.message.reply_text(
                f"⏳ Бесплатное открытие через: {minutes} мин {seconds} сек\n"
                f"💎 Можете открыть платный ящик за {self.config.PAID_OPEN_PRICE} тенге"
            )
            return

        card_info = self.get_random_card()
        if not card_info:
            await query.message.reply_text("❌ Ошибка: карточки не найдены!")
            return

        db.add_card_to_user(user_id, card_info['name'], card_info['rarity'], card_info['path'])
        db.update_last_opened(user_id, is_free)

        price = db.get_rarity_price(card_info['rarity'])


        with open(card_info['path'], 'rb') as photo:
            await query.message.reply_photo(
                photo=photo,
                caption=(
                    f"🎉 Вы получили карточку!\n\n"
                    f"🏷 Название: {card_info['name']}\n"
                    f"⭐ Редкость: {card_info['rarity']}\n"
                    f"💰 Цена продажи: {price} тенге\n"
                    f"{'💎 Платное открытие' if not is_free else '🎁 Бесплатное открытие'}\n\n"
                    f"🆔 Карта №: {db.get_user_cards(user_id)[0]['id']}"
                )
            )

        await self.show_main_menu(update, context, query.message.message_id)

    def get_random_card(self):
        try:
            rarities = db.get_all_rarities()
            weights = [r['weight'] for r in rarities]
            names = [r['name'] for r in rarities]

            chosen_rarity = random.choices(names, weights=weights, k=1)[0]
            rarity_path = os.path.join(self.config.CARDS_PATH, chosen_rarity)

            cards = [f for f in os.listdir(rarity_path)
                     if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]

            if not cards:
                return None

            chosen_card = random.choice(cards)
            card_path = os.path.join(rarity_path, chosen_card)
            card_name = os.path.splitext(chosen_card)[0]

            return {
                'name': card_name,
                'rarity': chosen_rarity,
                'path': card_path
            }
        except Exception as e:
            logger.error(f"Ошибка при получении карточки: {e}")
            return None

    async def show_cards_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await self.show_cards(user.id, update.message.chat.id, context)

    async def show_cards(self, user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE,
                         message_id: int = None):
        cards = db.get_user_cards(user_id)

        if not cards:
            text = "📭 У вас пока нет карточек!"
            keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        else:
            text = "🃏 <b>Ваши карточки:</b>\n\n"
            total_price = 0
            for i, card in enumerate(cards, 1):
                price = db.get_rarity_price(card['rarity'])
                total_price += price
                text += f"{i}. {html.escape(card['card_name'])}\n"
                text += f"   ⭐ Редкость: {card['rarity']}\n"
                text += f"   💰 Цена: {price} тенге\n"
                text += f"   🆔 Карта №: {card['id']}\n\n"

            text += f"💰 Общая стоимость: {total_price} тенге\n\n"
            text += "Для продажи карточки используйте команду: /sell &lt;id&gt;"

            keyboard = [
                [InlineKeyboardButton("💰 Продать все", callback_data="sell_all")],
                [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
            ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        if message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML'
            )

    async def sell_card_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Использование: /sell <id_карточки>")
            return

        try:
            card_id = int(context.args[0])
            user_id = update.effective_user.id

            if db.is_user_blocked(user_id):
                await update.message.reply_text("🚫 Вы заблокированы и не можете продавать карточки!")
                return

            rarity = db.sell_card(card_id, user_id)

            if rarity:
                price = db.get_rarity_price(rarity)
                db.update_balance(user_id, price)
                db.add_balance_history(user_id, price, 'card_sale')
                user_data = db.get_user(user_id)

                await update.message.reply_text(
                    f"✅ Карточка продана за {price} тенге!\n"
                    f"💰 Новый баланс: {user_data['balance']} тенге\n"
                    f"🃏 Осталось карточек: {db.get_card_count(user_id)}"
                )
            else:
                await update.message.reply_text("❌ Карточка не найдена или уже продана!")

        except ValueError:
            await update.message.reply_text("❌ Неверный ID карточки! Используйте число.")
        except Exception as e:
            logger.error(f"Ошибка при продаже: {e}")
            await update.message.reply_text("❌ Произошла ошибка при продаже!")

    async def show_top_players(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query:
            await query.answer()

        top_players = db.get_top_players(10)

        if not top_players:
            text = "🏆 Топ игроков пока пуст!"
        else:
            text = "🏆 <b>Топ 10 игроков (текущий баланс):</b>\n\n"
            emojis = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

            for i, player in enumerate(top_players):
                emoji = emojis[i] if i < len(emojis) else f"{i + 1}."
                username = player['username'] or f"User_{player['user_id']}"
                safe_username = html.escape(str(username))
                text += (
                    f"{emoji} @{safe_username}\n"
                    f"   💰 Баланс: {player['balance']} тенге\n"
                    f"   🃏 Карточек: {player['card_count']}\n\n"
                )

        keyboard = [
            [InlineKeyboardButton("👑 Топ Легенд", callback_data="legend_top")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')
        else:
            await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def show_balance(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        user_id = query.from_user.id
        user_data = db.get_user(user_id)

        text = (
            f"💰 <b>Ваш баланс:</b> {user_data['balance']} тенге\n"
            f"🃏 <b>Карточек в коллекции:</b> {db.get_card_count(user_id)}\n"
            f"👥 <b>Рефералов:</b> {user_data['total_referrals']}\n\n"
            f"⚡ Баланс обнуляется каждые 3 дня!\n"
            f"🏆 Следите за топом Легенд!"
        )

        keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="main_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.message.edit_text(text, reply_markup=reply_markup, parse_mode='HTML')

    async def balance_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        user_data = db.get_user(user_id)

        text = (
            f"💰 <b>Ваш баланс:</b> {user_data['balance']} тенге\n"
            f"🃏 <b>Карточек в коллекции:</b> {db.get_card_count(user_id)}\n"
            f"👥 <b>Рефералов:</b> {user_data['total_referrals']}"
        )

        await update.message.reply_text(text, parse_mode='HTML')

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        data = query.data

        await query.answer()

        if data == "check_subscription":
            if await self.check_subscription(query.from_user.id):
                await self.show_main_menu(update, context, query.message.message_id)
            else:
                await query.answer("Вы ещё не подписались!", show_alert=True)

        elif data == "open_box_free":
            await self.open_box(update, context, is_free=True)

        elif data == "open_box_paid":
            await self.open_box(update, context, is_free=False)

        elif data == "my_cards":
            await self.show_cards(query.from_user.id, query.message.chat.id, context,
                                  query.message.message_id)

        elif data == "top_players":
            await self.show_top_players(update, context)

        elif data == "legend_top":
            await self.show_legend_top(query.message.chat.id, context, query.message.message_id)

        elif data == "referral_menu":
            await self.show_referral_menu(query.from_user.id, query.message.chat.id, context,
                                          query.message.message_id)

        elif data == "share_referral":
            referral_code = db.get_referral_code(query.from_user.id)
            await query.message.reply_text(
                f"🔗 Ваша реферальная ссылка:\n"
                f"<code>https://t.me/{context.bot.username}?start={referral_code}</code>\n\n"
                f"📤 Отправьте эту ссылку друзьям!\n"
                f"За каждого активного друга вы получите 750 тенге!",
                parse_mode='HTML'
            )

        elif data == "suggest_card":
            await query.message.reply_text(
                "📤 Отправьте изображение карточки, которую хотите предложить.\n"
                "Если администратор одобрит, вы получите 500 тенге!"
            )

        elif data == "show_balance":
            await self.show_balance(update, context)

        elif data == "admin_menu":
            await self.admin_panel.show_admin_menu(update, context, query.message.message_id)

        elif data == "main_menu":
            await self.show_main_menu(update, context, query.message.message_id)

        elif data == "sell_all":
            user_id = query.from_user.id

            if db.is_user_blocked(user_id):
                await query.answer("Вы заблокированы!", show_alert=True)
                return

            cards = db.get_user_cards(user_id)

            if not cards:
                await query.answer("У вас нет карточек для продажи!", show_alert=True)
                return

            total_price = 0
            sold_count = 0

            for card in cards:
                price = db.get_rarity_price(card['rarity'])
                db.sell_card(card['id'], user_id)
                db.update_balance(user_id, price)
                db.add_balance_history(user_id, price, 'card_sale')
                total_price += price
                sold_count += 1

            user_data = db.get_user(user_id)
            await query.message.edit_text(
                f"💰 Продано {sold_count} карточек за {total_price} тенге!\n"
                f"💵 Новый баланс: {user_data['balance']} тенге"
            )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        rarities = db.get_all_rarities()
        prices_text = ""
        for r in rarities:
            prices_text += f"• {r['name']}: {r['price']} тенге (шанс {r['weight']}%)\n"

        help_text = (
            "🎮 <b>Помощь по боту</b>\n\n"
            "📌 <b>Основные команды:</b>\n"
            "/start - Начать работу с ботом\n"
            "/cards - Показать ваши карточки\n"
            "/sell <id> - Продать карточку по ID\n"
            "/balance - Показать баланс\n"
            "/referral - Реферальная система\n"
            "/legend - Топ Легенд\n"
            "/suggest - Предложить карту\n"
            "/help - Показать это сообщение\n\n"
            "📋 <b>Как работает бот:</b>\n"
            "1️⃣ Подпишитесь на канал\n"
            "2️⃣ Каждые 20 минут можно открыть бесплатный кейс\n"
            f"3️⃣ Можно открыть платный кейс за {self.config.PAID_OPEN_PRICE} тенге\n"
            "4️⃣ Получайте карточки разной редкости\n"
            "5️⃣ Продавайте карточки или собирайте коллекцию\n"
            "6️⃣ Баланс обнуляется каждые 3 дня\n"
            "7️⃣ Победители периода получают очки в Топ Легенд\n\n"
            "👥 <b>Реферальная система:</b>\n"
            "• Приглашайте друзей по своей ссылке\n"
            "• Когда друг наберет баланс >0 - вы получите 750 тенге\n"
            "• Друг получает 100 тенге при регистрации\n\n"
            "💡 <b>Предложение карт:</b>\n"
            "• Отправьте свою карту командой /suggest\n"
            "• Если админ одобрит - получите 500 тенге\n\n"
            "💰 <b>Цены карточек:</b>\n"
            f"{prices_text}"
        )

        await update.message.reply_text(help_text, parse_mode='HTML')

    def run(self):
        self.app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    bot = CardBot()
    bot.run()