"""Builds build/index_ar.html (Arabic, right to left) from build/index.html."""
import json, re

en = {s["name"]: s["vodur"] for s in json.load(open("timeline.json"))}
h = open("build/index.html").read()
R = [
('<html lang="en">', '<html lang="ar" dir="rtl">'),
('<title>Wakeel Ad</title>', '<title>Wakeel Ad (Arabic)</title>'),
("font-size:110px;line-height:1.05;letter-spacing:-2px", "font-size:116px;line-height:1.2;letter-spacing:0"),
("font-size:76px;line-height:1.1;letter-spacing:-1px", "font-size:80px;line-height:1.25;letter-spacing:0"),
(".word{display:inline-block;margin-right:.26em}", ".word{display:inline-block;margin-inline-end:.26em}"),
("letter-spacing:3px;text-transform:uppercase;color:#b4a9ff}", "letter-spacing:0;color:#b4a9ff;font-size:30px}"),
("transform-origin:left}", "transform-origin:right}"),
# hook
('<span class="word">Your</span><span class="word">business</span><span class="word">deserves</span><br><span class="word grad">great</span><span class="word grad">marketing.</span>',
 '<span class="word">عملُك</span><span class="word">يستحق</span><br><span class="word grad">تسويقًا</span><span class="word grad">رائعًا.</span>'),
("But every month, it's the same story…", "لكن كل شهر، تتكرر القصة نفسها…"),
# problem
("Marketing shouldn't be <span class=\"grad\">this hard.</span>", "التسويق لا ينبغي أن يكون <span class=\"grad\">بهذه الصعوبة.</span>"),
('style="left:150px;top:440px"', 'style="left:1410px;top:440px"'),
('style="left:570px;top:440px"', 'style="left:990px;top:440px" data-x'),
('style="left:990px;top:440px"><div class="ic" style="background:rgba(255,176', 'style="left:570px;top:440px"><div class="ic" style="background:rgba(255,176'),
('style="left:1410px;top:440px"><div class="ic" style="background:rgba(255,93', 'style="left:150px;top:440px"><div class="ic" style="background:rgba(255,93'),
("Hours of<br>brainstorming", "ساعات من<br>التفكير"), ("Endless<br>revisions", "تعديلات<br>لا تنتهي"),
("Expensive<br>agencies", "وكالات<br>مكلفة"), ("Posts that<br>go out late", "منشورات<br>تتأخر عن موعدها"),
# meet
('<span class="h1" style="font-size:150px">Wakeel</span><span id="meet-ar" style="font-family:Cairo;font-weight:800;font-size:96px;color:#b4a9ff;margin-left:36px">وكيل</span>',
 '<span class="h1" style="font-family:Cairo;font-weight:800;font-size:170px">وكيل</span><span id="meet-ar" style="font-family:\'Readex Pro\';font-weight:600;font-size:88px;color:#b4a9ff;margin-right:40px">Wakeel</span>'),
('Your <span class="grad" style="font-weight:600">AI Marketing Manager</span>', 'مدير التسويق <span class="grad" style="font-weight:600">الذكي</span> لشركتك'),
('top:560px;text-align:center"><span', 'top:520px;text-align:center"><span'),
# kickers
("<b>1</b>Learns your brand", "<b>1</b>يفهم علامتك"), ("<b>2</b>Plans your month", "<b>2</b>يخطط لشهرك"),
("<b>3</b>Designs every post", "<b>3</b>يصمم كل منشور"), ("<b>4</b>Review &amp; approve", "<b>4</b>مراجعة واعتماد"),
("<b>5</b>Publishes on time", "<b>5</b>ينشر في موعده"),
# brand
('id="brand-copy" style="left:140px;', 'id="brand-copy" style="right:140px;'),
('id="brand-card" style="left:860px;', 'id="brand-card" style="right:860px;'),
('Knows your business <span class="grad">like you do.</span>', 'يعرف نشاطك <span class="grad">كما تعرفه أنت.</span>'),
(">Brand Kit<", ">هوية العلامة<"), (">Step 1 of 1<", ">✓ مكتملة<"),
("<label>Business</label>", "<label>النشاط</label>"), ("<label>Audience</label>", "<label>الجمهور</label>"),
("<label>Tone of voice</label>", "<label>نبرة الصوت</label>"), ("<label>Colors</label>", "<label>الألوان</label>"),
("<label>Fonts</label>", "<label>الخطوط</label>"), ("<label>Logo</label>", "<label>الشعار</label>"),
('data-text="Specialty coffee roastery &amp; café">Specialty coffee roastery &amp; café', '>محمصة قهوة مختصة ومقهى'),
('data-text="Young professionals, 22–35, coffee lovers">Young professionals, 22–35, coffee lovers', '>شباب ومهنيون من 22 إلى 35 عامًا، عشاق القهوة'),
(">Warm<", ">دافئة<"), (">Playful<", ">مرحة<"), (">Confident<", ">واثقة<"), (">Premium<", ">فاخرة<"),
("kf.push({clipPath:`inset(0 ${100-100*i/n}% 0 0)`})", "kf.push({clipPath:`inset(0 0 0 ${100-100*i/n}%)`})"),
("rotateY(-28deg) translateX(200px)", "rotateY(28deg) translateX(-200px)"),
("perspective(1600px) rotateY(-6deg)", "perspective(1600px) rotateY(6deg)"),
("perspective(1600px) rotateY(2deg)", "perspective(1600px) rotateY(-2deg)"),
# plan
('id="plan-copy" style="left:140px;', 'id="plan-copy" style="right:140px;'),
('id="strategy" style="left:140px;', 'id="strategy" style="right:140px;'),
('A full strategy, <span class="grad">in minutes.</span>', 'استراتيجية كاملة <span class="grad">في دقائق.</span>'),
(">October strategy<", ">استراتيجية أكتوبر<"), (">✓ Ready<", ">✓ جاهزة<"), (">GOALS<", ">الأهداف<"), (">CONTENT PILLARS<", ">محاور المحتوى<"),
("<span>Brand awareness</span>", "<span>الوعي بالعلامة</span>"), ("<span>Engagement</span>", "<span>التفاعل</span>"),
("<span>Store visits</span>", "<span>زيارات المتجر</span>"),
(">Behind the bar<", ">خلف الكواليس<"), (">New brews<", ">مشروبات جديدة<"), (">Offers<", ">عروض<"), (">Community<", ">مجتمعنا<"),
('id="counter" style="left:1520px;top:120px;text-align:right"', 'id="counter" style="left:140px;top:120px;text-align:left"'),
(">posts written<", ">منشورًا جاهزًا<"),
("'Meet our new<br>October roast','#CoffeeLovers #NewRoast','Mon · 9:00 AM'", "'تعرّف على<br>تحميصة أكتوبر','#عشاق_القهوة #تحميصة_جديدة','الإثنين · 9:00 ص'"),
("'2-for-1<br>every Friday','#FridayDeal #Café','Fri · 5:30 PM'", "'اثنان بسعر واحد<br>كل جمعة','#عرض_الجمعة #مقهى','الجمعة · 5:30 م'"),
("'Behind the bar<br>with Sara','#BaristaLife #Reels','Wed · 7:30 PM'", "'خلف البار<br>مع سارة','#باريستا #ريلز','الأربعاء · 7:30 م'"),
("'Latte art<br>Tuesday','#LatteArt #Morning','Tue · 8:00 AM'", "'ثلاثاء<br>فن اللاتيه','#فن_اللاتيه #صباح','الثلاثاء · 8:00 ص'"),
("'Community<br>open mic night','#Community #Live','Thu · 8:00 PM'", "'أمسية<br>المواهب','#مجتمعنا #مباشر','الخميس · 8:00 م'"),
("'Pumpkin Spice<br>is back','#Autumn #Seasonal','Sat · 11:00 AM'", "'عاد موسم<br>الخريف','#الخريف #موسمي','السبت · 11:00 ص'"),
("const pos=[[900,420],[1240,380],[1580,420],[900,700],[1240,660],[1580,700]];",
 "const pos=[[900,420],[1240,380],[1580,420],[900,700],[1240,660],[1580,700]].map(([x,y])=>[1920-x-300,y]);"),
("● AI</span>", "● وكيل</span>"),
# design
('On-brand. <span class="grad">Every single time.</span>', 'بهويتك. <span class="grad">في كل مرة.</span>'),
("t:'Bold',s:'Fresh roast, every morning'", "t:'جريء',s:'تحميص طازج كل صباح'"),
("t:'Gradient',s:'Weekend vibes ☕'", "t:'متدرّج',s:'أجواء نهاية الأسبوع ☕'"),
("t:'Story · 9:16',s:'Swipe up for the menu'", "t:'ستوري · 9:16',s:'اسحب لأعلى لرؤية القائمة'"),
("<span style=\"color:#3b2316\">Split</span>'", "<span style=\"color:#3b2316\">مقسوم</span>'"),
("Hot vs. iced", "ساخن أم مثلّج؟"), ("linear-gradient(90deg,#f3e6d3 50%,#3b2316 50%)", "linear-gradient(180deg,#3b2316 52%,#f3e6d3 52%)"), ('font-size:56px">-30%</span>', 'font-size:56px">خصم <span dir=ltr>30%</span></span>'), ("Offer · this week only", "عرض لهذا الأسبوع فقط"),
(".design .lg{position:absolute;top:24px;left:24px", ".design .lg{position:absolute;top:24px;right:24px"),
("▢ 1:1 Square", "▢ 1:1 مربع"), ("▯ 4:5 Portrait", "▯ 4:5 عمودي"), ("▮ 9:16 Story &amp; TikTok", "▮ 9:16 ستوري وتيك توك"),
# review
('id="review-copy" style="left:120px;', 'id="review-copy" style="right:120px;'),
(".cal{position:absolute;left:640px;", ".cal{position:absolute;left:120px;"),
('One smart <span class="grad">calendar.</span>', 'تقويم ذكي <span class="grad">واحد.</span>'),
(">● Draft<", ">● مسودة<"), (">● In review<", ">● قيد المراجعة<"), (">✓ Approved<", ">✓ معتمد<"),
('<span style="opacity:.85">…/review/', '<span dir="ltr" style="opacity:.85">…/review/'),
(">✓ Client approved<", ">✓ اعتمده العميل<"),
(">October</div>", ">أكتوبر</div>"), (">24 posts<", ">24 منشورًا<"),
(">Facebook<", ">فيسبوك<"), (">Instagram<", ">إنستغرام<"), (">TikTok</span></div></div>", ">تيك توك</span></div></div>"),
("['Sun','Mon','Tue','Wed','Thu','Fri','Sat']", "['الأحد','الإثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت']"),
("'FB · Roast'", "'FB · تحميص'"), ("'IG · Reel'", "'IG · ريلز'"), ("'IG · Offer'", "'IG · عرض'"), ("'FB · Event'", "'FB · فعالية'"),
("'IG · Story'", "'IG · ستوري'"), ("'IG · Latte'", "'IG · لاتيه'"), ("'FB · Menu'", "'FB · القائمة'"), ("'Open mic'", "'أمسية'"),
("'IG · Autumn'", "'IG · الخريف'"), ("'FB · Promo'", "'FB · ترويج'"),
("translate(158px,-6px) scale(1.08) rotate(-3deg)", "translate(-158px,-6px) scale(1.08) rotate(3deg)"),
("{transform:'translate(158px,0)',boxShadow:'none'}", "{transform:'translate(-158px,0)',boxShadow:'none'}"),
# publish
(">NEW ON THE MENU<", ">جديد في القائمة<"), ("Pumpkin Spice<br>Cold Brew", "كولد برو<br>بنكهة الخريف"),
(">Today · 7:30 PM<", ">اليوم · 7:30 م<"), (">Publish</div>", ">انشر الآن</div>"),
('id="auto" style="left:1330px;', 'id="auto" style="left:150px;'), ('class="toast" id="toast" style="left:150px;', 'class="toast" id="toast" style="left:1330px;'),
(">Auto-publish<", ">نشر تلقائي<"), (">Published to 3 platforms<", ">تم النشر على 3 منصات<"),
("[[tc-1.2,1400,620],[tc-.1,1120,560],[tc,1120,560,1],[tc+.2,1120,560],[tc+1.5,1300,600]]",
 "[[tc-1.2,520,640],[tc-.1,800,590],[tc,800,590,1],[tc+.2,800,590],[tc+1.5,620,640]]"),
("transform:'translateX(-80px)'},{opacity:1,transform:'none'}],tc+1.4", "transform:'translateX(80px)'},{opacity:1,transform:'none'}],tc+1.4"),
("{transform:'translateX(42px)'}", "{transform:'translateX(-42px)'}"),
(".toggle i{position:absolute;top:6px;left:6px;", ".toggle i{position:absolute;top:6px;right:6px;"),
# team
('One account. <span class="grad">Many companies.</span>', 'حساب واحد. <span class="grad">شركات متعددة.</span>'),
("['Nile Café',", "['مقهى النيل',"), ("['Pearl Tech',", "['بيرل تك',"), ("['Bloom Studio',", "['استوديو بلوم',"), ("['Atlas Gym',", "['أطلس جيم',"),
("[['S','#6d5ef8',700,800],['M','#0f9d6b',820,840],['A','#d6336c',940,850],['K','#c47f00',1060,840],['R','#2563eb',1180,800]]",
 "[['س','#6d5ef8',700,800],['م','#0f9d6b',820,840],['ع','#d6336c',940,850],['خ','#c47f00',1060,840],['ر','#2563eb',1180,800]]"),
# cta
('<div class="h1" id="cta-name" style="font-size:130px;margin-top:20px">Wakeel</div>',
 '<div class="h1" id="cta-name" style="font-family:Cairo;font-weight:800;font-size:150px;margin-top:10px;line-height:1.2">وكيل</div>'),
('Your marketing, <span class="grad" style="font-weight:600">on autopilot.</span>', 'تسويقك <span class="grad" style="font-weight:600">يعمل وحده.</span>'),
('<div class="url" id="cta-url"', '<div class="url" dir="ltr" id="cta-url"'),
# credit
('letter-spacing:6px;text-transform:uppercase;color:#b4a9ff">A service provided by', 'letter-spacing:0;color:#b4a9ff">خدمة مقدّمة من'),
('<div id="cr-name" class="h1" style="font-size:96px;text-align:center">Enjaz <span class="grad">Information Technology</span></div>',
 '<div id="cr-name" class="h1" style="font-family:Cairo;font-weight:800;font-size:110px;text-align:center;line-height:1.3">إنجاز <span class="grad">لتقنية المعلومات</span></div>'),
('<div id="cr-ar" style="font-family:Cairo;font-weight:700;font-size:48px;color:#cfcaff;margin-top:24px">إنجاز لتقنية المعلومات</div>',
 '<div id="cr-ar" dir="ltr" style="font-family:\'Readex Pro\';font-weight:500;font-size:44px;color:#cfcaff;margin-top:20px">Enjaz Information Technology</div>'),
# generic
("margin-left:auto", "margin-inline-start:auto"),
("transform:'translateX(40px)'},{opacity:1,transform:'none'}],V('meet')", "transform:'translateX(-40px)'},{opacity:1,transform:'none'}],V('meet')"),
('<script src="timeline.js"></script>', '<script src="timeline_ar.js"></script>'),
]
for a, b in R:
    assert a in h, ("MISSING", a)
    h = h.replace(a, b)
h = h.replace(' data-x', '')
# Stretch each scene's in-voice cues to the Arabic narration's length.
h = h.replace("const S=n=>TL[n].start",
              "const EN=" + json.dumps(en) + ";const K=n=>TL[n].vodur/EN[n];const S=n=>TL[n].start")
h = re.sub(r"V\('(\w+)'\)\+(?=[\d.(\[])", lambda m: f"V('{m.group(1)}')+K('{m.group(1)}')*", h)
open("build/index_ar.html", "w").write(h)
print("ok", h.count("K('"))
