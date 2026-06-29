from types import SimpleNamespace

from django.test import TestCase

from bias_core.extensions.application_models import ApplicationModelUrlService
from bias_core.extensions.types import ExtensionModelSlugDriverDefinition
from bias_core.models import Setting


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
        self.seen_batches = []

    def to_slug(self, instance, *, context=None):
        return f"{instance.id}-{instance.slug}"

    def from_slug(self, slug, *, context=None):
        tag_id = int(str(slug).split("-", 1)[0])
        return self.instances.get(tag_id)

    def from_slugs(self, slugs, *, context=None):
        self.seen_batches.append(tuple(slugs))
        return {
            slug: self.from_slug(slug)
            for slug in slugs
            if self.from_slug(slug) is not None
        }


class PlainSlugDriver:
    def __init__(self):
        self.instances = {
            "alpha": SimpleNamespace(id=1, slug="alpha"),
            "beta": SimpleNamespace(id=2, slug="beta"),
        }

    def to_slug(self, instance, *, context=None):
        return instance.slug

    def from_slug(self, slug, *, context=None):
        return self.instances.get(str(slug or "").strip())

    def from_slugs(self, slugs, *, context=None):
        return {
            slug: self.from_slug(slug)
            for slug in slugs
            if self.from_slug(slug) is not None
        }


class SingleSlugOnlyDriver:
    def __init__(self):
        self.instances = {
            "alpha": SimpleNamespace(id=1, slug="alpha"),
            "beta": SimpleNamespace(id=2, slug="beta"),
        }
        self.calls = []

    def from_slug(self, slug, *, context=None):
        self.calls.append(str(slug or "").strip())
        return self.instances.get(str(slug or "").strip())


class ModelUrlServiceTests(TestCase):
    def setUp(self):
        self.host = FakeHost()
        self.service = ApplicationModelUrlService(self.host)
        self.default_driver = PlainSlugDriver()
        self.service.register_slug_driver(
            "tags",
            ExtensionModelSlugDriverDefinition(
                model=InMemoryModel,
                identifier="default",
                driver=self.default_driver,
            ),
        )
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

    def test_resolve_slugs_deduplicates_inputs_before_batch_driver(self):
        resolved = self.service.resolve_slugs(
            InMemoryModel,
            ["1-renamed", "2-beta", "1-renamed", "", "2-beta"],
            identifier="id_with_slug",
        )

        self.assertEqual(set(resolved), {"1-renamed", "2-beta"})
        self.assertEqual(self.driver.seen_batches, [("1-renamed", "2-beta")])

    def test_resolve_slugs_deduplicates_single_slug_driver_fallback(self):
        driver = SingleSlugOnlyDriver()
        self.service.register_slug_driver(
            "tags",
            ExtensionModelSlugDriverDefinition(
                model=InMemoryModel,
                identifier="single_only",
                driver=driver,
            ),
        )

        resolved = self.service.resolve_slugs(
            InMemoryModel,
            ["alpha", "beta", "alpha", "missing", "beta"],
            identifier="single_only",
        )

        self.assertEqual(set(resolved), {"alpha", "beta"})
        self.assertEqual(driver.calls, ["alpha", "beta", "missing"])

    def test_active_slug_driver_defaults_to_default_driver(self):
        instance = SimpleNamespace(id=1, slug="alpha")

        self.assertEqual(self.service.to_slug(InMemoryModel, instance, identifier=None), "alpha")
        self.assertEqual(self.service.resolve_slug(InMemoryModel, "alpha", identifier=None).id, 1)

    def test_active_slug_driver_uses_configured_setting(self):
        Setting.objects.update_or_create(
            key=self.service.active_slug_driver_setting_key(InMemoryModel),
            defaults={"value": '"id_with_slug"'},
        )

        instance = SimpleNamespace(id=1, slug="alpha")

        self.assertEqual(self.service.to_slug(InMemoryModel, instance, identifier=None), "1-alpha")
        self.assertEqual(self.service.resolve_slug(InMemoryModel, "1-renamed", identifier=None).id, 1)
        resolved = self.service.resolve_slugs(
            InMemoryModel,
            ["1-renamed", "2-beta"],
            identifier=None,
        )
        self.assertEqual(set(resolved), {"1-renamed", "2-beta"})

    def test_active_slug_driver_falls_back_to_default_for_unknown_setting(self):
        Setting.objects.update_or_create(
            key=self.service.active_slug_driver_setting_key(InMemoryModel),
            defaults={"value": '"missing"'},
        )

        instance = SimpleNamespace(id=1, slug="alpha")

        self.assertEqual(self.service.to_slug(InMemoryModel, instance, identifier=None), "alpha")
        self.assertEqual(self.service.resolve_slug(InMemoryModel, "alpha", identifier=None).id, 1)

    def test_explicit_slug_driver_ignores_active_setting(self):
        Setting.objects.update_or_create(
            key=self.service.active_slug_driver_setting_key(InMemoryModel),
            defaults={"value": '"id_with_slug"'},
        )

        instance = SimpleNamespace(id=1, slug="alpha")

        self.assertEqual(self.service.to_slug(InMemoryModel, instance, identifier="default"), "alpha")

    def test_clear_active_slug_driver_cache_reloads_setting(self):
        key = self.service.active_slug_driver_setting_key(InMemoryModel)
        Setting.objects.update_or_create(key=key, defaults={"value": '"id_with_slug"'})
        self.assertEqual(
            self.service.to_slug(InMemoryModel, SimpleNamespace(id=1, slug="alpha"), identifier=None),
            "1-alpha",
        )

        Setting.objects.update_or_create(key=key, defaults={"value": '"default"'})
        self.assertEqual(
            self.service.to_slug(InMemoryModel, SimpleNamespace(id=1, slug="alpha"), identifier=None),
            "1-alpha",
        )

        self.service.clear_active_slug_driver_cache()
        self.assertEqual(
            self.service.to_slug(InMemoryModel, SimpleNamespace(id=1, slug="alpha"), identifier=None),
            "alpha",
        )
