from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeServiceContract:
    service_key: str
    provider_extension: str
    required_methods: tuple[str, ...] = ()
    required_values: tuple[str, ...] = ()
    optional_methods: tuple[str, ...] = ()
    callable_service: bool = False


@dataclass(frozen=True)
class ResolvedRuntimeServiceContract:
    contract: RuntimeServiceContract
    source: str


RUNTIME_SERVICE_CONTRACTS: dict[str, RuntimeServiceContract] = {}


def get_declared_runtime_service_contracts(host: Any) -> tuple[RuntimeServiceContract, ...]:
    if host is None:
        return ()
    getter = getattr(host, "get_runtime_views", None) or getattr(host, "get_extension_views", None)
    if not callable(getter):
        return ()
    contracts: dict[str, RuntimeServiceContract] = {}
    for view in getter() or ():
        extension_id = str(getattr(view, "extension_id", "") or getattr(view, "id", "") or "").strip()
        for contract in getattr(view, "runtime_service_contracts", ()) or ():
            normalized = _normalize_runtime_service_contract(contract, provider_extension=extension_id)
            if normalized is not None:
                contracts[normalized.service_key] = normalized
    return tuple(contracts[key] for key in sorted(contracts))


def get_runtime_service_contracts(
    *,
    host: Any | None = None,
    provider_extension: str | None = None,
) -> tuple[RuntimeServiceContract, ...]:
    return tuple(
        resolved.contract
        for resolved in get_resolved_runtime_service_contracts(
            host=host,
            provider_extension=provider_extension,
        )
    )


def get_resolved_runtime_service_contracts(
    *,
    host: Any | None = None,
    provider_extension: str | None = None,
) -> tuple[ResolvedRuntimeServiceContract, ...]:
    normalized_provider = str(provider_extension or "").strip()
    contracts_by_key = {
        key: ResolvedRuntimeServiceContract(contract=contract, source="core_fallback")
        for key, contract in RUNTIME_SERVICE_CONTRACTS.items()
    }
    contracts_by_key.update({
        contract.service_key: ResolvedRuntimeServiceContract(contract=contract, source="declared")
        for contract in get_declared_runtime_service_contracts(host)
    })
    contracts = tuple(contracts_by_key[key] for key in sorted(contracts_by_key))
    if not normalized_provider:
        return contracts
    return tuple(
        resolved
        for resolved in contracts
        if resolved.contract.provider_extension == normalized_provider
    )


def inspect_runtime_service_contract_sources(host: Any, *, provider_extension: str | None = None) -> list[dict]:
    return [
        _source_issue(resolved.contract, "runtime_service_contract_uses_core_fallback")
        for resolved in get_resolved_runtime_service_contracts(
            host=host,
            provider_extension=provider_extension,
        )
        if resolved.source == "core_fallback"
    ]


def inspect_runtime_service_contracts(host: Any, *, provider_extension: str | None = None) -> list[dict]:
    issues: list[dict] = []
    if host is None:
        return issues
    for contract in get_runtime_service_contracts(host=host, provider_extension=provider_extension):
        if not _host_provider_registered(host, contract):
            issues.append(_issue(contract, "missing_provider_registration", contract.service_key))
        service = _resolve_host_service(host, contract.service_key)
        if service is None:
            issues.append(_issue(contract, "missing_service", contract.service_key))
            continue
        if contract.callable_service and not callable(service):
            issues.append(_issue(contract, "service_not_callable", contract.service_key))
        for name in contract.required_values:
            if _service_value(service, name, _MISSING) is _MISSING:
                issues.append(_issue(contract, "missing_value", name))
        for name in contract.required_methods:
            if not callable(_service_value(service, name, None)):
                issues.append(_issue(contract, "missing_method", name))
    return issues


def snapshot_runtime_service_contracts(*, host: Any | None = None) -> list[dict]:
    return [
        {
            "service_key": contract.service_key,
            "provider_extension": contract.provider_extension,
            "required_methods": sorted(contract.required_methods),
            "required_values": sorted(contract.required_values),
            "optional_methods": sorted(contract.optional_methods),
            "callable_service": bool(contract.callable_service),
            "source": resolved.source,
        }
        for resolved in get_resolved_runtime_service_contracts(host=host)
        for contract in (resolved.contract,)
    ]


def _resolve_host_service(host: Any, key: str):
    getter = getattr(host, "make", None) or getattr(host, "get_service", None)
    if not callable(getter):
        return None
    try:
        return getter(key, None)
    except TypeError:
        try:
            return getter(key)
        except (KeyError, TypeError):
            return None
    except KeyError:
        return None


def _host_provider_registered(host: Any, contract: RuntimeServiceContract) -> bool:
    getter = getattr(host, "get_service_provider_keys", None)
    if not callable(getter):
        return True
    try:
        keys = getter(extension_id=contract.provider_extension)
    except TypeError:
        return True
    return contract.service_key in {str(item or "").strip() for item in keys or ()}


def _service_value(service: Any, name: str, default: Any = None):
    if isinstance(service, dict):
        return service.get(name, default)
    return getattr(service, name, default)


def _issue(contract: RuntimeServiceContract, code: str, member: str) -> dict:
    return {
        "code": code,
        "service_key": contract.service_key,
        "provider_extension": contract.provider_extension,
        "member": member,
    }


def _source_issue(contract: RuntimeServiceContract, code: str) -> dict:
    payload = _issue(contract, code, contract.service_key)
    payload["severity"] = "warning"
    return payload


def _normalize_runtime_service_contract(
    contract: RuntimeServiceContract,
    *,
    provider_extension: str = "",
) -> RuntimeServiceContract | None:
    service_key = str(getattr(contract, "service_key", "") or "").strip()
    if not service_key:
        return None
    provider = str(provider_extension or getattr(contract, "provider_extension", "") or "").strip()
    return RuntimeServiceContract(
        service_key=service_key,
        provider_extension=provider,
        required_methods=_normalize_contract_names(getattr(contract, "required_methods", ()) or ()),
        required_values=_normalize_contract_names(getattr(contract, "required_values", ()) or ()),
        optional_methods=_normalize_contract_names(getattr(contract, "optional_methods", ()) or ()),
        callable_service=bool(getattr(contract, "callable_service", False)),
    )


def _normalize_contract_names(values) -> tuple[str, ...]:
    return tuple(
        item
        for item in sorted({str(value or "").strip() for value in values or ()})
        if item
    )


def _validate_runtime_service_contracts() -> None:
    for service_key, contract in RUNTIME_SERVICE_CONTRACTS.items():
        if service_key != contract.service_key:
            raise RuntimeError(f"runtime service contract key mismatch: {service_key} != {contract.service_key}")
        if not contract.provider_extension:
            raise RuntimeError(f"runtime service contract is missing provider extension: {service_key}")
        for field in ("required_methods", "required_values", "optional_methods"):
            values = tuple(getattr(contract, field))
            normalized_values = tuple(str(item or "").strip() for item in values)
            if values != normalized_values:
                raise RuntimeError(f"runtime service contract {service_key}.{field} contains unnormalized names")
            if any(not item for item in normalized_values):
                raise RuntimeError(f"runtime service contract {service_key}.{field} contains empty names")
            if tuple(sorted(normalized_values)) != normalized_values:
                raise RuntimeError(f"runtime service contract {service_key}.{field} must be sorted")
            if len(set(normalized_values)) != len(normalized_values):
                raise RuntimeError(f"runtime service contract {service_key}.{field} contains duplicate names")
        overlap = set(contract.required_methods) & set(contract.optional_methods)
        if overlap:
            names = ", ".join(sorted(overlap))
            raise RuntimeError(f"runtime service contract {service_key} has required/optional overlap: {names}")


_MISSING = object()


_validate_runtime_service_contracts()


__all__ = [
    "RUNTIME_SERVICE_CONTRACTS",
    "ResolvedRuntimeServiceContract",
    "RuntimeServiceContract",
    "get_declared_runtime_service_contracts",
    "get_resolved_runtime_service_contracts",
    "get_runtime_service_contracts",
    "inspect_runtime_service_contract_sources",
    "inspect_runtime_service_contracts",
    "snapshot_runtime_service_contracts",
]
