from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class EmailOrUsernameBackend(ModelBackend):
    """Sign in with either the email address or the username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        User = get_user_model()
        user = User.objects.filter(email__iexact=username).first() or User.objects.filter(username=username).first()
        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        User().set_password(password)  # equalise timing when the user doesn't exist
        return None
