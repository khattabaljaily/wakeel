# Wakeel promo video

A 1:42 English motion-graphics ad for Wakeel (1920×1080, 30 fps, H.264 + AAC).

| File | What it is |
|---|---|
| `wakeel_ad.mp4` | The finished video with voice-over and music |
| `wakeel_ad.srt` | English subtitles, for feeds that autoplay muted |
| `poster.jpg` | A thumbnail frame |
| `source/` | Everything needed to change and re-render it |

## Script

1. **Hook**: Your business deserves great marketing. But every month, it's the same story.
2. **Problem**: Hours of brainstorming, endless revisions, expensive agencies, late posts.
3. **Meet Wakeel**: Your AI marketing manager.
4. **Brand kit**: learns your business, audience, tone, colours, fonts and logo.
5. **Content plan**: a month's strategy and every post, with captions, hashtags and posting times.
6. **Designs**: on-brand post designs for Instagram, Facebook and TikTok.
7. **Review**: the calendar, drag to reschedule, approvals, client review links.
8. **Publish**: one click or auto-publish.
9. **Teams**: one account, many companies.
10. **Call to action**: wakeel.enjaztechnology.com
11. **Credit**: A service provided by Enjaz Information Technology.

## Re-rendering

Run from `source/`, with `pip install kokoro-onnx soundfile playwright` and ffmpeg installed.

1. `vo.py`: voice-over with Kokoro (voice `am_michael`). It needs `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the kokoro-onnx releases, and writes `vo/*.wav`.
2. `timeline.py`: scene timings from the voice lengths (`timeline.json`, `timeline.js`).
3. `music.py`: the synthesized music bed and transition whooshes (`music.wav`).
4. `render.py`: renders `index.html` frame by frame in headless Chromium (`video_silent.mp4`). Open `index.html?play` in a browser to preview it live, or `index.html?t=42` to see one moment.
5. Mix and mux with ffmpeg: place each `vo/<scene>.wav` at its `vo` time, duck the music under the voice (sidechaincompress), loudnorm to -15 LUFS, then `ffmpeg -i video_silent.mp4 -i audio.wav -c:v copy -c:a aac wakeel_ad.mp4`.
