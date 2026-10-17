from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class InputRisk:
    blocked: bool
    reasons: tuple[str, ...] = ()


INJECTION_PATTERNS = (
    ("instruction_override", re.compile(r"(?:忽略|无视|跳过|忘记).{0,20}(?:之前|上面|系统).{0,20}(?:指令|规则|提示|约束)|ignore.{0,20}(?:previous|above|system).{0,20}(?:instruction|rule|prompt)", re.I)),
    ("prompt_extraction", re.compile(r"(?:泄露|展示|打印|告诉我).{0,20}(?:系统提示词|system prompt|内部提示|prompt)|(?:reveal|show|print|tell me).{0,20}(?:system prompt|internal prompt)", re.I)),
    ("privilege_escalation", re.compile(r"(?:我是管理员|把我当作管理员|授予我).{0,20}(?:管理员|admin|最高权限)|(?:make me|grant me).{0,20}(?:admin|administrator|root)", re.I)),
    ("cross_user_access", re.compile(r"(?:别人的|其他用户|他人的).{0,20}(?:订单|地址|手机号|会话|购买记录)|(?:another|other|someone else's).{0,20}(?:order|address|phone|session|purchase)", re.I)),
)

PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
ID_CARD_RE = re.compile(r"(?<!\d)\d{6}\d{8}\d{3}[0-9X](?!\d)", re.I)
ADDRESS_RE = re.compile(r"[^，。；,.;]{0,40}(?:省|市|区|县|路|街|号|室)[^，。；,.;]{0,20}")


def scan_input(text: str) -> InputRisk:
    reasons = tuple(name for name, pattern in INJECTION_PATTERNS if pattern.search(text))
    return InputRisk(blocked=bool(reasons), reasons=reasons)


def redact_pii(text: str) -> str:
    value = PHONE_RE.sub("[PHONE_REDACTED]", text)
    value = EMAIL_RE.sub("[EMAIL_REDACTED]", value)
    value = ID_CARD_RE.sub("[ID_REDACTED]", value)
    return ADDRESS_RE.sub("[ADDRESS_REDACTED]", value)


def moderate_output(text: str) -> str:
    if re.search(r"(?:系统提示词|system prompt|api key|sk-[a-zA-Z0-9]{12,})", text, re.I):
        return "抱歉，我不能提供内部提示词、密钥或其他受保护信息。"
    return redact_pii(text)


def require_tool_permission(user_id: int, authenticated: bool, tool_name: str) -> None:
    protected = {"list_order_history", "get_order_detail", "cancel_order", "refund_order"}
    if tool_name in protected and not authenticated:
        raise PermissionError("LOGIN_REQUIRED")
    if user_id <= 0:
        raise PermissionError("INVALID_USER")
