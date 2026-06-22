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
from django.contrib.auth.models import AnonymousUser
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
from unittest.mock import Mock, patch
