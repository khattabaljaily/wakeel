"""Which language a person (or a company's team) reads Wakeel in."""
from django.conf import settings

LANGUAGE_NAMES = {'ar': 'Arabic (Modern Standard Arabic)', 'en': 'English'}


def of_user(user):
    return (getattr(user, 'language', '') or settings.LANGUAGE_CODE) if user else settings.LANGUAGE_CODE


def of_team(company):
    """The company owner's language: what team-facing AI text (strategy, lessons) is written in."""
    from apps.companies.models import Membership
    owner = company.memberships.filter(role=Membership.Role.OWNER).select_related('user').first()
    return of_user(owner.user if owner else None)


def name(code):
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES[settings.LANGUAGE_CODE])
