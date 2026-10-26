"""Реестр политик типов заявок и охранников изменений.

Другие модули (например, investments) регистрируют здесь свои политики при старте,
а requests обращается только к реестру и не импортирует эти модули.
"""
from __future__ import annotations

from typing import Callable, Protocol

from rest_framework.exceptions import ValidationError

from apps.modules.requests.models import Request
from apps.modules.requests.payment_type_families import INVEST_PAYMENT_TYPES


class PaymentTypePolicy(Protocol):
    def is_available(self, *, tenant) -> bool: ...

    def normalize_attrs(self, *, tenant, attrs: dict, instance: Request | None) -> dict:
        """Может поднять ValidationError."""
        ...

    def form_hint(self, *, tenant) -> dict | None:
        """{"wallet_id": int, "wallet_label": str, "currency": str | None} или None."""
        ...


RequestMutationGuard = Callable[[Request, dict], "str | None"]

_POLICIES: dict[str, PaymentTypePolicy] = {}
_MUTATION_GUARDS: list[RequestMutationGuard] = []


def register_payment_type_policy(payment_type: str, policy: PaymentTypePolicy) -> None:
    _POLICIES[payment_type] = policy


def get_payment_type_policy(payment_type: str) -> PaymentTypePolicy | None:
    return _POLICIES.get(payment_type)


def is_payment_type_available(*, tenant, payment_type: str) -> bool:
    policy = _POLICIES.get(payment_type)
    if policy is None:
        # Инвест-типы закрыты по умолчанию: без политики (модуль investments не загрузил её)
        # их нельзя выбрать. Остальные типы — без изменений.
        return payment_type not in INVEST_PAYMENT_TYPES
    return bool(policy.is_available(tenant=tenant))


def register_request_mutation_guard(guard: RequestMutationGuard) -> None:
    if guard not in _MUTATION_GUARDS:
        _MUTATION_GUARDS.append(guard)


def check_request_mutation(*, request_obj: Request, attrs: dict) -> None:
    for guard in _MUTATION_GUARDS:
        message = guard(request_obj, attrs)
        if message:
            raise ValidationError({"detail": message})


def _reset_registry_for_tests() -> None:
    _POLICIES.clear()
    _MUTATION_GUARDS.clear()


def _snapshot_registry_for_tests() -> object:
    return (dict(_POLICIES), list(_MUTATION_GUARDS))


def _restore_registry_for_tests(snapshot: object) -> None:
    policies, guards = snapshot  # type: ignore[misc]
    _POLICIES.clear()
    _POLICIES.update(policies)
    _MUTATION_GUARDS.clear()
    _MUTATION_GUARDS.extend(guards)
