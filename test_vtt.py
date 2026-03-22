import yt_dlp
import asyncio
import aiohttp
import re
import traceback

YDL_OPTIONS = {
    'noplaylist': True,
    'quiet': True,
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitleslangs': ['ko', 'en']
}

async def fetch_and_parse_vtt(url):
    if not url:
        return []
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
        print(f"Subtitle parse error: {e}")
        traceback.print_exc()
        return []

async def main():
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info("https://www.youtube.com/watch?v=UasQNGlw0xY&list=RDUasQNGlw0xY&start_radio=1", download=False) # Despacito
        sub_url = None
        
        subs = info.get('subtitles', {})
        auto_subs = info.get('automatic_captions', {})
        print("Available subtitles:", list(subs.keys()))
        print("Available auto_subs:", list(auto_subs.keys()))
        
        for lang in ['ko', 'en', 'es']: # Adding Spanish for Despacito
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

        print(f"Sub URL: {sub_url}")
        
        if sub_url:
            parsed = await fetch_and_parse_vtt(sub_url)
            print(f"Parsed {len(parsed)} subtitle blocks.")
            for s in parsed[:5]:
                print(s)

if __name__ == '__main__':
    asyncio.run(main())
