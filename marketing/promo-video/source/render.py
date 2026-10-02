import asyncio, os, json, subprocess
from playwright.async_api import async_playwright
TL=json.load(open("timeline.json")); T=TL[-1]["end"]; FPS=30; N=int(T*FPS)
async def main():
    ff=subprocess.Popen(["ffmpeg","-loglevel","error","-y","-f","image2pipe","-framerate",str(FPS),"-c:v","mjpeg","-i","-","-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","video_silent.mp4"],stdin=subprocess.PIPE)
    async with async_playwright() as p:
        b=await p.chromium.launch(executable_path="/opt/pw-browsers/chromium",args=["--allow-file-access-from-files"])
        pg=await b.new_page(viewport={"width":1920,"height":1080})
        await pg.goto("file://"+os.path.abspath("index.html")); await pg.evaluate("document.fonts.ready"); await pg.wait_for_timeout(800)
        for i in range(N):
            await pg.evaluate(f"seek({i/FPS})")
            ff.stdin.write(await pg.screenshot(type="jpeg",quality=95))
            if i%300==0: print(i,N,flush=True)
        await b.close()
    ff.stdin.close(); ff.wait(); print("done")
asyncio.run(main())
