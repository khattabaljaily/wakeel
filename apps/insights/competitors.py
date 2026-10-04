"""Competitor analysis: read the competitors' websites, ask the AI for the gaps, and give the planner the result."""
import datetime

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .models import Competitor, CompetitorAnalysis

MAX_COMPETITORS = 8
REREAD_AFTER = datetime.timedelta(days=7)
FRESH_FOR = datetime.timedelta(days=120)  # older analyses no longer steer the planner


def read_sites(competitors, now=None):
    from apps.companies.scrape import FetchError, read_site
    now = now or timezone.now()
    for c in competitors:
        if not c.website or (c.site_read_at and now - c.site_read_at < REREAD_AFTER and c.site_text):
            continue
        try:
            site = read_site(c.website)
        except FetchError as exc:
            c.site_error = str(exc)[:300]
        except Exception:  # an odd site must not sink the whole analysis
            c.site_error = str(_('تعذّرت قراءة الموقع.'))
        else:
            c.site_text = '\n'.join(p for p in (site.get('title', ''), site.get('description', ''), site.get('text', '')) if p)[:8000]
            c.site_error = ''
        c.site_read_at = now
        c.save(update_fields=['site_text', 'site_error', 'site_read_at'])


def run_analysis(job):
    from apps.ai import competitors as ai
    from apps.core import language

    analysis = CompetitorAnalysis.objects.get(pk=job.params['analysis_id'], company=job.company)
    rivals = list(Competitor.objects.filter(company=job.company)[:MAX_COMPETITORS])
    job.set_progress(15, _('قراءة مواقع المنافسين…'))
    read_sites(rivals)
    job.set_progress(50, _('وكيل يحلّل المنافسين…'))
    try:
        result = ai.analyse(job.company, rivals,
                            language.name(language.of_user(job.created_by) if job.created_by_id else language.of_team(job.company)))
    except Exception as exc:
        analysis.status, analysis.error = CompetitorAnalysis.Status.FAILED, str(exc)
        analysis.save(update_fields=['status', 'error'])
        raise
    job.add_usage(result)
    data = result.data
    analysis.summary = str(data.get('summary') or '').strip()
    analysis.competitors = [c for c in data.get('competitors') or [] if isinstance(c, dict)][:MAX_COMPETITORS]
    analysis.gaps = [str(g) for g in data.get('gaps') or [] if g][:6]
    analysis.opportunities = [str(o) for o in data.get('opportunities') or [] if o][:6]
    analysis.status, analysis.error = CompetitorAnalysis.Status.READY, ''
    analysis.save()
    return _('اكتمل تحليل المنافسين.')


def latest(company):
    return CompetitorAnalysis.objects.filter(company=company, status=CompetitorAnalysis.Status.READY).first()


def planner_block(company, now=None):
    """The latest analysis as a prompt section, while it is recent. Empty otherwise."""
    analysis = latest(company)
    now = now or timezone.now()
    if not analysis or now - analysis.created_at > FRESH_FOR or not (analysis.gaps or analysis.opportunities):
        return ''
    lines = ['Gaps the competitors leave:', *(f'- {g}' for g in analysis.gaps),
             'Content angles that set the brand apart:', *(f'- {o}' for o in analysis.opportunities)]
    return ('\n<competitor_insights>\nFrom the latest competitor analysis. Use it to differentiate the brand; never name or '
            'attack competitors in posts.\n' + '\n'.join(lines) + '\n</competitor_insights>\n')
