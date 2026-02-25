import discord
import asyncio
import yt_dlp
import logging
from discord.ext import commands

logger = logging.getLogger('musicBot.music')

# yt-dlp 옵션 설정
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

# FFmpeg 옵션 설정
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

class MusicPlayerView(discord.ui.View):
    """음악 컨트롤 버튼이 포함된 뷰"""
    def __init__(self, cog, ctx):
        super().__init__(timeout=None)
        self.cog = cog
        self.ctx = ctx

    @discord.ui.button(label="⏮️ 이전곡", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        history = self.cog.history.get(guild_id, [])
        
        if not history:
            return await interaction.response.send_message("이전 곡 기록이 없습니다.", ephemeral=True)
        
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            # 현재 곡을 대기열 맨 앞으로 보냄 (원한다면)
            # 여기서는 단순히 이전 곡을 재생하는 로직
            prev_song = history.pop()
            current_song = self.cog.current_song.get(guild_id)
            if current_song:
                self.cog.queue[guild_id].insert(0, current_song)
            
            self.cog.queue[guild_id].insert(0, prev_song)
            vc.stop() # after_playing이 호출되면서 다음 곡(여기서는 이전 곡) 재생
            await interaction.response.send_message("⏮️ 이전 곡으로 돌아갑니다.", ephemeral=True)
        else:
            await interaction.response.send_message("현재 재생 중이 아닙니다.", ephemeral=True)

    @discord.ui.button(label="⏯️ 재생/일시정지", style=discord.ButtonStyle.primary)
    async def toggle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("음성 채널에 있지 않습니다.", ephemeral=True)
            
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ 일시정지되었습니다.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ 재생을 재개합니다.", ephemeral=True)
        else:
            await interaction.response.send_message("재생 중인 곡이 없습니다.", ephemeral=True)

    @discord.ui.button(label="⏭️ 다음곡", style=discord.ButtonStyle.secondary)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏭️ 다음 곡으로 넘어갑니다.", ephemeral=True)
        else:
            await interaction.response.send_message("건너뛸 곡이 없습니다.", ephemeral=True)

    @discord.ui.button(label="📋 대기열", style=discord.ButtonStyle.secondary)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_id = interaction.guild_id
        queue = self.cog.queue.get(guild_id, [])
        
        if not queue:
            return await interaction.response.send_message("대기열이 비어 있습니다.", ephemeral=True)
            
        embed = discord.Embed(title="📋 현재 대기열", color=discord.Color.blue())
        desc = ""
        for i, song in enumerate(queue[:10], 1):
            desc += f"{i}. {song['title']}\n"
        if len(queue) > 10:
            desc += f"...외 {len(queue)-10}곡"
        
        embed.description = desc
        await interaction.response.send_message(embed=embed, ephemeral=True)

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = {} # guild_id: [songs]
        self.history = {} # guild_id: [played_songs]
        self.current_song = {} # guild_id: song
        self.is_playing = {}

    async def check_queue(self, ctx):
        guild_id = ctx.guild.id
        if guild_id in self.queue and len(self.queue[guild_id]) > 0:
            song = self.queue[guild_id].pop(0)
            await self.play_music(ctx, song)
        else:
            self.is_playing[guild_id] = False
            self.current_song[guild_id] = None

    async def play_music(self, ctx, song):
        guild_id = ctx.guild.id
        self.is_playing[guild_id] = True
        
        # 현재 곡을 이력에 추가 (이전 곡이 있었다면)
        if self.current_song.get(guild_id):
            if guild_id not in self.history:
                self.history[guild_id] = []
            self.history[guild_id].append(self.current_song[guild_id])
            if len(self.history[guild_id]) > 20: # 이력은 최근 20곡까지만
                self.history[guild_id].pop(0)

        self.current_song[guild_id] = song
        
        vc = ctx.voice_client
        if not vc:
            if ctx.author.voice:
                await ctx.author.voice.channel.connect()
                vc = ctx.voice_client
            else:
                return await ctx.send("❌ 먼저 음성 채널에 접속해 주세요!")

        source = await discord.FFmpegOpusAudio.from_probe(song['url'], **FFMPEG_OPTIONS)
        
        def after_playing(error):
            coro = self.check_queue(ctx)
            asyncio.run_coroutine_threadsafe(coro, self.bot.loop)

        vc.play(source, after=after_playing)
        
        # 플레이어 Embed 생성
        embed = discord.Embed(
            title="🎵 지금 재생 중",
            description=f"[{song['title']}]({song.get('webpage_url', '')})",
            color=discord.Color.green()
        )
        if song.get('thumbnail'):
            embed.set_image(url=song['thumbnail'])
            
        embed.add_field(name="재생 시간", value=self.format_duration(song.get('duration', 0)), inline=True)
        embed.add_field(name="신청자", value=ctx.author.display_name, inline=True)
        
        await ctx.send(embed=embed, view=MusicPlayerView(self, ctx))

    def format_duration(self, seconds):
        if not seconds: return "알 수 없음"
        mins, secs = divmod(seconds, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            return f"{hours:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    @commands.hybrid_command(name="유튜브", aliases=["play", "p"], description="유튜브 검색 및 재생을 수행합니다.")
    async def play(self, ctx, *, search: str):
        if not ctx.author.voice:
            return await ctx.send("❌ 먼저 음성 채널에 접속해 주세요!")

        async with ctx.typing():
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                try:
                    info = ydl.extract_info(f"ytsearch:{search}", download=False)['entries'][0]
                    song = {
                        'url': info['url'],
                        'title': info['title'],
                        'thumbnail': info.get('thumbnail'),
                        'duration': info.get('duration'),
                        'webpage_url': info.get('webpage_url')
                    }
                except Exception as e:
                    return await ctx.send(f"❌ 검색 중 오류가 발생했습니다: {e}")

            guild_id = ctx.guild.id
            if guild_id not in self.queue:
                self.queue[guild_id] = []
            
            if self.is_playing.get(guild_id):
                self.queue[guild_id].append(song)
                await ctx.send(f"📂 **대기열 추가:** {song['title']}")
            else:
                await self.play_music(ctx, song)

    @commands.hybrid_command(name="건너뛰기", aliases=["skip", "s"], description="현재 재생 중인 곡을 건너뜁니다.")
    async def skip(self, ctx):
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ 곡을 건너뛰었습니다.")
        else:
            await ctx.send("❌ 현재 재생 중인 곡이 없습니다.")

    @commands.hybrid_command(name="정지", aliases=["stop"], description="재생을 중지하고 채널에서 나갑니다.")
    async def stop(self, ctx):
        if ctx.voice_client:
            self.queue[ctx.guild.id] = []
            self.history[ctx.guild.id] = []
            self.current_song[ctx.guild.id] = None
            await ctx.voice_client.disconnect()
            await ctx.send("👋 재생을 중지하고 채널에서 나갔습니다.")
        else:
            await ctx.send("❌ 봇이 이미 음성 채널에 있지 않습니다.")

    @commands.hybrid_command(name="대기열", aliases=["queue", "q"], description="현재 재생 대기열 목록을 확인합니다.")
    async def queue_list(self, ctx):
        guild_id = ctx.guild.id
        queue = self.queue.get(guild_id, [])
        
        if not queue:
            return await ctx.send("📋 대기열이 비어 있습니다.")
            
        embed = discord.Embed(title="📋 현재 대기열", color=discord.Color.blue())
        desc = ""
        for i, song in enumerate(queue[:10], 1):
            desc += f"{i}. {song['title']}\n"
        if len(queue) > 10:
            desc += f"...외 {len(queue)-10}곡"
        
        embed.description = desc
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Music(bot))
