import discord
from discord.ext import commands
import asyncio
import os
from dotenv import load_dotenv
from database import EconomyDatabase

# Загружаем переменные из .env ДО всего остального
load_dotenv()

# Читаем токены строго из окружения
TOKEN_ECONOMY = os.getenv("DISCORD_BOT_TOKEN_ECONOMY")
TOKEN_CASINO = os.getenv("DISCORD_BOT_TOKEN_CASINO")
MY_USER_ID = int(os.getenv("MY_USER_ID", 0))

# Общая база данных
db = EconomyDatabase()

# --- Бот 1: Экономист ---
intents_eco = discord.Intents.default()
intents_eco.message_content = True
intents_eco.members = True
bot_economy = commands.Bot(command_prefix="!", intents=intents_eco)

# --- Бот 2: Крупье ---
intents_cas = discord.Intents.default()
intents_cas.message_content = True
intents_cas.members = True
bot_casino = commands.Bot(command_prefix="!", intents=intents_cas)


async def load_cogs(bot, folder_name):
    """Загрузка команд из папки"""
    if not os.path.exists(folder_name):
        print(f"⚠️ Папка {folder_name} не найдена!")
        return

    for filename in os.listdir(folder_name):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                await bot.load_extension(f'{folder_name}.{filename[:-3]}')
                print(f'✅ [{bot.user.name}] Загружено: {filename}')
            except Exception as e:
                print(f'❌ [{bot.user.name}] Ошибка {filename}: {e}')


def print_guild_info(bot_name, guilds):
    """Вывод информации о серверах в консоль"""
    print(f"\n--- ️ Список серверов для {bot_name} ---")
    if not guilds:
        print("Бот пока не находится ни на одном сервере.")
    else:
        for guild in guilds:
            print(f"ID: {guild.id} | Название: {guild.name} | Участников: {guild.member_count}")
    print("----------------------------------\n")


@bot_economy.event
async def on_ready():
    print(f'🏦 Экономист {bot_economy.user} запущен!')
    print_guild_info("Экономист", bot_economy.guilds)

    await db.initialize()
    await load_cogs(bot_economy, 'commands_economy')

    # Добавляем команду проверки серверов только экономисту
    @bot_economy.tree.command(name="серверы", description="[Только для Кортуса] Показать список серверов")
    async def servers_list(interaction: discord.Interaction):
        if interaction.user.id != MY_USER_ID:
            await interaction.response.send_message("❌ Эта команда доступна только основателю.", ephemeral=True)
            return

        embed = discord.Embed(title="🖥️ Мои сервера", color=discord.Color.blue())
        desc = ""
        for g in bot_economy.guilds:
            desc += f"🔹 **{g.name}** (ID: `{g.id}`)\n   👥 Участников: {g.member_count}\n"

        if not desc:
            desc = "Пока нет серверов."

        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

    try:
        synced = await bot_economy.tree.sync()
        print(f"🏦 Синхронизировано {len(synced)} экономических команд")
    except Exception as e:
        print(f"Ошибка синхронизации экономики: {e}")


@bot_economy.event
async def on_member_join(member):
    await db.create_user(member.id)


@bot_casino.event
async def on_ready():
    print(f' Крупье {bot_casino.user} запущен!')
    print_guild_info("Крупье", bot_casino.guilds)

    await load_cogs(bot_casino, 'commands_casino')
    try:
        synced = await bot_casino.tree.sync()
        print(f"🎰 Синхронизировано {len(synced)} команд казино")
    except Exception as e:
        print(f"Ошибка синхронизации казино: {e}")


if __name__ == "__main__":
    # Проверка наличия токенов перед запуском
    if not TOKEN_ECONOMY or not TOKEN_CASINO:
        print("❌ ОШИБКА: Один из токенов не найден в .env!")
        if not TOKEN_ECONOMY: print("   -> Отсутствует DISCORD_BOT_TOKEN_ECONOMY")
        if not TOKEN_CASINO: print("   -> Отсутствует DISCORD_BOT_TOKEN_CASINO")
        print("   Проверь файл .env и перезапусти бота.")
    else:
        async def run_all():
            try:
                await asyncio.gather(
                    bot_economy.start(TOKEN_ECONOMY),
                    bot_casino.start(TOKEN_CASINO)
                )
            except Exception as e:
                print(f"Критическая ошибка при запуске: {e}")


        try:
            asyncio.run(run_all())
        except KeyboardInterrupt:
            print("\n🛑 Боты остановлены пользователем.")