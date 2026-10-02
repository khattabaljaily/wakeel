import json, soundfile as sf, numpy as np
from kokoro_onnx import Kokoro
k = Kokoro("kokoro-v1.0.onnx", "voices-v1.0.bin")
lines = [
 ("hook", "Your business deserves great marketing. But every month, it's the same story."),
 ("problem", "Hours of brainstorming. Endless back and forth with designers. Expensive agencies. And posts that still go out late."),
 ("meet", "Meet Wakeel. Your AI marketing manager."),
 ("brand", "Wakeel starts by learning your brand: your business, your audience, your tone of voice, your colors, fonts, and logo."),
 ("plan", "Pick a month and your platforms. In minutes, Wakeel builds a complete strategy: goals, content pillars, key dates, and every single post, with captions, hashtags, and the best time to publish."),
 ("design", "Then it designs every post, in your brand's style, ready for Instagram, Facebook, and TikTok."),
 ("review", "Everything lands in one smart calendar. Drag to reschedule, rewrite with one click, and send posts for approval. Even share a secure link so your clients can approve without an account."),
 ("publish", "Once approved, publish with one click, or let Wakeel post automatically, right on time."),
 ("team", "One account. Multiple companies. Your whole team, working together."),
 ("cta", "Wakeel. Your marketing, on autopilot. Start today at wakeel dot enjaz technology dot com."),
 ("credit", "Wakeel is a service provided by Enjaz Information Technology."),
]
meta=[]
for name, text in lines:
    s, sr = k.create(text, voice="am_michael", speed=1.0, lang="en-us")
    sf.write(f"vo/{name}.wav", s, sr)
    meta.append({"name":name,"dur":round(len(s)/sr,3),"text":text})
    print(name, round(len(s)/sr,2))
json.dump(meta, open("vo/meta.json","w"), indent=1)
print("total", sum(m["dur"] for m in meta))
