"""Topic vectors drawn in the corner of a design: line drawings from Tabler Icons (MIT, see
VECTORS_LICENSE.txt), coloured with the brand palette at render time.

`VECTORS` maps a key to (label for the editor, words that suggest it). The AI picks up to three keys
per post; posts without a choice get them from the words of their title, headline and pillar.
The drawings themselves live in vectors.json (the inner SVG of each 24x24 icon).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from django.utils.translation import gettext_lazy as _

VECTORS = {
    # Technology
    'device-laptop': (_('حاسوب'), 'laptop computer حاسوب لابتوب كمبيوتر برنامج نظام software system'),
    'device-mobile': (_('جوال'), 'mobile phone app تطبيق جوال هاتف موبايل'),
    'code': (_('برمجة'), 'code developer برمجة مطور كود تطوير'),
    'cloud': (_('سحابة'), 'cloud سحابة سحابي استضافة hosting'),
    'server': (_('خادم'), 'server خادم سيرفر'),
    'database': (_('بيانات'), 'database data بيانات قاعدة'),
    'cpu': (_('معالج'), 'cpu chip hardware معالج عتاد'),
    'robot': (_('روبوت'), 'robot ai bot روبوت ذكاء اصطناعي أتمتة automation'),
    'brain': (_('ذكاء'), 'brain intelligence ذكاء تفكير عقل'),
    'shield-lock': (_('أمان'), 'security secure protect أمان حماية أمن'),
    'world-www': (_('موقع'), 'website web موقع إلكتروني ويب'),
    'wifi': (_('إنترنت'), 'internet wifi network إنترنت شبكة'),
    'device-desktop-analytics': (_('لوحة تحكم'), 'dashboard analytics لوحة تحكم'),
    'qrcode': (_('رمز QR'), 'qr code باركود رمز'),
    'fingerprint': (_('بصمة'), 'fingerprint بصمة هوية'),
    'settings': (_('إعدادات'), 'settings configure إعدادات ضبط'),
    'puzzle': (_('تكامل'), 'integration puzzle تكامل ربط حلول'),
    'cube': (_('منتج'), 'product cube منتج'),
    # Business & growth
    'chart-line': (_('نمو'), 'growth chart نمو أداء ارتفاع'),
    'chart-bar': (_('إحصاءات'), 'statistics stats إحصائيات إحصاءات أرقام'),
    'chart-pie': (_('حصة'), 'share pie حصة نسبة'),
    'trending-up': (_('ارتفاع'), 'trend increase زيادة ارتفاع مبيعات sales'),
    'report-analytics': (_('تقرير'), 'report تقرير تقارير'),
    'presentation-analytics': (_('عرض تقديمي'), 'presentation عرض تقديمي'),
    'target': (_('هدف'), 'goal target هدف أهداف'),
    'rocket': (_('انطلاق'), 'launch rocket startup إطلاق انطلاق جديد'),
    'bulb': (_('فكرة'), 'idea tip فكرة نصيحة نصائح أفكار'),
    'sparkles': (_('تميّز'), 'new special جديد مميز تميز'),
    'briefcase': (_('أعمال'), 'business work أعمال شركة عمل'),
    'building': (_('شركة'), 'company office شركة مكتب مؤسسة'),
    'businessplan': (_('خطة'), 'plan strategy خطة استراتيجية'),
    'checklist': (_('قائمة مهام'), 'checklist steps خطوات قائمة علامات'),
    'clipboard-check': (_('إنجاز'), 'done task مهمة إنجاز تنظيم'),
    'file-text': (_('مستند'), 'document file مستند ملف وثيقة'),
    'calculator': (_('محاسبة'), 'accounting calculator محاسبة حسابات'),
    'scale': (_('عدالة'), 'law legal قانون عدالة'),
    'id-badge': (_('موظف'), 'employee staff موظف موظفين'),
    'award': (_('جائزة'), 'award جائزة تكريم'),
    'trophy': (_('فوز'), 'win trophy فوز بطولة نجاح'),
    'crown': (_('ريادة'), 'leader premium ريادة قيادة فاخر'),
    'certificate': (_('شهادة'), 'certificate شهادة اعتماد'),
    'rosette': (_('جودة'), 'quality جودة ضمان'),
    'star': (_('تقييم'), 'rating review تقييم نجوم'),
    # People & communication
    'users': (_('فريق'), 'team users فريق عملاء مستخدمين'),
    'user-check': (_('عميل'), 'customer client عميل'),
    'heart-handshake': (_('شراكة وخدمة'), 'support care partner deal خدمة دعم رعاية شراكة شريك اتفاق تعاون'),
    'headset': (_('دعم فني'), 'support help دعم فني مساعدة'),
    'messages': (_('محادثة'), 'chat messages محادثة رسائل تواصل'),
    'mail': (_('بريد'), 'email mail بريد إيميل'),
    'phone': (_('اتصال'), 'call phone اتصال اتصل'),
    'brand-whatsapp': (_('واتساب'), 'whatsapp واتساب واتس'),
    'speakerphone': (_('إعلان'), 'announcement announce إعلان نعلن'),
    'ad-2': (_('تسويق'), 'marketing ads تسويق إعلانات'),
    'news': (_('أخبار'), 'news أخبار خبر'),
    'microphone': (_('بودكاست'), 'podcast interview بودكاست مقابلة'),
    'camera': (_('تصوير'), 'photo camera تصوير صورة'),
    'video': (_('فيديو'), 'video فيديو'),
    'thumb-up': (_('إعجاب'), 'like إعجاب'),
    'mood-smile': (_('سعادة'), 'happy smile سعادة سعيد'),
    'heart': (_('حب'), 'love heart حب قلب'),
    'help-circle': (_('سؤال'), 'question faq سؤال أسئلة استفسار'),
    'info-circle': (_('معلومة'), 'info fact معلومة حقيقة'),
    'alert-triangle': (_('تنبيه'), 'warning alert تنبيه تحذير خطأ أخطاء'),
    'circle-check': (_('صحيح'), 'correct check صح صحيح'),
    # Real estate & construction
    'home': (_('منزل'), 'home house apartment منزل بيت سكن شقق شقة'),
    'building-skyscraper': (_('برج'), 'tower real estate برج عقار عقارات'),
    'building-community': (_('مجمع'), 'compound community مجمع حي'),
    'building-cottage': (_('فيلا'), 'villa فيلا'),
    'key': (_('مفتاح'), 'key rent مفتاح إيجار تأجير'),
    'map-pin': (_('موقع'), 'location address موقع عنوان مكان'),
    'ruler-2': (_('قياس'), 'design measure قياس تصميم هندسة'),
    'tools': (_('صيانة'), 'maintenance tools صيانة أدوات إصلاح'),
    'hammer': (_('بناء'), 'build construction بناء مقاولات تشييد'),
    'paint': (_('دهان'), 'paint دهان طلاء'),
    'sofa': (_('أثاث'), 'furniture أثاث ديكور'),
    'bed': (_('غرفة نوم'), 'bedroom hotel غرفة فندق'),
    'building-warehouse': (_('مستودع'), 'warehouse inventory مستودع مخزن مخزون'),
    # Retail & money
    'building-store': (_('متجر'), 'store shop متجر محل'),
    'shopping-cart': (_('تسوق'), 'cart shopping تسوق سلة شراء'),
    'shopping-bag': (_('مشتريات'), 'bag purchase مشتريات'),
    'tag': (_('سعر'), 'price tag سعر أسعار'),
    'discount': (_('خصم'), 'discount sale offer خصم عرض تخفيض'),
    'gift': (_('هدية'), 'gift present هدية هدايا'),
    'receipt': (_('فاتورة'), 'invoice receipt فاتورة فواتير'),
    'credit-card': (_('دفع'), 'payment card دفع بطاقة'),
    'cash': (_('نقد'), 'cash money نقد نقود مال'),
    'coin': (_('عملة'), 'coin عملة'),
    'wallet': (_('محفظة'), 'wallet محفظة'),
    'building-bank': (_('بنك'), 'bank finance بنك مالية تمويل'),
    'pig-money': (_('ادخار'), 'saving ادخار توفير'),
    'barcode': (_('منتجات'), 'products barcode منتجات صنف أصناف'),
    'package': (_('طرد'), 'package parcel طرد شحنة'),
    'box': (_('صندوق'), 'box صندوق'),
    'truck-delivery': (_('توصيل'), 'delivery shipping توصيل شحن'),
    # Food
    'tools-kitchen-2': (_('مطعم'), 'restaurant food مطعم طعام أكل'),
    'chef-hat': (_('طبخ'), 'chef cooking طبخ شيف'),
    'coffee': (_('قهوة'), 'coffee cafe قهوة كافيه'),
    'pizza': (_('بيتزا'), 'pizza بيتزا'),
    'burger': (_('برجر'), 'burger برجر وجبة'),
    'salad': (_('صحي'), 'healthy salad صحي سلطة'),
    'cake': (_('حلويات'), 'cake sweets حلويات كيك'),
    'ice-cream': (_('آيس كريم'), 'icecream آيس ايسكريم بوظة'),
    'apple': (_('فواكه'), 'fruit فواكه فاكهة'),
    # Health & beauty
    'stethoscope': (_('طبيب'), 'doctor clinic طبيب عيادة'),
    'heartbeat': (_('صحة'), 'health صحة صحي'),
    'pill': (_('دواء'), 'medicine pharmacy دواء صيدلية'),
    'first-aid-kit': (_('إسعاف'), 'first aid إسعاف طوارئ'),
    'dental': (_('أسنان'), 'dental teeth أسنان'),
    'eye': (_('عيون'), 'eye vision عيون نظر'),
    'barbell': (_('رياضة'), 'gym fitness رياضة لياقة'),
    'run': (_('جري'), 'running جري مشي'),
    'ball-football': (_('كرة قدم'), 'football كرة قدم'),
    'diamond': (_('فخامة'), 'luxury diamond فخامة مجوهرات'),
    'perfume': (_('عطور'), 'perfume عطر عطور'),
    'scissors': (_('صالون'), 'salon haircut صالون حلاقة'),
    'shirt': (_('ملابس'), 'clothes fashion ملابس أزياء'),
    'baby-carriage': (_('أطفال'), 'baby kids أطفال طفل'),
    # Education
    'school': (_('تعليم'), 'education school تعليم مدرسة دراسة'),
    'book': (_('كتاب'), 'book reading كتاب قراءة'),
    'books': (_('مكتبة'), 'library books مكتبة كتب'),
    'pencil': (_('كتابة'), 'writing pencil كتابة'),
    'notebook': (_('ملاحظات'), 'notes notebook ملاحظات دفتر'),
    'backpack': (_('طلاب'), 'students طلاب طالب'),
    'presentation': (_('تدريب'), 'training course تدريب دورة ورشة'),
    # Travel, transport, nature
    'plane': (_('سفر'), 'travel flight سفر طيران رحلة'),
    'car': (_('سيارة'), 'car auto سيارة سيارات'),
    'gas-station': (_('وقود'), 'fuel وقود'),
    'map': (_('خريطة'), 'map خريطة'),
    'beach': (_('شاطئ'), 'beach summer شاطئ صيف'),
    'mountain': (_('مغامرة'), 'adventure mountain مغامرة جبل'),
    'tent': (_('تخييم'), 'camping تخييم'),
    'tree': (_('شجرة'), 'tree شجرة'),
    'plant': (_('نبات'), 'plant agriculture نبات زراعة'),
    'leaf': (_('بيئة'), 'eco nature بيئة طبيعة'),
    'recycle': (_('استدامة'), 'recycle sustainability استدامة تدوير'),
    'droplet': (_('ماء'), 'water ماء مياه'),
    'bolt': (_('طاقة'), 'energy power طاقة كهرباء سرعة سريع'),
    'sun': (_('شمس'), 'sun solar شمس'),
    'flame': (_('حماس'), 'hot fire حماس ساخن'),
    # Time & occasions
    'calendar-event': (_('موعد'), 'event date موعد فعالية حدث'),
    'clock': (_('وقت'), 'time hours وقت ساعات دوام'),
    'hourglass': (_('عرض محدود'), 'limited countdown محدود ينتهي'),
    'alarm': (_('تذكير'), 'reminder alarm تذكير'),
    'moon-stars': (_('رمضان'), 'ramadan night رمضان صيام صائم إفطار سحور ليل ليلة'),
    'building-mosque': (_('مسجد'), 'mosque eid islamic مسجد عيد جمعة صلاة'),
    'confetti': (_('احتفال'), 'celebration party احتفال تهنئة'),
    'balloon': (_('مناسبة'), 'occasion balloon مناسبة'),
    'flag': (_('اليوم الوطني'), 'national flag وطني وطن علم'),
    'calendar-heart': (_('مناسبة خاصة'), 'special day مناسبة خاصة'),
}

FALLBACK = ('sparkles', 'target', 'bulb')
DIR = Path(__file__).with_name('vectors.json')


@lru_cache(maxsize=1)
def drawings():
    return json.loads(DIR.read_text(encoding='utf-8'))


def choices():
    return [(key, label) for key, (label, _words) in VECTORS.items()]


_WORDS = re.compile(r'[\w؀-ۿ]+')


def _normalise(text):
    """Arabic letters that are written several ways become one; English is lowercased."""
    text = text.lower()
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي')):
        text = text.replace(a, b)
    return text


def _forms(word):
    """A word and the forms left after peeling Arabic prefixes (و ف ب ل ك ال) and common suffixes."""
    forms = {word}
    stem = word
    # At most one conjunction (و ف) then one preposition (ب ل ك): stripping more eats the root («وطن»).
    for letters in ('وف', 'بلك'):
        if len(stem) > 3 and stem[0] in letters:
            stem = stem[1:]
            forms.add(stem)
    for w in list(forms):
        if w.startswith('ال') and len(w) > 4:
            forms.add(w[2:])
        elif w.startswith('لل') and len(w) > 4:
            forms.add(w[2:])
    for w in list(forms):
        for suffix in ('ات', 'ها', 'هم', 'نا', 'كم', 'ك', 'ه', 'ي'):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                forms.add(w[:-len(suffix)])
    return forms


def guess(*texts, limit=3):
    """Vectors whose words appear in the texts, best first; FALLBACK fills up when too few match.
    Earlier texts weigh more (the headline counts three times the pillar)."""
    weights = {}
    for rank, text in enumerate(t for t in texts if t):
        weight = max(3 - rank, 1)
        for word in _WORDS.findall(_normalise(text)):
            for form in _forms(word):
                weights[form] = max(weights.get(form, 0), weight)
    scored = []
    for order, (key, (_label, hints)) in enumerate(VECTORS.items()):
        score = sum(weights.get(h, 0) for h in set(_normalise(hints).split()))
        if score:
            scored.append((-score, order, key))
    picked = [key for _s, _o, key in sorted(scored)[:limit]]
    for key in FALLBACK:
        if len(picked) >= limit:
            break
        if key not in picked:
            picked.append(key)
    return picked


def for_post(vectors, *texts):
    """The post's chosen vectors (valid ones), else guessed from its words. Returns [(key, inner svg)]."""
    keys = [v for v in (vectors or []) if v in VECTORS][:3] or guess(*texts)
    art = drawings()
    return [(key, art[key]) for key in keys if key in art]
