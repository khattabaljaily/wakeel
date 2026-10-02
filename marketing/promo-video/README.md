# Wakeel promo video

A motion-graphics ad for Wakeel in two languages (1920×1080, 30 fps, H.264 + AAC):

- **English**: 1:42, `wakeel_ad.mp4`
- **Arabic**: 1:59, `wakeel_ad_ar.mp4`, right to left, Modern Standard Arabic voice-over

| File | What it is |
|---|---|
| `wakeel_ad.mp4` | The finished video with voice-over and music |
| `wakeel_ad.srt` | English subtitles, for feeds that autoplay muted |
| `poster.jpg` | A thumbnail frame |
| `wakeel_ad_ar.mp4`, `wakeel_ad_ar.srt`, `poster_ar.jpg` | The Arabic version, its subtitles and thumbnail |
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

## Arabic version

`source/arabic/make_ar.py` builds `index_ar.html` from the English `index.html`: it translates every on-screen text, mirrors the layouts for right-to-left reading, and stretches each scene's cues to the Arabic narration (`timeline_ar.json`). Re-run it after changing the English page.

The voice is Piper's `ar_JO-kareem-medium`, run with sherpa-onnx (`vo_ar.py`, model from the sherpa-onnx `tts-models` GitHub release). The script is fully diacritized so the voice reads it correctly. Keep the diacritics when you edit it.
