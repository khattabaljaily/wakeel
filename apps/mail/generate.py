"""The AI designs the company's e-mail templates: one paid job per template, on the strongest model. It returns HTML for a mail
(tables and inline styles, the way mail apps need it); `htmlsafe` cleans it before it is stored. The price is a fixed value the
owner set ($0.24), charged when the job is queued at the price on the button, and given back if no usable design comes out."""
import re

from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.ai import client as ai
from apps.ai.client import AIError
from apps.core.tenancy import company_context
from apps.credits import quote as quotes
from apps.documents.generate import LANGUAGE_NAMES
from apps.jobs.models import Job

from . import htmlsafe
from .models import MailTemplate

SERVICE = 'generate_mail_template'
FUNC = 'apps.mail.generate.run_template'
MAX_NOTES = 1000
STYLES = {
    'classic': (gettext_lazy('Classic'), 'A classic business look: a coloured band with the logo and company name at the top, a white '
                'page for the message, a thin rule and a quiet footer.'),
    'modern': (gettext_lazy('Modern'), 'A modern look: generous white space, a large rounded header card in the brand colour with the '
               'logo, soft shadows and rounded corners, a pill-shaped contact line in the footer.'),
    'minimal': (gettext_lazy('Minimal'), 'A minimal look: almost no colour, the logo small at the top left, one thin accent rule in the '
                'brand colour, very light footer text.'),
    'elegant': (gettext_lazy('Elegant'), 'An elegant look for a formal company: the logo centred above a thin double rule, a serif '
                'feel for the headings (Georgia, "Times New Roman", serif), the brand colour used sparingly.'),
}
SYSTEM = (
    'You design an HTML e-mail template for a company, the way a good e-mail designer does, so the company\'s messages '
    'look professional in every mail app. Rules: a single outer table 640px wide (max-width 100%) centred on a light '
    'background; tables for the layout, every style inline (no <style> block, no classes, no scripts, no forms, no external '
    'fonts or images, no background images, no JavaScript, no CSS variables); fonts only from Arial, Tahoma, Georgia, '
    '"Times New Roman", Verdana, sans-serif, serif; text at least 14px; good contrast; it must look right on a phone. '
    'The page has these blanks, written exactly like this, which the app fills in later: {{body}} (REQUIRED, exactly once: '
    'where the message text goes, in a cell with comfortable padding and line-height 1.6), {{logo}} (use it only as the src of '
    'ONE <img src="{{logo}}" alt="" height="48" style="...">, and wrap it so that an empty logo leaves no broken picture: '
    'give the company name next to it), {{company}}, {{address}}, {{phone}}, {{email}}, {{website}}, {{subject}}. '
    'Put the company details in the footer using those blanks; a blank may be empty, so never build a sentence that breaks '
    'when one is. {{website}} and {{email}} may be used as the text of a link: <a href="{{website}}">{{website}}</a>. '
    'Set dir on the outer table (rtl for Arabic and Persian, ltr otherwise) and align text to match. '
    'Write any fixed words (such as a footer line) in the language of the template. Do not invent facts, offers, slogans or '
    'numbers. Reply with JSON only: "html" is the complete design (the outer table and what is in it, without html/head/body). '
    + ai.UNTRUSTED_NOTE)
SCHEMA = {'type': 'object', 'additionalProperties': False, 'required': ['html'], 'properties': {'html': {'type': 'string'}}}


def quote():
    """The quote of one template: the screen and the charge use this same function."""
    return quotes.make(SERVICE)


def start(company, user, data, expected_points):
    """Queue the paid job (charged here at the price shown: a refused payment raises, nothing is queued). Returns the job."""
    return Job.enqueue(company, Job.Kind.CALL, user, expected_points=expected_points, func=FUNC, service=SERVICE,
                       name=(data.get('name') or '')[:120], style=data['style'], language=data['language'],
                       notes=(data.get('notes') or '')[:MAX_NOTES], result_url=reverse('mail:templates'))


def brief(company, language, style):
    return (f'Company: {company.name_for(language) or company.name}\nBrand colours: primary {company.primary_color or "#6d5ef8"}, '
            f'secondary {company.secondary_color or "#111827"}\nTone: {company.get_tone_display() if company.tone else "formal"}\n'
            f'Language: {LANGUAGE_NAMES.get(language, "English")} ({"right-to-left" if language in ("ar", "fa") else "left-to-right"})\n'
            f'Style: {STYLES[style][1]}\n')


def design(job, company, language, style, notes=''):
    """The cleaned HTML of a new template. Raises AIError when no usable design came back (the charge is then given back)."""
    prompt = brief(company, language, style)
    if notes:
        prompt += '\n' + ai.wrap_untrusted('what the company wants', notes[:MAX_NOTES])
    result = ai.call_json(SYSTEM, prompt, SCHEMA, tier='premium', effort='high')
    job.add_usage(result)
    html, _images = htmlsafe.clean(str((result.data or {}).get('html', '')), template=True)
    if len(re.findall(r'\{\{\s*body\s*\}\}', html)) != 1 or len(html) < 200:
        raise AIError(_('The design could not be used. You were not charged; please try again.'), 'template without one body blank')
    return html


def run_template(job):
    """The paid job: design one template and keep it (the company's first one becomes its default)."""
    p = job.params
    if p.get('style') not in STYLES:
        raise AIError(_('The design could not be used. You were not charged; please try again.'), 'unknown style')
    with company_context(job.company):
        html = design(job, job.company, p['language'], p['style'], p.get('notes', ''))
        first = not MailTemplate.objects.exists()
        MailTemplate.objects.create(company=job.company, name=p.get('name') or str(STYLES[p['style']][0]), language=p['language'],
                                    style=p['style'], html=html, is_default=first, created_by=job.created_by)
    return _('Your e-mail template is ready. Preview it and choose it when you write a message.')
