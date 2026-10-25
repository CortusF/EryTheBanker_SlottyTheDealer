import aiosqlite
import json
from datetime import datetime, timedelta


class EconomyDatabase:
    def __init__(self, db_path: str = "economy.db"):
        self.db_path = db_path

    async def initialize(self):
        """Инициализация БД с поддержкой автоматических миграций"""
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Создание таблиц (IF NOT EXISTS сохраняет данные)
            await db.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY, 
                smith_tokens INTEGER DEFAULT 0, 
                gems INTEGER DEFAULT 0,
                last_work TIMESTAMP, 
                last_salary TIMESTAMP, 
                last_pinata TIMESTAMP, 
                last_mine TIMESTAMP,
                last_mail TIMESTAMP, 
                has_lucky_token INTEGER DEFAULT 0, 
                achievements TEXT DEFAULT '[]', 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")

            await db.execute("""CREATE TABLE IF NOT EXISTS items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT, 
                user_id INTEGER, 
                item_name TEXT NOT NULL,
                quantity INTEGER DEFAULT 1, 
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")

            await db.execute("""CREATE TABLE IF NOT EXISTS role_salaries (
                role_id INTEGER PRIMARY KEY, 
                role_name TEXT NOT NULL, 
                salary_amount INTEGER DEFAULT 0
            )""")

            await db.execute("""CREATE TABLE IF NOT EXISTS shop_items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT, 
                item_name TEXT NOT NULL UNIQUE,
                description TEXT, 
                price INTEGER NOT NULL, 
                is_permanent INTEGER DEFAULT 0, 
                is_available INTEGER DEFAULT 1
            )""")

            await db.execute("""CREATE TABLE IF NOT EXISTS rps_games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                challenger_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                bet INTEGER NOT NULL,
                challenger_move TEXT NOT NULL,
                target_move TEXT,
                winner_id INTEGER,
                status TEXT DEFAULT 'pending'
            )""")

            await db.execute("""CREATE TABLE IF NOT EXISTS loans (
                loan_id INTEGER PRIMARY KEY AUTOINCREMENT, 
                user_id INTEGER NOT NULL,
                initial_amount INTEGER NOT NULL, 
                current_debt INTEGER NOT NULL,
                interest_rate REAL DEFAULT 0.15, 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                due_date TIMESTAMP NOT NULL, 
                is_active INTEGER DEFAULT 1,
                last_payment_at TIMESTAMP, 
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )""")

            await db.execute("""CREATE TABLE IF NOT EXISTS user_penalties (
                user_id INTEGER PRIMARY KEY, 
                role_id INTEGER NOT NULL, 
                expire_at TIMESTAMP NOT NULL
            )""")

            # 2. Безопасные миграции (добавление колонок для старых БД)
            new_columns = [
                ("users", "last_mail", "TIMESTAMP"),
                ("users", "has_lucky_token", "INTEGER DEFAULT 0"),
                ("users", "achievements", "TEXT DEFAULT '[]'")
            ]

            for table, col, dtype in new_columns:
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
                except Exception:
                    pass  # Колонка уже существует, игнорируем ошибку

            # 3. Инициализация товаров магазина
            initial_items = [
                ('Шахта', 'Перманентный инструмент для добычи гемов.', 5000, 1),
                ('Шахтеры', 'Перманентная бригада для рискованных ставок.', 30, 1),
                ('Сломанные часы', 'Сбрасывает кулдаун одной команды.', 10, 0)
            ]
            for name, desc, price, perm in initial_items:
                await db.execute(
                    "INSERT OR IGNORE INTO shop_items (item_name, description, price, is_permanent) VALUES (?, ?, ?, ?)",
                    (name, desc, price, perm)
                )

            await db.commit()

    # --- Управление пользователями и балансом ---

    async def create_user(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()

    async def get_user(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            if row:
                return {
                    'user_id': row[0], 'smith_tokens': row[1], 'gems': row[2],
                    'last_work': row[3], 'last_salary': row[4], 'last_pinata': row[5],
                    'last_mine': row[6], 'last_mail': row[7], 'has_lucky_token': row[8],
                    'achievements': row[9]
                }
            return None

    async def update_smith_tokens(self, user_id: int, amount: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET smith_tokens = COALESCE(smith_tokens, 0) + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()

    async def update_gems(self, user_id: int, amount: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET gems = COALESCE(gems, 0) + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()

    async def update_last(self, user_id: int, field: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE users SET {field} = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
            await db.commit()

    # --- Кулдауны и Почта ---

    async def check_cooldown(self, user_id: int, field: str, cooldown_seconds: int):
        user = await self.get_user(user_id)
        if not user:
            await self.create_user(user_id)
            return True, None

        last_time_str = user.get(field)
        if not last_time_str:
            return True, None

        last_time = datetime.fromisoformat(last_time_str)
        elapsed = (datetime.now() - last_time).total_seconds()

        if elapsed >= cooldown_seconds:
            return True, None

        remaining = cooldown_seconds - elapsed
        h, m, s = int(remaining // 3600), int((remaining % 3600) // 60), int(remaining % 60)
        return False, f"{h}ч {m}м {s}с"

    async def check_mail_cooldown(self, user_id: int):
        return await self.check_cooldown(user_id, 'last_mail', 24 * 3600)

    async def update_last_mail(self, user_id: int):
        await self.update_last(user_id, 'last_mail')

    # --- Инвентарь и Предметы ---

    async def has_item(self, user_id: int, item_name: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT quantity FROM items WHERE user_id = ? AND item_name = ?",
                (user_id, item_name)
            )
            row = await cursor.fetchone()
            return row is not None and row[0] > 0

    async def remove_item(self, user_id: int, item_name: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE items SET quantity = quantity - 1 WHERE user_id = ? AND item_name = ? AND quantity > 0",
                (user_id, item_name)
            )
            await db.commit()

    async def reset_cooldown(self, user_id: int, field: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(f"UPDATE users SET {field} = NULL WHERE user_id = ?", (user_id,))
            await db.commit()

    # --- Магазин ---

    async def get_shop_items(self):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT * FROM shop_items WHERE is_available = 1")
            return await cursor.fetchall()

    async def buy_item(self, user_id: int, item_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM shop_items WHERE item_id = ? AND is_available = 1", (item_id,)
            )
            item = await cursor.fetchone()
            if not item:
                return False, "Предмет не найден"

            _, name, _, price, is_perm, _ = item

            # Определение валюты по названию предмета
            is_gem_item = name in ["Шахтеры", "Сломанные часы"]

            if is_gem_item:
                cursor = await db.execute("SELECT gems FROM users WHERE user_id = ?", (user_id,))
                user = await cursor.fetchone()
                currency_name = "гемов"
            else:
                cursor = await db.execute("SELECT smith_tokens FROM users WHERE user_id = ?", (user_id,))
                user = await cursor.fetchone()
                currency_name = "смиттокенов"

            if not user or user[0] < price:
                return False, f"Недостаточно {currency_name}. Нужно: {price}"

            if is_perm:
                cursor = await db.execute(
                    "SELECT quantity FROM items WHERE user_id = ? AND item_name = ?",
                    (user_id, name)
                )
                if await cursor.fetchone():
                    return False, f"У вас уже есть '{name}'"

            # Списание средств
            if is_gem_item:
                await db.execute("UPDATE users SET gems = gems - ? WHERE user_id = ?", (price, user_id))
            else:
                await db.execute("UPDATE users SET smith_tokens = smith_tokens - ? WHERE user_id = ?", (price, user_id))

            # Добавление в инвентарь
            cursor = await db.execute(
                "SELECT quantity FROM items WHERE user_id = ? AND item_name = ?",
                (user_id, name)
            )
            if await cursor.fetchone():
                await db.execute(
                    "UPDATE items SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?",
                    (user_id, name)
                )
            else:
                await db.execute(
                    "INSERT INTO items (user_id, item_name, quantity) VALUES (?, ?, 1)",
                    (user_id, name)
                )

            await db.commit()
            return True, f"Вы купили '{name}' за {price} {currency_name}!"

    # --- Зарплаты ---

    async def add_role_salary(self, role_id: int, name: str, amount: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO role_salaries VALUES (?, ?, ?)",
                (role_id, name, amount)
            )
            await db.commit()

    async def get_role_salary(self, role_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT salary_amount FROM role_salaries WHERE role_id = ?", (role_id,)
            )
            row = await cursor.fetchone()
            return row[0] if row else 0

    # --- Кредиты ---

    async def create_loan(self, user_id: int, amount: int):
        total_repay = int(amount * 1.15)
        due_date = datetime.now() + timedelta(hours=96)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO loans (user_id, initial_amount, current_debt, due_date) VALUES (?, ?, ?, ?)",
                (user_id, amount, total_repay, due_date.isoformat())
            )
            await db.execute(
                "UPDATE users SET smith_tokens = smith_tokens + ? WHERE user_id = ?",
                (amount, user_id)
            )
            await db.commit()
        return total_repay, due_date

    async def get_active_loans(self, user_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM loans WHERE user_id = ? AND is_active = 1", (user_id,)
            )
            return await cursor.fetchall()

    async def make_partial_payment(self, loan_id: int, user_id: int, payment_amount: int):
        """
        Принимает произвольную сумму платежа.
        Возвращает: (успех, сообщение, новый_долг, новая_дата)
        """
        import math
        from datetime import datetime, timedelta

        async with aiosqlite.connect(self.db_path) as db:
            # Получаем данные кредита
            cursor = await db.execute(
                "SELECT current_debt, initial_amount FROM loans WHERE loan_id = ? AND user_id = ? AND is_active = 1",
                (loan_id, user_id)
            )
            loan = await cursor.fetchone()

            if not loan:
                return False, "Кредит не найден или уже закрыт", 0, None

            current_debt, initial_amount = loan

            # Проверяем, что платеж в допустимых границах (дублируем проверку из команды для безопасности)
            min_payment = max(1, initial_amount // 8)
            if payment_amount < min_payment or payment_amount > current_debt:
                return False, f"Платеж должен быть от {min_payment} до {current_debt}", current_debt, None

            # Рассчитываем комиссию 5% от ВНОСИМОЙ суммы
            fee = math.ceil(payment_amount * 0.05)
            total_cost = payment_amount + fee

            # Проверяем баланс пользователя
            cursor = await db.execute("SELECT smith_tokens FROM users WHERE user_id = ?", (user_id,))
            tokens_row = await cursor.fetchone()
            user_balance = tokens_row[0] if tokens_row else 0

            if user_balance < total_cost:
                return False, f"Недостаточно средств. Нужно: {total_cost} (платеж {payment_amount} + комиссия {fee})", current_debt, None

            # Выполняем транзакцию
            new_debt = current_debt - payment_amount
            if new_debt < 0:
                new_debt = 0  # Не уходим в минус

            new_due_date = datetime.now() + timedelta(hours=96)

            # Списываем средства
            await db.execute("UPDATE users SET smith_tokens = smith_tokens - ? WHERE user_id = ?",
                             (total_cost, user_id))

            if new_debt == 0:
                # Кредит полностью погашен
                await db.execute("UPDATE loans SET is_active = 0, current_debt = 0 WHERE loan_id = ?", (loan_id,))
            else:
                # Частичное погашение - сбрасываем таймер на 96ч
                await db.execute(
                    "UPDATE loans SET current_debt = ?, due_date = ?, last_payment_at = CURRENT_TIMESTAMP WHERE loan_id = ?",
                    (new_debt, new_due_date.isoformat(), loan_id)
                )

            await db.commit()

            # Формируем сообщение
            if new_debt == 0:
                msg = f"✅ Кредит полностью погашен!\nВнесено: {payment_amount}\nКомиссия: {fee}\nИтого списано: {total_cost}"
            else:
                msg = f"✅ Платеж принят\nВнесено: {payment_amount}\nКомиссия: {fee}\nИтого списано: {total_cost}\nОстаток долга: {new_debt}"

            return True, msg, new_debt, new_due_date if new_debt > 0 else None

    async def apply_penalty(self, loan_id: int):
        import math
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT current_debt FROM loans WHERE loan_id = ? AND is_active = 1", (loan_id,)
            )
            row = await cursor.fetchone()
            if row:
                new_debt = math.ceil(row[0] * 1.10)
                await db.execute(
                    "UPDATE loans SET current_debt = ? WHERE loan_id = ?",
                    (new_debt, loan_id)
                )
                await db.commit()
                return new_debt
        return 0

    async def force_collect_debt(self, user_id: int, debt_amount: int, penalty_role_id: int):
        import math
        from config import GUILD_ID

        async with aiosqlite.connect(self.db.db_path) as db:
            # Принудительно списываем 1/8 от ТЕКУЩЕГО долга + комиссия
            part = math.ceil(debt_amount / 8)
            fee = math.ceil(part * 0.05)
            total_to_take = part + fee

            cursor = await db.execute("SELECT smith_tokens FROM users WHERE user_id = ?", (user_id,))
            row = await cursor.fetchone()
            current_balance = row[0] if row else 0

            new_balance = current_balance - total_to_take

            # Списываем средства
            await db.execute("UPDATE users SET smith_tokens = ? WHERE user_id = ?", (new_balance, user_id))

            # Уменьшаем долг на сумму основного платежа (без комиссии)
            await db.execute(
                "UPDATE loans SET current_debt = current_debt - ? WHERE user_id = ? AND is_active = 1",
                (part, user_id)
            )

            # Управление штрафной ролью
            guild = self.bot.get_guild(GUILD_ID) if hasattr(self, 'bot') else None
            if guild:
                member = guild.get_member(user_id)
                if member:
                    role = guild.get_role(penalty_role_id)
                    if role:
                        if new_balance < 0:
                            if role not in member.roles:
                                await member.add_roles(role)
                                expire_time = datetime.now() + timedelta(days=7)
                                await db.execute(
                                    "INSERT OR REPLACE INTO user_penalties VALUES (?, ?, ?)",
                                    (user_id, penalty_role_id, expire_time.isoformat())
                                )
                        else:
                            if role in member.roles:
                                await member.remove_roles(role)
                                await db.execute("DELETE FROM user_penalties WHERE user_id = ?", (user_id,))

            await db.commit()
            return new_balance, total_to_take

    # --- Достижения ---

    async def get_achievements(self, user_id: int) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT achievements FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return []

    async def add_achievement(self, user_id: int, achievement_name: str):
        current = await self.get_achievements(user_id)
        if achievement_name not in current:
            current.append(achievement_name)
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE users SET achievements = ? WHERE user_id = ?",
                    (json.dumps(current), user_id)
                )
                await db.commit()

    async def has_achievement(self, user_id: int, achievement_name: str) -> bool:
        return achievement_name in await self.get_achievements(user_id)

    # --- Лидерборд ---

    async def get_top_users(self, currency: str, limit: int = 10):
        col = "smith_tokens" if currency == "tokens" else "gems"
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                f"SELECT user_id, {col} FROM users ORDER BY {col} DESC LIMIT ?",
                (limit,)
            )
            return await cursor.fetchall()

    # --- Счастливый жетон ---

    async def set_lucky_token(self, user_id: int, status: bool):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET has_lucky_token = ? WHERE user_id = ?",
                (1 if status else 0, user_id)
            )
            await db.commit()

    async def has_lucky_token(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT has_lucky_token FROM users WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return bool(row[0]) if row else False

    # --- Дуэли КНБ ---

    async def set_rps_challenge(self, challenger_id: int, target_id: int, bet: int, move: str):
        """Создает или обновляет вызов на дуэль"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO rps_games (challenger_id, target_id, bet, challenger_move, status) VALUES (?, ?, ?, ?, 'pending')",
                (challenger_id, target_id, bet, move)
            )
            await db.commit()

    async def get_rps_game(self, user_id: int):
        """Получает активную игру, где пользователь является целью ИЛИ инициатором"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT * FROM rps_games WHERE (target_id = ? OR challenger_id = ?) AND status = 'pending'",
                (user_id, user_id)
            )
            return await cursor.fetchone()

    async def resolve_rps_game(self, game_id: int, target_move: str, winner_id: int):
        """Завершает игру, переводит средства и очищает запись"""
        async with aiosqlite.connect(self.db_path) as db:
            # Сначала получаем данные игры для транзакции
            cursor = await db.execute("SELECT bet, challenger_id, target_id FROM rps_games WHERE id = ?", (game_id,))
            game = await cursor.fetchone()

            if not game: return

            bet, chall_id, targ_id = game

            if winner_id == 0:  # Ничья - ничего не переводим
                await db.execute("DELETE FROM rps_games WHERE id = ?", (game_id,))
            else:
                # Перевод средств победителю
                await db.execute(
                    "UPDATE users SET smith_tokens = smith_tokens + ? WHERE user_id = ?",
                    (bet, winner_id)
                )
                # Списание средств у проигравшего
                loser_id = chall_id if winner_id == targ_id else targ_id
                await db.execute(
                    "UPDATE users SET smith_tokens = smith_tokens - ? WHERE user_id = ?",
                    (bet, loser_id)
                )
                # Удаляем запись об игре
                await db.execute("DELETE FROM rps_games WHERE id = ?", (game_id,))

            await db.commit()

    async def cancel_rps_game(self, game_id: int):
        """Отменяет дуэль без перевода средств"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM rps_games WHERE id = ?", (game_id,))
            await db.commit()