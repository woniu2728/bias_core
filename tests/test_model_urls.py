from types import SimpleNamespace

from django.test import TestCase

from bias_core.extensions.application_models import ApplicationModelUrlService
from bias_core.extensions.types import ExtensionModelSlugDriverDefinition


class FakeRuntimeView:
    model_slug_drivers = ()


class FakeHost:
    def __init__(self):
        self.views = {}

    def _get_or_create_runtime_view(self, extension_id):
        return self.views.setdefault(extension_id, FakeRuntimeView())


class InMemoryModel:
    pass


class IdSlugDriver:
    def __init__(self):
        self.instances = {
            1: SimpleNamespace(id=1, slug="alpha"),
            2: SimpleNamespace(id=2, slug="beta"),
        }

    def to_slug(self, instance, *, context=None):
        return f"{instance.id}-{instance.slug}"

    def from_slug(self, slug, *, context=None):
        tag_id = int(str(slug).split("-", 1)[0])
        return self.instances.get(tag_id)

    def from_slugs(self, slugs, *, context=None):
        return {
            slug: self.from_slug(slug)
            for slug in slugs
            if self.from_slug(slug) is not None
        }


class ModelUrlServiceTests(TestCase):
    def setUp(self):
        self.host = FakeHost()
        self.service = ApplicationModelUrlService(self.host)
        self.driver = IdSlugDriver()
        self.service.register_slug_driver(
            "tags",
            ExtensionModelSlugDriverDefinition(
                model=InMemoryModel,
                identifier="id_with_slug",
                driver=self.driver,
            ),
        )

    def test_to_slug_delegates_to_registered_driver(self):
        instance = SimpleNamespace(id=1, slug="alpha")

        self.assertEqual(
            self.service.to_slug(InMemoryModel, instance, identifier="id_with_slug"),
            "1-alpha",
        )

    def test_resolve_slug_delegates_to_registered_driver(self):
        resolved = self.service.resolve_slug(InMemoryModel, "1-renamed", identifier="id_with_slug")

        self.assertEqual(resolved.id, 1)

    def test_resolve_slugs_keeps_results_keyed_by_input_slug(self):
        resolved = self.service.resolve_slugs(
            InMemoryModel,
            ["1-renamed", "2-beta", "404-missing"],
            identifier="id_with_slug",
        )

        self.assertEqual(set(resolved), {"1-renamed", "2-beta"})
        self.assertEqual(resolved["1-renamed"].slug, "alpha")
        self.assertEqual(resolved["2-beta"].slug, "beta")
