import sqlite3
import logging
import hashlib
import time
from datetime import datetime, timedelta
from contextlib import contextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_name="bot_database.db"):
        self.db_name = db_name
        self.init_db()

    @contextmanager
    def get_connection(self, max_retries=5, retry_delay=0.1):
        conn = None
        for attempt in range(max_retries):
            try:
                conn = sqlite3.connect(self.db_name, timeout=10)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                yield conn
                conn.commit()
                break
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < max_retries - 1:
                    time.sleep(retry_delay)
                    continue
                else:
                    if conn:
                        conn.rollback()
                    logger.error(f"Database error after {attempt + 1} attempts: {e}")
                    raise
            except Exception as e:
                if conn:
                    conn.rollback()
                logger.error(f"Database error: {e}")
                raise
            finally:
                if conn:
                    conn.close()

    def init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("PRAGMA foreign_keys = ON")

            # Таблица пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    balance INTEGER DEFAULT 0,
                    last_opened TIMESTAMP,
                    last_free_opened TIMESTAMP,
                    referral_code TEXT UNIQUE,
                    referred_by INTEGER,
                    total_referrals INTEGER DEFAULT 0,
                    referral_earnings INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица карточек пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    card_name TEXT,
                    rarity TEXT,
                    file_path TEXT,
                    obtained_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_sold BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Таблица предложенных карточек
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS suggested_cards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    file_path TEXT,
                    status TEXT DEFAULT 'pending',
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    reviewed_by INTEGER,
                    reviewed_at TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Таблица редкостей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS rarities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    price INTEGER DEFAULT 0,
                    weight INTEGER DEFAULT 10,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица заблокированных пользователей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS blocked_users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    blocked_by TEXT,
                    reason TEXT,
                    blocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица админов
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS admins (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица для рассылок
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS mailing_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER,
                    message_text TEXT,
                    recipients_count INTEGER,
                    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица топ легенд
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS legend_top (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    period_start TIMESTAMP,
                    period_end TIMESTAMP,
                    balance_earned INTEGER DEFAULT 0,
                    legend_points INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Таблица истории баланса
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS balance_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    amount INTEGER,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')

            # Индексы
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_referred_by ON users(referred_by)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_balance_history_user ON balance_history(user_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_cards_user ON user_cards(user_id)')

            # Стандартные редкости
            default_rarities = [
                ("Обычный", 10, 40),
                ("Редкий", 15, 30),
                ("Мифик", 30, 15),
                ("Легендарный", 50, 10),
                ("Секрет", 100, 5)
            ]

            for name, price, weight in default_rarities:
                cursor.execute('''
                    INSERT OR IGNORE INTO rarities (name, price, weight)
                    VALUES (?, ?, ?)
                ''', (name, price, weight))

    # === ПОЛЬЗОВАТЕЛИ ===

    def add_user(self, user_id, username, referrer_code=None):
        """Добавить пользователя (с мгновенным начислением бонуса за реферала)"""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                existing = cursor.fetchone()

                if not existing:
                    referral_code = hashlib.md5(f"{user_id}_{datetime.now()}".encode()).hexdigest()[:8]

                    cursor.execute('''
                        INSERT INTO users (user_id, username, referral_code, balance)
                        VALUES (?, ?, ?, ?)
                    ''', (user_id, username, referral_code, 100))

                    if referrer_code:
                        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referrer_code,))
                        referrer = cursor.fetchone()
                        if referrer:
                            referrer_id = referrer['user_id']

                            # Обновляем referred_by у нового пользователя
                            cursor.execute('''
                                UPDATE users SET referred_by = ? WHERE user_id = ?
                            ''', (referrer_id, user_id))

                            # Увеличиваем счетчик рефералов
                            cursor.execute('''
                                UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id = ?
                            ''', (referrer_id,))

                            # СРАЗУ начисляем бонус 750 тенге
                            cursor.execute('''
                                UPDATE users SET balance = balance + 750, referral_earnings = referral_earnings + 750 
                                WHERE user_id = ?
                            ''', (referrer_id,))

                            # Записываем в историю
                            self.add_balance_history(referrer_id, 750, 'referral_bonus')

                            logger.info(f"Реферал {user_id} зарегистрирован, бонус 750 начислен {referrer_id}")

                    logger.info(f"Новый пользователь {user_id} добавлен")
        except Exception as e:
            logger.error(f"Ошибка при добавлении пользователя {user_id}: {e}")

    def get_user(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Ошибка при получении пользователя {user_id}: {e}")
            return None

    def update_balance(self, user_id, amount):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET balance = balance + ? 
                    WHERE user_id = ?
                ''', (amount, user_id))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при обновлении баланса {user_id}: {e}")
            return False

    def set_balance(self, user_id, amount):
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

    def get_all_users(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT user_id FROM users')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении всех пользователей: {e}")
            return []

    # === РЕФЕРАЛЫ ===

    def get_referral_code(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                if result and result['referral_code']:
                    return result['referral_code']

                code = hashlib.md5(f"{user_id}_{datetime.now()}".encode()).hexdigest()[:8]
                cursor.execute('''
                    UPDATE users SET referral_code = ? WHERE user_id = ?
                ''', (code, user_id))
                return code
        except Exception as e:
            logger.error(f"Ошибка при получении реферального кода {user_id}: {e}")
            return None

    def get_referrals(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_id, username, balance, created_at 
                    FROM users 
                    WHERE referred_by = ?
                    ORDER BY created_at DESC
                ''', (user_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении рефералов {user_id}: {e}")
            return []

    def get_referrals_count(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT total_referrals FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                return result['total_referrals'] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении количества рефералов {user_id}: {e}")
            return 0

    # === КЕЙСЫ ===

    def update_last_opened(self, user_id, is_free=True):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now()
                if is_free:
                    cursor.execute('''
                        UPDATE users 
                        SET last_free_opened = ? 
                        WHERE user_id = ?
                    ''', (now, user_id))
                cursor.execute('''
                    UPDATE users 
                    SET last_opened = ? 
                    WHERE user_id = ?
                ''', (now, user_id))
        except Exception as e:
            logger.error(f"Ошибка при обновлении времени открытия {user_id}: {e}")

    def can_open_box(self, user_id, is_free=True):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if is_free:
                    cursor.execute('SELECT last_free_opened FROM users WHERE user_id = ?', (user_id,))
                else:
                    cursor.execute('SELECT last_opened FROM users WHERE user_id = ?', (user_id,))
                user = cursor.fetchone()

                if not user or not user[0]:
                    return True

                last_opened = datetime.fromisoformat(user[0])
                time_passed = (datetime.now() - last_opened).total_seconds()
                cooldown = 1200 if is_free else 3600
                return time_passed >= cooldown
        except Exception as e:
            logger.error(f"Ошибка при проверке открытия кейса {user_id}: {e}")
            return False

    def get_time_until_next_open(self, user_id, is_free=True):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if is_free:
                    cursor.execute('SELECT last_free_opened FROM users WHERE user_id = ?', (user_id,))
                else:
                    cursor.execute('SELECT last_opened FROM users WHERE user_id = ?', (user_id,))
                user = cursor.fetchone()

                if not user or not user[0]:
                    return 0

                last_opened = datetime.fromisoformat(user[0])
                cooldown = 1200 if is_free else 3600
                next_time = last_opened + timedelta(seconds=cooldown)
                time_left = next_time - datetime.now()

                return max(0, int(time_left.total_seconds()))
        except Exception as e:
            logger.error(f"Ошибка при получении времени до открытия {user_id}: {e}")
            return 0

    # === РЕДКОСТИ ===

    def get_all_rarities(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM rarities ORDER BY weight DESC')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении списка редкостей: {e}")
            return []

    def add_rarity(self, name, price, weight=10):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO rarities (name, price, weight)
                    VALUES (?, ?, ?)
                ''', (name, price, weight))
                return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            logger.error(f"Ошибка при добавлении редкости {name}: {e}")
            return False

    def delete_rarity(self, name):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM rarities WHERE name = ?', (name,))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при удалении редкости {name}: {e}")
            return False

    def update_rarity_price(self, name, price):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE rarities SET price = ? WHERE name = ?
                ''', (price, name))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при обновлении цены редкости {name}: {e}")
            return False

    def update_rarity_weight(self, name, weight):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE rarities SET weight = ? WHERE name = ?
                ''', (weight, name))
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Ошибка при обновлении веса редкости {name}: {e}")
            return False

    def get_rarity_price(self, rarity_name):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT price FROM rarities WHERE name = ?', (rarity_name,))
                result = cursor.fetchone()
                return result['price'] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении цены редкости {rarity_name}: {e}")
            return 0

    def get_random_rarity(self):
        """Получить случайную редкость с учетом весов"""
        try:
            rarities = self.get_all_rarities()
            if not rarities:
                return "Обычный"

            import random
            weights = [r['weight'] for r in rarities]
            names = [r['name'] for r in rarities]

            return random.choices(names, weights=weights, k=1)[0]
        except Exception as e:
            logger.error(f"Ошибка при получении случайной редкости: {e}")
            return "Обычный"

    # === КАРТОЧКИ ===

    def add_card_to_user(self, user_id, card_name, rarity, file_path):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO user_cards (user_id, card_name, rarity, file_path)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, card_name, rarity, file_path))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Ошибка при добавлении карточки пользователю {user_id}: {e}")
            return None

    def get_user_cards(self, user_id, unsold_only=True):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                if unsold_only:
                    cursor.execute('''
                        SELECT * FROM user_cards 
                        WHERE user_id = ? AND is_sold = 0 
                        ORDER BY obtained_at DESC
                    ''', (user_id,))
                else:
                    cursor.execute('''
                        SELECT * FROM user_cards 
                        WHERE user_id = ? 
                        ORDER BY obtained_at DESC
                    ''', (user_id,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении карточек пользователя {user_id}: {e}")
            return []

    def sell_card(self, card_id, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT rarity FROM user_cards 
                    WHERE id = ? AND user_id = ? AND is_sold = 0
                ''', (card_id, user_id))
                card = cursor.fetchone()

                if card:
                    cursor.execute('''
                        UPDATE user_cards 
                        SET is_sold = 1 
                        WHERE id = ? AND user_id = ?
                    ''', (card_id, user_id))
                    return card['rarity']
                return None
        except Exception as e:
            logger.error(f"Ошибка при продаже карточки {card_id}: {e}")
            return None

    def get_card_count(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) as count 
                    FROM user_cards 
                    WHERE user_id = ? AND is_sold = 0
                ''', (user_id,))
                result = cursor.fetchone()
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Ошибка при получении количества карточек {user_id}: {e}")
            return 0

    # === ТОП ===

    def get_top_players(self, limit=10):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 
                        u.user_id,
                        u.username,
                        u.balance,
                        COUNT(uc.id) as card_count
                    FROM users u
                    LEFT JOIN user_cards uc ON u.user_id = uc.user_id AND uc.is_sold = 0
                    GROUP BY u.user_id
                    ORDER BY u.balance DESC, card_count DESC
                    LIMIT ?
                ''', (limit,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении топа игроков: {e}")
            return []

    # === ПРЕДЛОЖЕНИЯ ===

    def add_suggested_card(self, user_id, file_path):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO suggested_cards (user_id, file_path)
                    VALUES (?, ?)
                ''', (user_id, file_path))
                return cursor.lastrowid
        except Exception as e:
            logger.error(f"Ошибка при добавлении предложения от {user_id}: {e}")
            return None

    def get_pending_suggestions(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM suggested_cards 
                    WHERE status = 'pending'
                    ORDER BY submitted_at ASC
                ''')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении списка предложений: {e}")
            return []

    def approve_suggestion(self, suggestion_id, admin_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE suggested_cards 
                    SET status = 'approved', reviewed_by = ?, reviewed_at = ?
                    WHERE id = ?
                ''', (admin_id, datetime.now(), suggestion_id))

                cursor.execute('SELECT user_id FROM suggested_cards WHERE id = ?', (suggestion_id,))
                result = cursor.fetchone()
                if result:
                    user_id = result['user_id']
                    self.add_balance_history(user_id, 500, 'card_suggestion')
                    self.update_balance(user_id, 500)
                    return user_id
                return None
        except Exception as e:
            logger.error(f"Ошибка при одобрении предложения {suggestion_id}: {e}")
            return None

    def reject_suggestion(self, suggestion_id, admin_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE suggested_cards 
                    SET status = 'rejected', reviewed_by = ?, reviewed_at = ?
                    WHERE id = ?
                ''', (admin_id, datetime.now(), suggestion_id))
        except Exception as e:
            logger.error(f"Ошибка при отклонении предложения {suggestion_id}: {e}")

    # === ИСТОРИЯ БАЛАНСА ===

    def add_balance_history(self, user_id, amount, reason):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO balance_history (user_id, amount, reason)
                    VALUES (?, ?, ?)
                ''', (user_id, amount, reason))
        except Exception as e:
            logger.error(f"Ошибка при добавлении истории баланса {user_id}: {e}")

    # === БЛОКИРОВКИ ===

    def is_user_blocked(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM blocked_users WHERE user_id = ?', (user_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке блокировки {user_id}: {e}")
            return False

    def block_user(self, user_id, username, blocked_by, reason="Не указана"):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO blocked_users (user_id, username, blocked_by, reason)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, username, blocked_by, reason))
        except Exception as e:
            logger.error(f"Ошибка при блокировке {user_id}: {e}")

    def unblock_user(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM blocked_users WHERE user_id = ?', (user_id,))
        except Exception as e:
            logger.error(f"Ошибка при разблокировке {user_id}: {e}")

    def get_blocked_users(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM blocked_users ORDER BY blocked_at DESC')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении списка заблокированных: {e}")
            return []

    # === АДМИНЫ ===

    def add_admin(self, user_id, username):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)',
                               (user_id, username))
        except Exception as e:
            logger.error(f"Ошибка при добавлении админа {user_id}: {e}")

    def remove_admin(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM admins WHERE user_id = ?', (user_id,))
        except Exception as e:
            logger.error(f"Ошибка при удалении админа {user_id}: {e}")

    def is_admin(self, user_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
                return cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Ошибка при проверке админа {user_id}: {e}")
            return False

    def get_admins(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM admins')
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении списка админов: {e}")
            return []

    # === СТАТИСТИКА ===

    def get_user_stats(self, user_id=None):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                if user_id:
                    cursor.execute('''
                        SELECT 
                            u.user_id,
                            u.username,
                            u.balance,
                            COUNT(uc.id) as total_cards,
                            SUM(CASE WHEN uc.is_sold = 1 THEN 1 ELSE 0 END) as sold_cards,
                            SUM(CASE WHEN uc.is_sold = 0 THEN 1 ELSE 0 END) as active_cards,
                            u.created_at
                        FROM users u
                        LEFT JOIN user_cards uc ON u.user_id = uc.user_id
                        WHERE u.user_id = ?
                        GROUP BY u.user_id
                    ''', (user_id,))
                    return cursor.fetchone()
                else:
                    cursor.execute('SELECT COUNT(*) as total_users FROM users')
                    total_users = cursor.fetchone()['total_users']

                    cursor.execute('SELECT COUNT(*) as blocked_users FROM blocked_users')
                    blocked_users = cursor.fetchone()['blocked_users']

                    cursor.execute('SELECT SUM(balance) as total_balance FROM users')
                    result = cursor.fetchone()
                    total_balance = result['total_balance'] if result and result['total_balance'] else 0

                    cursor.execute('SELECT COUNT(*) as total_cards FROM user_cards')
                    total_cards = cursor.fetchone()['total_cards']

                    cursor.execute('SELECT COUNT(*) as active_cards FROM user_cards WHERE is_sold = 0')
                    active_cards = cursor.fetchone()['active_cards']

                    cursor.execute('SELECT COUNT(*) as rarities_count FROM rarities')
                    rarities_count = cursor.fetchone()['rarities_count']

                    return {
                        'total_users': total_users,
                        'blocked_users': blocked_users,
                        'total_balance': total_balance,
                        'total_cards': total_cards,
                        'active_cards': active_cards,
                        'rarities_count': rarities_count
                    }
        except Exception as e:
            logger.error(f"Ошибка при получении статистики: {e}")
            return {
                'total_users': 0,
                'blocked_users': 0,
                'total_balance': 0,
                'total_cards': 0,
                'active_cards': 0,
                'rarities_count': 0
            }

    def search_users(self, search_term):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_id, username, balance, created_at 
                    FROM users 
                    WHERE username LIKE ? OR user_id LIKE ?
                    LIMIT 20
                ''', (f'%{search_term}%', f'%{search_term}%'))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при поиске пользователей: {e}")
            return []

    # === РАССЫЛКИ ===

    def add_mailing_history(self, admin_id, message_text, recipients_count):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO mailing_history (admin_id, message_text, recipients_count)
                    VALUES (?, ?, ?)
                ''', (admin_id, message_text, recipients_count))
        except Exception as e:
            logger.error(f"Ошибка при добавлении истории рассылки: {e}")

    def get_mailing_history(self, limit=10):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM mailing_history 
                    ORDER BY sent_at DESC 
                    LIMIT ?
                ''', (limit,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении истории рассылок: {e}")
            return []

    # === ТОП ЛЕГЕНД ===

    def start_new_legend_period(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now()
                period_start = now - timedelta(days=3)
                period_end = now

                cursor.execute('''
                    SELECT user_id, SUM(amount) as total_earned
                    FROM balance_history
                    WHERE created_at > ? AND amount > 0
                    GROUP BY user_id
                    ORDER BY total_earned DESC
                    LIMIT 1
                ''', (period_start,))

                winner = cursor.fetchone()

                if winner:
                    cursor.execute('''
                        INSERT INTO legend_top (user_id, period_start, period_end, balance_earned, legend_points)
                        VALUES (?, ?, ?, ?, 1)
                    ''', (winner['user_id'], period_start, period_end, winner['total_earned']))
        except Exception as e:
            logger.error(f"Ошибка при запуске нового периода легенд: {e}")

    def get_legend_top(self, limit=10):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT 
                        u.user_id,
                        u.username,
                        SUM(lt.legend_points) as total_points,
                        COUNT(lt.id) as periods_won
                    FROM legend_top lt
                    JOIN users u ON lt.user_id = u.user_id
                    GROUP BY lt.user_id
                    ORDER BY total_points DESC
                    LIMIT ?
                ''', (limit,))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"Ошибка при получении топа легенд: {e}")
            return []

    def reset_balances(self):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute('SELECT user_id, balance FROM users WHERE balance > 0')
                users = cursor.fetchall()

                for user in users:
                    self.add_balance_history(
                        user['user_id'],
                        -user['balance'],
                        'periodic_reset'
                    )

                cursor.execute('UPDATE users SET balance = 0')
                self.start_new_legend_period()
        except Exception as e:
            logger.error(f"Ошибка при обнулении балансов: {e}")