import discord
import os
import asyncio
import logging
import logging.handlers
from discord.ext import commands
from dotenv import load_dotenv

# 로그 디렉토리 자동 생성
os.makedirs('logs', exist_ok=True)

# 로깅 설정
logger = logging.getLogger('musicBot')
logger.setLevel(logging.INFO)

formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(name)s: %(message)s')

file_handler = logging.handlers.RotatingFileHandler(
    filename='logs/bot.log',
    encoding='utf-8',
    maxBytes=5*1024*1024,
    backupCount=5
)
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 환경 변수 로드
load_dotenv()
TOKEN = os.getenv('MUSIC_BOT_TOKEN') # 기존 봇과 다른 토큰 사용

# 봇 설정
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.event
async def setup_hook():
    await bot.tree.sync()
    logger.info("음악 봇 슬래시 명령어 동기화 완료!")

@bot.event
async def on_ready():
    logger.info(f'🎵 Music Bot Logged in as: {bot.user.name} ({bot.user.id})')

async def main():
    async with bot:
        # music cog 로드
        await bot.load_extension('cogs.music')
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
