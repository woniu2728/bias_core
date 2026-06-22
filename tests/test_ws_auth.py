from django.test import TestCase, override_settings
from django.contrib.auth.models import AnonymousUser, User
from ninja_jwt.tokens import RefreshToken

from bias_core.jwt_auth import (
    REFRESH_TOKEN_COOKIE_NAME,
    resolve_user_from_access_token,
)
from bias_core.websocket_auth import _parse_cookie_header


class WebSocketJwtAuthTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="ws-user",
            email="ws-user@example.com",
            password="password123",
        )

    def test_valid_token_resolves_user_for_websocket(self):
        token = str(RefreshToken.for_user(self.user).access_token)
        resolved_user = resolve_user_from_access_token(token)
        self.assertEqual(resolved_user.id, self.user.id)

    def test_invalid_token_returns_anonymous_user(self):
        resolved_user = resolve_user_from_access_token("invalid-token")
        self.assertIsInstance(resolved_user, type(None))

    def test_cookie_parser_extracts_refresh_token(self):
        scope = {
            "headers": [
                (b"cookie", f"theme=light; {REFRESH_TOKEN_COOKIE_NAME}=refresh-token-value".encode()),
            ]
        }
        cookies = _parse_cookie_header(scope)
        self.assertEqual(cookies[REFRESH_TOKEN_COOKIE_NAME], "refresh-token-value")
