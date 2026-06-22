from __future__ import annotations

from typing import Any


def normalize_secret_value(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip()


def looks_like_placeholder_secret(value: str | None) -> bool:
    if not value:
        return True

    value = value.strip()
    if not value or len(value) < 32:
        return True

    lower = value.lower()
    placeholder_patterns = [
        "dev",
        "test",
        "change",
        "placeholder",
        "secret",
        "your-",
        "xxxx",
        "django-insecure",
    ]
    for pattern in placeholder_patterns:
        if pattern in lower:
            return True

    return False


def jwt_key_length_requirement(algorithm: str) -> int:
    algorithm = (algorithm or "").strip().upper()
    if algorithm.startswith("HS"):
        try:
            bits = int(algorithm[2:])
            return bits // 8
        except (ValueError, IndexError):
            return 0
    if algorithm.startswith("RS") or algorithm.startswith("ES"):
        return 0
    return 0


def build_auth_secret_risks(
    *,
    secret_key: str,
    jwt_algorithm: str,
    jwt_signing_key: str,
) -> list[dict[str, Any]]:
    risks: list[dict[str, Any]] = []

    if looks_like_placeholder_secret(secret_key):
        risks.append({
            "code": "secret-key-placeholder",
            "level": "danger",
            "title": "Django SECRET_KEY 仍为占位符或开发密钥",
            "message": "当前密钥强度不足，容易在 CSRF、会话签名和 JWT 签名等场景中被预测。",
        })
    elif len(normalize_secret_value(secret_key)) < 32:
        risks.append({
            "code": "secret-key-short",
            "level": "danger",
            "title": "Django SECRET_KEY 长度不足",
            "message": "密钥长度应不少于 32 字符。",
        })

    required_len = jwt_key_length_requirement(jwt_algorithm)
    if required_len > 0 and len(normalize_secret_value(jwt_signing_key)) < required_len:
        risks.append({
            "code": "jwt-signing-key-short",
            "level": "warning",
            "title": "JWT 签名密钥长度不足",
            "message": f"{jwt_algorithm} 要求密钥长度至少为 {required_len} 字节。",
        })

    if looks_like_placeholder_secret(jwt_signing_key):
        risks.append({
            "code": "jwt-signing-key-placeholder",
            "level": "warning",
            "title": "JWT 签名密钥仍为占位符",
            "message": "当前 JWT 签名密钥稳定性不足，容易被字典攻击或彩虹表破解。",
        })

    return risks


def build_auth_secret_status(*, risks: list[dict[str, Any]]) -> dict[str, Any]:
    if not risks:
        return {
            "status": "secure",
            "label": "密钥安全",
            "message": "当前密钥配置符合安全要求，未检测到已知风险。",
        }

    danger_count = sum(1 for r in risks if r.get("level") == "danger")
    warning_count = sum(1 for r in risks if r.get("level") == "warning")

    if danger_count > 0:
        status = "insecure"
        label = "存在安全风险"
    else:
        status = "warning"
        label = "存在安全建议"

    messages = [r["message"] for r in risks]
    return {
        "status": status,
        "label": label,
        "message": "；".join(messages),
        "danger_count": danger_count,
        "warning_count": warning_count,
    }
