import importlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
import shutil
from io import StringIO
import sys
from types import ModuleType, SimpleNamespace
import uuid

from django.conf import settings
from django.apps import apps
from django.contrib.auth.models import AnonymousUser, Group, Permission, User
from django.core.cache import cache
from django.core.checks import run_checks
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command, CommandError
from django.db import OperationalError, connection
from django.db.migrations.recorder import MigrationRecorder
from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, path
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken
from unittest.mock import Mock, patch

# ─── bias_core core models ───
from bias_core.models import Setting, AuditLog, ExtensionInstallation

# ─── bias_core services ───
from bias_core.domain_events import DomainEvent, DomainEventBus, get_forum_event_bus
from bias_core.settings_service import clear_runtime_setting_caches
from bias_core.forum_permissions import has_forum_permission

# ─── bias_core resource API ───
from bias_core.resource_registry import ResourceRegistry, get_resource_registry
from bias_core.resource_objects import DatabaseResource, ResourceEndpoint, ResourceField, ResourceRelationship, ResourceSort, ResourceFilter, Resource
from bias_core.resource_context import ResourceContext
from bias_core.resource_dispatcher import dispatch_resource_endpoint
from bias_core.resource_routes import build_resource_path_route_definitions, build_resource_route_definitions
from bias_core.resource_search import ResourceSearchFilter, ResourceSearchManager, ResourceSearchState
from bias_core.resource_serializer import ResourceSerializer
from bias_core.resource_validation import ResourceValidationError, ResourceValidator, ResourceValidatorFactory

# ─── bias_core extensions ───
from bias_core.extensions import ApiResourceExtender, ConditionalExtender, PostEventExtender, SearchDriverExtender
from bias_core.extensions.extenders import ResourceExtender, ValidatorExtender, MailExtender
from bias_core.extensions.registry import ExtensionRegistry
from bias_core.extensions.types import (
    ExtensionResourceDefinition, ExtensionResourceFieldDefinition,
    ExtensionResourceRelationshipDefinition, ExtensionResourceSortDefinition,
    ExtensionResourceFilterDefinition, ExtensionResourceEndpointDefinition,
)
from bias_core.extensions.backend import run_extension_backend_hook

# ─── bias_core diagnostics ───
from bias_core.extension_diagnostics import classify_extension_diagnostics, summarize_extension_delivery

# ─── bias_core extension service ───
from bias_core.extension_service import ExtensionService

# ─── bias_core extensions management ───
from bias_core.extensions.runtime_service import get_enabled_extension_runtime_entries
from bias_core.extensions.lifecycle import reset_extension_runtime_state
from bias_core.extensions.recovery import serialize_extension_recovery_state
from bias_core.extensions.bootstrap import bootstrap_extension_host, build_extension_application
from bias_core.extensions.frontend_runtime_service import bootstrap_extension_frontend_runtime
from bias_core.extensions.frontend_runtime_service import build_enabled_frontend_document_payload as build_frontend_payload
from bias_core.extensions.frontend_compiler import build_extension_frontend_output_manifest, get_extension_frontend_import_map_path
from bias_core.extensions.manifest import ExtensionManifest, ExtensionManifestLoader
from bias_core.extensions.exceptions import ExtensionStateError
from bias_core.extensions.assembly_service import get_enabled_extension_assemblies
from bias_core.extensions.frontend_compiler import build_extension_frontend_output_manifest

# ─── bias_core forum ───
from bias_core.forum_registry import get_forum_registry, ForumRegistry
from bias_core.extensions.forum_registry_types import ForumModuleDefinition

# ─── bias_core extension runtime ───
from bias_core.extensions.extension_runtime import Extension
from bias_core.extensions.application import ExtensionApplication, ExtensionHost
from bias_core.extensions.application_runtime import ExtensionRuntimeView

# ─── bias_core extension discovery ───
from bias_core.extension_django_apps import discover_extension_django_apps, discover_extension_django_migration_modules
from bias_core.extension_diagnostics import classify_extension_diagnostics, summarize_extension_delivery

# ─── bias_core bootstrap/auth ───
from bias_core.api_runtime import build_api_application
from bias_core.middleware import ExtensionRequestMiddleware
from bias_core.test_runner import BiasDiscoverRunner

# ─── Test utilities ───
def make_workspace_temp_dir():
    return Path(tempfile.mkdtemp(prefix="bias_test_"))

def call_command_quietly(command_name: str, *args, **kwargs):
    out = StringIO()
    kwargs.setdefault('stdout', out)
    kwargs.setdefault('stderr', out)
    try:
        call_command(command_name, *args, **kwargs)
    except SystemExit:
        pass
    return out.getvalue()

@dataclass(frozen=True)
class AlphaStringEvent(DomainEvent):
    value: str

