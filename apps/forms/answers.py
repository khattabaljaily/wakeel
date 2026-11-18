"""Reading and summing the answers of a form. The answers come from strangers on the public page, so nothing is trusted:
a choice must be one of the listed ones, a rating a whole number from 1 to 5, a date a real date, a text is cut to a limit."""
import csv
import datetime
import io

from django.utils.translation import gettext as _

from .models import Question

SHORT_MAX, LONG_MAX = 300, 4000


def read(form, data):
    """(answers, errors) from a submitted page: answers is [(question, value, values)], errors is {question id: message}."""
    answers, errors = [], {}
    for q in form.questions.all():
        key = f'q{q.pk}'
        if q.kind == Question.MULTI:
            picked = [v for v in data.getlist(key) if v in q.choices]
            value, values = '', [c for c in q.choices if c in picked]        # in the order they were written, no repeats
        else:
            value, values = (data.get(key) or '').strip(), []
            if q.kind == Question.SHORT:
                value = value[:SHORT_MAX]
            elif q.kind == Question.LONG:
                value = value[:LONG_MAX]
            elif value and q.kind == Question.CHOICE and value not in q.choices:
                errors[q.pk] = _('Choose one of the listed choices.')
            elif value and q.kind == Question.RATING and value not in ('1', '2', '3', '4', '5'):
                errors[q.pk] = _('Choose a rating from 1 to 5.')
            elif value and q.kind == Question.DATE:
                try:
                    value = datetime.date.fromisoformat(value).isoformat()
                except ValueError:
                    errors[q.pk] = _('Write a real date.')
        if q.required and not value and not values and q.pk not in errors:
            errors[q.pk] = _('This question needs an answer.')
        if value or values:
            answers.append((q, value, values))
    return answers, errors


def summary(form):
    """One entry per question for the results page: the choices with how many picked each, the ratings with their average,
    or the latest written answers."""
    from .models import Answer
    out = []
    for q in form.questions.all():
        rows = list(Answer.objects.filter(question=q).order_by('-id'))
        item = {'question': q, 'count': len(rows)}
        if q.kind in Question.WITH_OPTIONS:
            counts = {c: 0 for c in q.choices}
            for a in rows:
                for v in (a.values if q.kind == Question.MULTI else [a.value]):
                    if v in counts:
                        counts[v] += 1
            top = max(counts.values(), default=0) or 1
            item['bars'] = [{'label': c, 'n': n, 'pct': round(100 * n / max(len(rows), 1)), 'width': round(100 * n / top)} for c, n in counts.items()]
        elif q.kind == Question.RATING:
            marks = [int(a.value) for a in rows if a.value.isdigit()]
            counts = {i: marks.count(i) for i in range(1, 6)}
            top = max(counts.values(), default=0) or 1
            item['average'] = round(sum(marks) / len(marks), 1) if marks else None
            item['bars'] = [{'label': str(i), 'n': n, 'pct': round(100 * n / max(len(marks), 1)), 'width': round(100 * n / top)} for i, n in counts.items()]
        else:
            item['texts'] = [a.value for a in rows[:30]]
        out.append(item)
    return out


def _safe(text):
    """A cell that a spreadsheet would run as a formula is made plain text (the answers come from strangers)."""
    text = str(text)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text


def to_csv(form):
    """The answers as CSV text (with a byte-order mark so Excel reads Arabic), one row per response."""
    questions = list(form.questions.all())
    out = io.StringIO()
    out.write('﻿')
    writer = csv.writer(out)
    writer.writerow([_('Date'), _('Person')] + [_safe(q.text) for q in questions])
    for response in form.responses.select_related('user').prefetch_related('answers'):
        by_question = {a.question_id: a for a in response.answers.all()}
        writer.writerow([response.created_at.strftime('%Y-%m-%d %H:%M'), getattr(response.user, 'email', '')] +
                        [_safe(by_question[q.pk].shown) if q.pk in by_question else '' for q in questions])
    return out.getvalue()
