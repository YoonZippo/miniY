import yt_dlp
import json

YDL_OPTIONS = {
    'noplaylist': True,
    'quiet': True,
    'writesubtitles': True,
    'writeautomaticsub': True,
    'subtitleslangs': ['ko', 'en']
}

def test_extract(url):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)
        sub_url = None
        subs = info.get('subtitles', {})
        auto_subs = info.get('automatic_captions', {})
        
        print(f"Title: {info.get('title')}")
        print(f"Has subs: {bool(subs)}")
        print(f"Has auto_subs: {bool(auto_subs)}")

        for lang in ['ko', 'en']:
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
        
        print(f"Extracted sub URL: {sub_url}")

test_extract("https://www.youtube.com/watch?v=oE5CvDBl9lw")
