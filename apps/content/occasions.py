"""Occasions that matter to a brand's audience, with dates we can trust.

The AI knows occasions but can get their dates wrong, especially Islamic ones
that move every year. This module computes them (Hijri dates with the
Umm al-Qura calendar) so the planner and the calendar show real dates.
"""
import calendar
import datetime

from hijridate import Gregorian, Hijri
from django.utils.translation import gettext_lazy as _

# Country codes, from the company's country (or timezone when the country isn't recognised).
TIMEZONE_CODES = {
    'Africa/Khartoum': 'sd', 'Asia/Qatar': 'qa', 'Asia/Riyadh': 'sa', 'Asia/Dubai': 'ae', 'Africa/Cairo': 'eg',
    'Asia/Kuwait': 'kw', 'Asia/Muscat': 'om', 'Asia/Bahrain': 'bh', 'Asia/Amman': 'jo', 'Europe/London': 'gb',
}
ARAB = {'sd', 'qa', 'sa', 'ae', 'eg', 'kw', 'om', 'bh', 'jo'}

# (month, day, name, countries); countries=None means everyone.
FIXED = [
    (1, 1, _('رأس السنة الميلادية'), None),
    (1, 1, _('عيد استقلال السودان'), {'sd'}),
    (2, 22, _('يوم التأسيس السعودي'), {'sa'}),
    (2, 25, _('العيد الوطني الكويتي'), {'kw'}),
    (2, 26, _('عيد التحرير في الكويت'), {'kw'}),
    (3, 21, _('عيد الأم'), ARAB),
    (5, 25, _('عيد استقلال الأردن'), {'jo'}),
    (7, 23, _('ذكرى ثورة 23 يوليو'), {'eg'}),
    (9, 23, _('اليوم الوطني السعودي'), {'sa'}),
    (10, 6, _('ذكرى انتصارات أكتوبر'), {'eg'}),
    (11, 20, _('اليوم الوطني العُماني'), {'om'}),
    (12, 2, _('عيد الاتحاد الإماراتي'), {'ae'}),
    (12, 16, _('العيد الوطني البحريني'), {'bh'}),
    (12, 18, _('اليوم الوطني القطري'), {'qa'}),
]

# (hijri month, day, name). Dates can move a day with the moon sighting.
HIJRI = [
    (1, 1, _('رأس السنة الهجرية')),
    (9, 1, _('بداية شهر رمضان')),
    (9, 21, _('بداية العشر الأواخر من رمضان')),
    (10, 1, _('عيد الفطر')),
    (12, 1, _('بداية عشر ذي الحجة')),
    (12, 9, _('يوم عرفة')),
    (12, 10, _('عيد الأضحى')),
]


def country_code(company):
    from apps.companies.views import guess_timezone  # the same matching the onboarding uses
    return TIMEZONE_CODES.get(guess_timezone(company.country, []) or company.timezone, '')


def _nth_weekday(year, month, weekday, n):
    """n-th weekday (0=Monday) of a month; n=-1 is the last one."""
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1)
            if datetime.date(year, month, d).weekday() == weekday]
    return datetime.date(year, month, days[n])


def between(company, start, end):
    """Occasions from start to end (inclusive dates), sorted, as dicts {date, name, approx}."""
    code = country_code(company)
    found = []
    for year in range(start.year, end.year + 1):
        for month, day, name, countries in FIXED:
            if countries is None or code in countries:
                found.append((datetime.date(year, month, day), name, False))
        if code == 'qa':
            found.append((_nth_weekday(year, 2, 1, 1), _('اليوم الرياضي للدولة في قطر'), False))
        found.append((_nth_weekday(year, 11, 4, -1), _('الجمعة البيضاء (عروض التسوق)'), False))
    if code in ARAB:
        first = Gregorian.fromdate(start).to_hijri().year
        for hyear in range(first - 1, Gregorian.fromdate(end).to_hijri().year + 1):
            for hmonth, hday, name in HIJRI:
                try:
                    g = Hijri(hyear, hmonth, hday).to_gregorian()
                except (OverflowError, ValueError):  # outside the Umm al-Qura table
                    continue
                found.append((datetime.date(g.year, g.month, g.day), name, True))
    return [
        {'date': date, 'name': name, 'approx': approx}
        for date, name, approx in sorted(found, key=lambda o: o[0])
        if start <= date <= end
    ]


def in_month(company, month):
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    return between(company, month, last)
