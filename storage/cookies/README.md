# YouTube Cookies Setup

## Why cookies are needed
YouTube now requires authentication for some videos, especially:
- Music tracks
- DRM protected content
- Age-restricted videos
- Videos from certain regions

## Export Cookies from Firefox

### Method 1: Using yt-dlp (Recommended)
```bash
# Make sure you're logged into YouTube in Firefox
yt-dlp --cookies-from-browser firefox --cookies storage/cookies/youtube_cookies.txt "https://www.youtube.com/"
```

### Method 2: Using Browser Extension
1. Install "cookies.txt" extension for Firefox:
   https://addons.mozilla.org/en-US/firefox/addon/cookies-txt/

2. Go to https://www.youtube.com and make sure you're logged in
3. Click the extension icon and download cookies.txt
4. Rename and move the file:
   ```bash
   mv ~/Downloads/cookies.txt storage/cookies/youtube_cookies.txt
   ```

## Verify
```bash
ls -la storage/cookies/youtube_cookies.txt
```

## Notes
- Cookies expire every few weeks - re-export when needed
- Keep cookies file private (it's in .gitignore)
- The bot will auto-detect and use cookies when available
