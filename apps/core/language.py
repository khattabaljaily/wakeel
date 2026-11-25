"""Which language a person (or a company's team) reads Wakeel in."""
from django.conf import settings

LANGUAGE_NAMES = {'ar': 'Arabic (Modern Standard Arabic)', 'en': 'English'}


def of_user(user):
    """The interface language the person reads in; one saved before the screens were cut to Arabic and English reads Arabic."""
    language = getattr(user, 'language', '') if user else ''
    return language if language in dict(settings.INTERFACE_LANGUAGES) else settings.LANGUAGE_CODE


def of_team(company):
    """The company owner's language: what team-facing AI text (strategy, lessons) is written in."""
    from apps.companies.models import Membership
    owner = company.memberships.filter(role=Membership.Role.OWNER).select_related('user').first()
    return of_user(owner.user if owner else None)


def name(code):
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES[settings.LANGUAGE_CODE])
