from bias_core.api_errors import api_error


def require_staff(request):
    if not getattr(request, "auth", None) or not request.auth.is_staff:
        return api_error("需要管理员权限", status=403)
    return None
