import discord
import asyncio
import yt_dlp
import logging
import time
import aiohttp
import re
from discord.ext import commands, tasks

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
    'source_address': '0.0.0.0',
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitleslangs': ['ko', 'en', 'ja']
}

# FFmpeg 옵션 설정
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

class MusicSearchView(discord.ui.View):
    """유튜브 검색 결과를 보여주고 선택할 수 있는 뷰"""
    def __init__(self, cog, ctx, results):
        super().__init__(timeout=30)
        self.cog = cog
        self.ctx = ctx
        self.results = results
        self.selection = None

        # 버튼 생성 (1~len(results))
        for i in range(len(results)):
            button = discord.ui.Button(label=str(i+1), style=discord.ButtonStyle.secondary, custom_id=str(i))
            button.callback = self.make_callback(i)
            self.add_item(button)

    def make_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if interaction.user != self.ctx.author:
                return await interaction.response.send_message("❌ 검색한 사람만 선택할 수 있습니다.", ephemeral=True)
            
            self.selection = self.results[index]
            self.stop()
            await interaction.response.defer()
            await interaction.delete_original_response()
            await self.cog.add_to_queue_or_play(self.ctx, self.selection)
        return callback

    async def on_timeout(self):
        try:
            await self.ctx.send("🕒 선택 시간이 초과되었습니다.", delete_after=5)
        except:
            pass

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
        guild_id = interaction.guild_id
        if not vc:
            return await interaction.response.send_message("음성 채널에 있지 않습니다.", ephemeral=True)
            
        if vc.is_playing():
            vc.pause()
            self.cog.pause_times[guild_id] = time.time()
            await interaction.response.send_message("⏸️ 일시정지되었습니다.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            if self.cog.pause_times.get(guild_id):
                self.cog.pause_durations[guild_id] += time.time() - self.cog.pause_times[guild_id]
                self.cog.pause_times[guild_id] = 0
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
        self.last_controller_msg = {} # guild_id: discord.Message
        self.last_progress_msg = {} # guild_id: discord.Message
        
        self.start_times = {} # guild_id: start_time (float)
        self.pause_times = {} # guild_id: pause_time (float)
        self.pause_durations = {} # guild_id: total_pause_duration (float)
        self.subtitles = {} # guild_id: list of subtitle dicts

        self.update_controller.start()

    def cog_unload(self):
        self.update_controller.cancel()

    @tasks.loop(seconds=3)
    async def update_controller(self):
        try:
            for guild_id, prog_msg in list(self.last_progress_msg.items()):
                if not self.is_playing.get(guild_id):
                    continue
                    
                guild = self.bot.get_guild(guild_id)
                vc = guild.voice_client if guild else None
                # If paused, we still want to show progress, but we don't update time
                if not vc or (not vc.is_playing() and not vc.is_paused()):
                    continue
                    
                song = self.current_song.get(guild_id)
                if not song:
                    continue
                    
                start_time = self.start_times.get(guild_id, 0)
                pause_duration = self.pause_durations.get(guild_id, 0)
                if self.pause_times.get(guild_id):
                    elapsed = self.pause_times[guild_id] - start_time - pause_duration
                else:
                    elapsed = time.time() - start_time - pause_duration
                    
                duration = song.get('duration')
                if duration and int(duration) > 0:
                    duration_int = int(duration)
                    progress = int((elapsed / duration_int) * 15)
                    progress = max(0, min(15, progress))
                    bar = "▬" * progress + "🔘" + "▬" * (15 - progress)
                    time_str = f"{self.format_duration(elapsed)} / {self.format_duration(duration_int)}"
                else:
                    bar = "🔘▬▬▬▬▬▬▬▬▬▬▬▬▬▬"
                    time_str = f"{self.format_duration(elapsed)}"
                    
                current_sub = ""
                subs = self.subtitles.get(guild_id, [])
                for sub in subs:
                    # 여유 범위를 주어 컨트롤러 업데이트 주기 시점에 짧은 자막이 누락되지 않도록 보완
                    if sub['start'] - 1.0 <= elapsed <= sub['end'] + 2.0:
                        current_sub = sub['text']
                        break
                        
                if not prog_msg.embeds:
                    continue
                embed = prog_msg.embeds[0].copy()
                
                # Update progress field (it should be the first field)
                embed.set_field_at(0, name="재생 진행도", value=f"`{bar}`\n⏳ {time_str}", inline=False)
                
                if current_sub:
                    embed.description = f"💬 **자막:**\n{current_sub}"
                else:
                    embed.description = ""
                    
                try:
                    await prog_msg.edit(embed=embed)
                except discord.NotFound:
                    # 메시지가 삭제된 경우 추적에서 제외
                    self.last_progress_msg.pop(guild_id, None)
                except Exception as e:
                    logger.error(f"Message edit error: {e}")
                    pass
        except Exception as e:
            logger.error(f"update_controller total error: {e}")
                
    async def fetch_and_parse_vtt(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    text = await resp.text()
                    
            subs = []
            blocks = text.split('\n\n')
            for block in blocks:
                lines = block.strip().split('\n')
                if not lines: continue
                
                time_idx = -1
                for i, line in enumerate(lines):
                    if '-->' in line:
                        time_idx = i
                        break
                        
                if time_idx == -1: continue
                
                time_line = lines[time_idx]
                text_lines = lines[time_idx+1:]
                
                def parse_time(time_str):
                    parts = time_str.split(':')
                    if len(parts) == 3:
                        h, m, s = parts
                    elif len(parts) == 2:
                        h = 0; m, s = parts
                    else:
                        h = 0; m = 0; s = parts[0]
                    return int(h) * 3600 + int(m) * 60 + float(s)
                    
                times = time_line.split('-->')
                if len(times) == 2:
                    start_match = re.search(r'(\d+:\d{2}:\d{2}[\.,]\d+|\d{2}:\d{2}[\.,]\d+)', times[0])
                    end_match = re.search(r'(\d+:\d{2}:\d{2}[\.,]\d+|\d{2}:\d{2}[\.,]\d+)', times[1])
                    
                    if start_match and end_match:
                        start_str = start_match.group(1).replace(',', '.')
                        end_str = end_match.group(1).replace(',', '.')
                        start = parse_time(start_str)
                        end = parse_time(end_str)
                        
                        sub_text = re.sub(r'<[^>]+>', '', ' '.join(text_lines))
                        sub_text = sub_text.replace('&nbsp;', ' ').strip()
                        if sub_text:
                            subs.append({'start': start, 'end': end, 'text': sub_text})
            return subs
        except Exception as e:
            logger.error(f"Subtitle parse error: {e}")
            return []

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
        self.start_times[guild_id] = time.time()
        self.pause_times[guild_id] = 0
        self.pause_durations[guild_id] = 0
        self.subtitles[guild_id] = []
        
        if song.get('sub_url'):
            self.subtitles[guild_id] = await self.fetch_and_parse_vtt(song['sub_url'])
        
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
        
        await self.send_controller_message(ctx, song)

    async def send_controller_message(self, ctx, song):
        guild_id = ctx.guild.id
        
        # 이전 컨트롤러 메시지 삭제 시도 (선택 사항: 메시지 폭주 방지)
        if guild_id in self.last_controller_msg:
            try:
                await self.last_controller_msg[guild_id].delete()
            except:
                pass
                
        if guild_id in self.last_progress_msg:
            try:
                await self.last_progress_msg[guild_id].delete()
            except:
                pass

        # 플레이어 Embed 생성
        embed = discord.Embed(
            title="🎵 지금 재생 중",
            description=f"[{song['title']}]({song.get('webpage_url', '')})",
            color=discord.Color.green()
        )
        if song.get('thumbnail'):
            embed.set_image(url=song['thumbnail'])
            
        embed.add_field(name="재생 시간", value=self.format_duration(song.get('duration', 0)), inline=True)
        embed.add_field(name="신청자", value=ctx.author.display_name if hasattr(ctx.author, 'display_name') else "알 수 없음", inline=True)
        
        msg = await ctx.send(embed=embed, view=MusicPlayerView(self, ctx))
        self.last_controller_msg[guild_id] = msg
        
        # 진행도 및 자막 전용 Embed 생성
        prog_embed = discord.Embed(color=discord.Color.blue())
        prog_embed.add_field(name="재생 진행도", value="`🔘▬▬▬▬▬▬▬▬▬▬▬▬▬▬`\n⏳ 00:00 / 00:00", inline=False)
        prog_msg = await ctx.send(embed=prog_embed)
        self.last_progress_msg[guild_id] = prog_msg

    def format_duration(self, seconds):
        if not seconds: return "알 수 없음"
        seconds = int(seconds)
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
            # URL인지 검색어인지 확인
            if search.startswith("http"):
                with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                    try:
                        info = ydl.extract_info(search, download=False)
                        if 'entries' in info: # 플레이리스트인 경우
                            info = info['entries'][0]
                        song = self.parse_song_info(info)
                        await self.add_to_queue_or_play(ctx, song)
                    except Exception as e:
                        return await ctx.send(f"❌ 오류가 발생했습니다: {e}")
            else:
                # 최대 9개 검색 결과 추출
                search_options = YDL_OPTIONS.copy()
                search_options['noplaylist'] = True
                with yt_dlp.YoutubeDL(search_options) as ydl:
                    try:
                        entries = ydl.extract_info(f"ytsearch9:{search}", download=False)['entries']
                        if not entries:
                            return await ctx.send("🔍 검색 결과가 없습니다.")
                        
                        results = [self.parse_song_info(e) for e in entries]
                        
                        embed = discord.Embed(title=f"🔍 '{search}' 검색 결과", description="재생할 곡의 번호를 버튼으로 선택해 주세요.", color=discord.Color.blue())
                        for i, res in enumerate(results, 1):
                            embed.add_field(name=f"{i}. {res['title']}", value=f"시간: {self.format_duration(res['duration'])}", inline=False)
                        
                        await ctx.send(embed=embed, view=MusicSearchView(self, ctx, results))
                    except Exception as e:
                        return await ctx.send(f"❌ 검색 중 오류가 발생했습니다: {e}")

    @commands.hybrid_command(name="ㅇ", description="유튜브 검색 및 재생을 수행합니다.")
    async def play_alias_1(self, ctx, *, search: str): await self.play(ctx, search=search)

    @commands.hybrid_command(name="재생", description="유튜브 검색 및 재생을 수행합니다.")
    async def play_alias_2(self, ctx, *, search: str): await self.play(ctx, search=search)

    @commands.hybrid_command(name="노래", description="유튜브 검색 및 재생을 수행합니다.")
    async def play_alias_3(self, ctx, *, search: str): await self.play(ctx, search=search)

    def parse_song_info(self, info):
        sub_url = None
        subs = info.get('subtitles', {})
        auto_subs = info.get('automatic_captions', {})
        
        for lang in ['ko', 'en', 'ja']:
            if lang in subs:
                for fmt in subs[lang]:
                    if fmt.get('ext') == 'vtt':
                        sub_url = fmt.get('url')
                        break
                if sub_url: break
            if lang in auto_subs:
                for fmt in auto_subs[lang]:
                    if fmt.get('ext') == 'vtt':
                        sub_url = fmt.get('url')
                        break
                if sub_url: break

        return {
            'url': info['url'],
            'title': info['title'],
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration'),
            'webpage_url': info.get('webpage_url'),
            'sub_url': sub_url
        }

    async def add_to_queue_or_play(self, ctx, song):
        guild_id = ctx.guild.id
        if guild_id not in self.queue:
            self.queue[guild_id] = []
        
        if self.is_playing.get(guild_id):
            self.queue[guild_id].append(song)
            # 대기열 추가 시 메시지를 보내는 대신, 현재 재생 중인 컨트롤러를 아래로 다시 출력
            if guild_id in self.current_song:
                await self.send_controller_message(ctx, self.current_song[guild_id])
                # 알림용 임시 메시지
                await ctx.send(f"📂 **대기열 추가:** {song['title']}", delete_after=5)
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
