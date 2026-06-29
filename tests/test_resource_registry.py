from tests.common import *

class ResourceRegistryTests(TestCase):
    def test_api_resource_extender_registers_resource_in_bias_api_resources_contract(self):
        class ContractResource(Resource):
            def type(self):
                return "contract"

        app = ExtensionApplication()
        extension = app.get_or_create_runtime_view("alpha-tools")
        ApiResourceExtender.from_resource(ContractResource).extend(app, extension)

        self.assertIn(ContractResource, app.make("bias.api.resources"))

    def test_application_resource_service_replaces_same_runtime_definition_keys(self):
        from bias_core.extensions import (
            ExtensionResourceFieldDefinition,
            ExtensionResourceFilterDefinition,
            ExtensionResourceRelationshipDefinition,
        )

        app = ExtensionApplication()
        extension_id = "alpha-tools"

        app.resources.register_field(
            ExtensionResourceFieldDefinition(
                resource="discussion",
                field="summary",
                module_id=extension_id,
                resolver=lambda instance, context: "old",
            ),
            extension_id=extension_id,
        )
        app.resources.register_field(
            ExtensionResourceFieldDefinition(
                resource="discussion",
                field="summary",
                module_id=extension_id,
                resolver=lambda instance, context: "new",
            ),
            extension_id=extension_id,
        )
        app.resources.register_relationship(
            ExtensionResourceRelationshipDefinition(
                resource="discussion",
                relationship="tags",
                module_id=extension_id,
                resolver=lambda instance, context: ["old"],
            ),
            extension_id=extension_id,
        )
        app.resources.register_relationship(
            ExtensionResourceRelationshipDefinition(
                resource="discussion",
                relationship="tags",
                module_id=extension_id,
                resolver=lambda instance, context: ["new"],
            ),
            extension_id=extension_id,
        )
        app.resources.register_filter(
            ExtensionResourceFilterDefinition(
                resource="discussion",
                filter="tag",
                module_id=extension_id,
                handler=lambda queryset, value, context: ["old"],
            ),
            extension_id=extension_id,
        )
        app.resources.register_filter(
            ExtensionResourceFilterDefinition(
                resource="discussion",
                filter="tag",
                module_id=extension_id,
                handler=lambda queryset, value, context: ["new"],
            ),
            extension_id=extension_id,
        )

        runtime_view = app.get_runtime_view(extension_id)

        self.assertEqual(len(runtime_view.resource_fields), 1)
        self.assertEqual(runtime_view.resource_fields[0].resolver(None, {}), "new")
        self.assertEqual(len(runtime_view.resource_relationships), 1)
        self.assertEqual(runtime_view.resource_relationships[0].resolver(None, {}), ["new"])
        self.assertEqual(len(runtime_view.resource_filters), 1)
        self.assertEqual(runtime_view.resource_filters[0].handler([], "tag", {}), ["new"])
        self.assertEqual(len(app.resources.get_fields("discussion")), 1)
        self.assertEqual(app.resources.get_fields("discussion")[0].resolver(None, {}), "new")
        self.assertEqual(len(app.resources.get_relationships("discussion")), 1)
        self.assertEqual(app.resources.get_relationships("discussion")[0].resolver(None, {}), ["new"])
        self.assertEqual(len(app.resources.get_filters("discussion")), 1)
        self.assertEqual(app.resources.get_filters("discussion")[0].handler([], "tag", {}), ["new"])

    def test_extension_runtime_reset_allows_core_resources_to_rebootstrap(self):
        from bias_core.forum_resources import bootstrap_forum_resource_fields

        reset_extension_runtime_state()
        registry = get_resource_registry()
        bootstrap_forum_resource_fields(registry)

        self.assertIsNotNone(registry.get_resource("forum"))
        self.assertIsNotNone(registry.get_resource("admin_stats"))

    def test_core_resources_bootstrap_per_resource_registry_instance(self):
        from bias_core.forum_resources import bootstrap_forum_resource_fields

        first = ResourceRegistry()
        second = ResourceRegistry()

        bootstrap_forum_resource_fields(first)
        bootstrap_forum_resource_fields(second)

        self.assertIsNotNone(first.get_resource("forum"))
        self.assertIsNotNone(second.get_resource("forum"))

    def test_endpoint_definition_builds_own_pipeline(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="hello"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "pipeline_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

        resource = ItemResource()
        definition = ResourceEndpointDefinition(
            resource="pipeline_items",
            endpoint="show",
            module_id="core",
            kind="show",
        )
        pipeline = definition.build_pipeline(registry, resource)
        context = ResourceContext({"object_id": "1", "include": ()}).with_resource("pipeline_items")

        result = pipeline.action(context)

        self.assertEqual(result.title, "hello")

    def test_resource_field_supports_create_and_update_only_writable_helpers(self):
        create_only = ResourceField("title", resolver=lambda instance, context: instance.title).writable_on_create_field()
        update_only = ResourceField("state", resolver=lambda instance, context: instance.state).writable_on_update_field()

        self.assertTrue(create_only.is_writable({"creating": True}))
        self.assertFalse(create_only.is_writable({"creating": False}))
        self.assertFalse(update_only.is_writable({"creating": True}))
        self.assertTrue(update_only.is_writable({"creating": False}))

    def test_serializes_registered_resource_fields(self):
        registry = ResourceRegistry()

        class Target:
            id = 3
            title = "hello"

        registry.register_field(
            ResourceFieldDefinition(
                resource="discussion",
                field="summary",
                module_id="test",
                resolver=lambda instance, context: f"{instance.id}:{context['suffix']}",
            )
        )

        payload = registry.serialize("discussion", Target(), {"suffix": "ok"})
        self.assertEqual(payload, {"summary": "3:ok"})

    def test_preload_plan_applies_resource_field_annotations(self):
        registry = ResourceRegistry()

        class QuerySet:
            def __init__(self):
                self.annotations = None

            def annotate(self, **annotations):
                self.annotations = annotations
                return self

        registry.register_field(
            ResourceFieldDefinition(
                resource="post",
                field="like_count",
                module_id="likes",
                resolver=lambda instance, context: 0,
                annotate_resolver=lambda context: {"likes_count": "COUNT(likes)"},
            )
        )

        plan = registry.build_preload_plan("post", {})
        queryset = registry.apply_preload_plan(QuerySet(), "post", {})

        self.assertEqual(plan.annotations, (("likes_count", "COUNT(likes)"),))
        self.assertEqual(queryset.annotations, {"likes_count": "COUNT(likes)"})

    def test_resource_definition_mutators_raise_for_invalid_return_type(self):
        registry = ResourceRegistry()
        registry.register_field(
            ResourceFieldDefinition(
                resource="discussion",
                field="title",
                module_id="core",
                resolver=lambda instance, context: "title",
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="title",
                module_id="extension",
                mutator=lambda field: {"name": "title"},
            )
        )

        with self.assertRaises(TypeError):
            registry.get_effective_fields("discussion")

    def test_resource_validator_supports_laravel_like_rules(self):
        validator = ResourceValidatorFactory().make(
            {
                "title": "hello",
                "slug": "hello",
                "status": "archived",
                "summary": "abcd",
            },
            {
                "slug": ("same:title",),
                "status": (("not_in", ("deleted",)),),
                "summary": ("size:4", "different:title"),
            },
        )

        self.assertFalse(validator.fails())

    def test_resource_validator_supports_nested_wildcard_rules(self):
        validator = ResourceValidatorFactory().make(
            {
                "items": [
                    {"name": "alpha"},
                    {"name": ""},
                ],
            },
            {
                "items.*.name": ("required",),
            },
        )

        self.assertTrue(validator.fails())
        self.assertEqual(validator.jsonapi_errors()[0]["source"]["pointer"], "/data/attributes/items.1.name")

    def test_resource_relationship_exposes_schema_field_api(self):
        relationship = (
            ResourceRelationship("owner", resolver=lambda instance, context: instance.owner)
            .to_one("users")
            .include_when(lambda context: context.get("include_owner"))
            .with_linkage(lambda value, context: {"type": "users", "id": str(value.id)})
            .scope(lambda queryset, context: queryset)
            .prefetch_to("visible_owner")
        )

        self.assertEqual(relationship.field, "owner")
        self.assertTrue(relationship.is_relationship)
        self.assertEqual(relationship.collections(), ("users",))
        self.assertTrue(relationship.is_includable({"include_owner": True}))
        self.assertEqual(relationship.linkage_value(SimpleNamespace(id=7), {}), {"type": "users", "id": "7"})
        self.assertTrue(callable(relationship.scope_callback))
        self.assertEqual(relationship.prefetch_to_attr, "visible_owner")

    def test_search_manager_resolves_filters_and_mutators_from_container(self):
        app = ExtensionApplication()

        def filter_handler(state, value, context):
            state.queryset = [item for item in state.queryset if item == value]
            return state

        def mutator(state, criteria):
            state.queryset = [f"mutated:{item}" for item in state.queryset]
            return state

        app.instance("alpha.search.filter", ResourceSearchFilter("only", filter_handler))
        app.instance("alpha.search.mutator", mutator)
        manager = ResourceSearchManager(container=app)
        manager.register_searcher(str, lambda queryset, criteria, context: queryset, searcher_key="strings")
        manager.register_driver_filter("database", "strings", "alpha.search.filter")
        manager.add_driver_mutator("database", "strings", "alpha.search.mutator")

        result = manager.query(
            str,
            ["a", "b"],
            ResourceSearchCriteria(filters={"only": "b"}),
            {},
        )

        self.assertEqual(result.results, ["mutated:b"])

    def test_search_manager_replaces_indexer_with_same_component_key(self):
        manager = ResourceSearchManager()
        received = []

        class Item:
            pass

        class DemoIndexer:
            def __init__(self, label):
                self.label = label

            def index(self, instance, context):
                received.append(self.label)

        first = DemoIndexer("first")
        replacement = DemoIndexer("replacement")

        manager.register_indexer(Item, first)
        manager.register_indexer(Item, replacement)
        manager.index(Item, Item())

        self.assertEqual(received, ["replacement"])
        self.assertEqual(manager.indexers(Item), (replacement,))

    def test_search_manager_registers_driver_class_contract(self):
        manager = ResourceSearchManager()

        class DemoDriver:
            name = "demo"

            def supports(self, model):
                return False

        manager.register_driver_class(DemoDriver)

        self.assertIn(DemoDriver, manager.driver_classes())
        self.assertIsInstance(manager.driver("demo"), DemoDriver)

    def test_serializes_base_resource_and_relationship_includes(self):
        registry = ResourceRegistry()

        class Target:
            id = 8
            title = "hello"
            owner = type("Owner", (), {"username": "neo"})()

        registry.register_resource(
            ResourceDefinition(
                resource="discussion",
                module_id="test",
                resolver=lambda instance, context: {"id": instance.id, "title": instance.title},
            )
        )
        registry.register_field(
            ResourceFieldDefinition(
                resource="discussion",
                field="summary",
                module_id="test",
                resolver=lambda instance, context: f"{instance.id}:{context['suffix']}",
            )
        )
        registry.register_relationship(
            ResourceRelationshipDefinition(
                resource="discussion",
                relationship="owner",
                module_id="test",
                resolver=lambda instance, context: {"username": instance.owner.username},
            )
        )

        payload = registry.serialize(
            "discussion",
            Target(),
            {"suffix": "ok"},
            include=("owner",),
        )
        self.assertEqual(
            payload,
            {
                "id": 8,
                "title": "hello",
                "summary": "8:ok",
                "owner": {"username": "neo"},
            },
        )

    def test_resource_object_defines_base_fields_relationships_endpoints_and_sorts(self):
        registry = ResourceRegistry()

        class Target:
            id = 8
            title = "hello"
            owner = type("Owner", (), {"username": "neo"})()

        class DiscussionResource(Resource):
            module_id = "core"

            def type(self):
                return "discussion"

            def base(self, instance, context):
                return {"id": instance.id}

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: instance.title,
                        select_related=("state",),
                    ),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: {"username": instance.owner.username},
                        select_related=("owner",),
                    ),
                ]

            def endpoints(self):
                return [
                    ResourceEndpoint(
                        "show",
                        handler=lambda context: {"endpoint": context["endpoint"]},
                    )
                ]

            def sorts(self):
                return [
                    ResourceSort("hot", handler=("-hot_score",)),
                ]

        registry.register_resource(DiscussionResource)

        payload = registry.serialize("discussion", Target(), include=("owner",))
        plan = registry.build_preload_plan("discussion", include=("owner",))
        endpoint = registry.get_dispatch_endpoint("discussion", "show", "GET")

        self.assertEqual(payload, {"id": 8, "title": "hello", "owner": {"username": "neo"}})
        self.assertEqual(plan.select_related, ("state", "owner"))
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint.handler({"endpoint": "show"}), {"endpoint": "show"})
        self.assertTrue(registry.has_named_sort("discussion", "hot"))

    def test_resource_object_surfaces_are_mutated_by_bias_like_definitions(self):
        registry = ResourceRegistry()

        class Target:
            title = "hello"
            owner = type("Owner", (), {"username": "neo"})()

        class DiscussionResource(Resource):
            def type(self):
                return "discussion"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: {"username": instance.owner.username},
                        select_related=("owner",),
                    ),
                ]

            def endpoints(self):
                return [
                    ResourceEndpoint("show", handler=lambda context: {"version": 1}),
                ]

            def sorts(self):
                return [
                    ResourceSort("hot", handler=("hot",)),
                ]

        registry.register_resource(DiscussionResource())
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="title",
                module_id="extension",
                operation="mutate",
                mutator=lambda field: ResourceFieldDefinition(
                    resource="discussion",
                    field=field.field,
                    module_id="extension",
                    resolver=lambda instance, context: instance.title.upper(),
                ),
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="owner",
                module_id="extension",
                operation="mutate",
                mutator=lambda relationship: ResourceRelationshipDefinition(
                    resource="discussion",
                    relationship=relationship.relationship,
                    module_id="extension",
                    resolver=lambda instance, context: {"username": instance.owner.username.upper()},
                    select_related=("profile",),
                ),
            )
        )
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="discussion",
                endpoint="show",
                module_id="extension",
                operation="mutate",
                mutator=lambda endpoint: ResourceEndpointDefinition(
                    resource=endpoint.resource,
                    endpoint=endpoint.endpoint,
                    module_id=endpoint.module_id,
                    handler=lambda context: {"version": 2},
                ),
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="hot",
                module_id="extension",
                operation="mutate",
                mutator=lambda sort: ResourceSortDefinition(
                    resource=sort.resource,
                    sort=sort.sort,
                    module_id=sort.module_id,
                    handler=("-hot_score",),
                ),
            )
        )

        payload = registry.serialize("discussion", Target(), include=("owner",))
        plan = registry.build_preload_plan("discussion", include=("owner",))
        endpoint = registry.get_dispatch_endpoint("discussion", "show", "GET")
        queryset = Mock()
        ordered_queryset = Mock()
        queryset.order_by.return_value = ordered_queryset

        self.assertEqual(payload, {"title": "HELLO", "owner": {"username": "NEO"}})
        self.assertEqual(plan.select_related, ("profile",))
        self.assertEqual(endpoint.handler({}), {"version": 2})
        self.assertIs(registry.apply_named_sort("discussion", queryset, "hot"), ordered_queryset)
        queryset.order_by.assert_called_once_with("-hot_score")

    def test_resource_object_fields_support_visibility_and_write_pipeline(self):
        registry = ResourceRegistry()

        class Target:
            title = "hello"
            secret = "hidden"

        def validate_title(value, context):
            if len(value) < 3:
                raise ValueError("too short")

        class DemoResource(Resource):
            def type(self):
                return "demo"

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: instance.title,
                        writable=True,
                        required_on_create=True,
                        setter=lambda instance, value, context: setattr(instance, "title", value.strip()),
                        validator=validate_title,
                    ),
                    ResourceField(
                        "secret",
                        resolver=lambda instance, context: instance.secret,
                        visible=lambda instance, context: context.get("show_secret") is True,
                    ),
                ]

        registry.register_resource(DemoResource())
        target = Target()

        self.assertEqual(registry.serialize("demo", target), {"title": "hello"})
        self.assertEqual(
            registry.serialize("demo", target, {"show_secret": True}),
            {"title": "hello", "secret": "hidden"},
        )
        registry.apply_resource_payload("demo", target, {"title": " updated "}, creating=True)
        self.assertEqual(target.title, "updated")
        with self.assertRaises(ValueError):
            registry.apply_resource_payload("demo", target, {"title": "x"})
        with self.assertRaises(ValueError):
            registry.apply_resource_payload("demo", target, {}, creating=True)

    def test_resource_payload_ignores_fields_hidden_from_current_context(self):
        registry = ResourceRegistry()

        class Target:
            title = "hello"
            legacy = "plain"

        class DemoResource(Resource):
            def type(self):
                return "demo"

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: instance.title,
                        writable=True,
                        setter=lambda instance, value, context: setattr(instance, "title", value),
                    ),
                    ResourceField(
                        "legacy",
                        resolver=lambda instance, context: instance.legacy,
                        writable=True,
                        setter=lambda instance, value, context: setattr(instance, "legacy", value),
                    ).plain_only(),
                ]

        registry.register_resource(DemoResource())
        target = Target()
        context = {"request": RequestFactory().patch("/api/demo/1", HTTP_ACCEPT="application/vnd.api+json")}

        registry.apply_resource_payload("demo", target, {"title": "updated", "legacy": "wire"}, context)

        self.assertEqual(target.title, "updated")
        self.assertEqual(target.legacy, "plain")

    def test_resource_payload_supports_conditional_required_fields_and_relationships(self):
        registry = ResourceRegistry()

        class Target:
            title = ""
            owner = None

        class DemoResource(Resource):
            def type(self):
                return "demo"

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: instance.title,
                        writable=True,
                        required_on_create=lambda instance, context: context.get("require_title") is True,
                        setter=lambda instance, value, context: setattr(instance, "title", value),
                    ),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        writable=True,
                        required_on_create=lambda instance, context: context.get("require_owner") is True,
                        setter=lambda instance, value, context: setattr(instance, "owner", value),
                    ),
                ]

        registry.register_resource(DemoResource())

        registry.apply_resource_payload(
            "demo",
            Target(),
            {},
            {"require_title": False, "require_owner": False},
            creating=True,
        )

        with self.assertRaises(ValueError):
            registry.apply_resource_payload(
                "demo",
                Target(),
                {},
                {"require_title": True, "require_owner": False},
                creating=True,
            )

        with self.assertRaises(ValueError):
            registry.apply_resource_payload(
                "demo",
                Target(),
                {"title": "ok"},
                {"require_title": True, "require_owner": True},
                creating=True,
            )

        registry.validate_required_resource_payload(
            "demo",
            Target(),
            {},
            {"require_title": False, "require_owner": False},
            creating=True,
        )

        with self.assertRaises(ValueError):
            registry.validate_required_resource_payload(
                "demo",
                Target(),
                {},
                {"require_title": False, "require_owner": True},
                creating=True,
            )

    def test_resource_relationship_includable_controls_include_and_preload(self):
        registry = ResourceRegistry()

        class Target:
            owner = type("Owner", (), {"username": "neo"})()

        class DemoResource(Resource):
            def type(self):
                return "demo"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: {"username": instance.owner.username},
                        includable=lambda context: context.get("can_include") is True,
                        select_related=("owner",),
                    )
                ]

        registry.register_resource(DemoResource())

        self.assertEqual(registry.serialize("demo", Target(), include=("owner",)), {})
        self.assertEqual(registry.build_preload_plan("demo", include=("owner",)).select_related, ())
        self.assertEqual(
            registry.serialize("demo", Target(), {"can_include": True}, include=("owner",)),
            {"owner": {"username": "neo"}},
        )
        self.assertEqual(
            registry.build_preload_plan("demo", {"can_include": True}, include=("owner",)).select_related,
            ("owner",),
        )

    def test_resource_endpoint_metadata_builds_preload_plan(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "demo"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: None,
                        select_related=("owner",),
                    )
                ]

            def endpoints(self):
                return [
                    ResourceEndpoint(
                        "show",
                        handler=lambda context: {"include": context["default_include"]},
                    )
                    .add_default_include(["owner"])
                    .eager_load_with("comments")
                    .with_default_sort("-created_at")
                    .with_pagination()
                ]

        registry.register_resource(DemoResource())

        endpoint = registry.get_dispatch_endpoint("demo", "show", "GET")
        plan = registry.build_endpoint_preload_plan("demo", "show", {"method": "GET"})

        self.assertEqual(endpoint.default_include, ("owner",))
        self.assertEqual(endpoint.default_sort, "-created_at")
        self.assertTrue(endpoint.paginate)
        self.assertEqual(plan.select_related, ("owner",))
        self.assertEqual(plan.prefetch_related, ("comments",))

    def test_forum_resource_bootstrap_registers_show_endpoint_for_default_includes(self):
        from bias_core.forum_resources import bootstrap_forum_resource_fields

        registry = ResourceRegistry()
        bootstrap_forum_resource_fields(registry)

        endpoint = registry.get_dispatch_endpoint("forum", "show", "GET")

        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint.resource, "forum")
        self.assertEqual(endpoint.endpoint, "show")

    def test_forum_settings_serialization_uses_forum_show_default_includes(self):
        from dataclasses import replace

        from bias_core.forum_resources import bootstrap_forum_resource_fields
        from bias_core.resources.definitions import ResourceEndpointDefinition
        from bias_core.services.settings import _serialize_forum_resource_fields

        registry = ResourceRegistry()
        bootstrap_forum_resource_fields(registry)
        registry.register_relationship(ResourceRelationshipDefinition(
            resource="forum",
            relationship="owner",
            module_id="test",
            resolver=lambda instance, context: SimpleNamespace(name="neo"),
            resource_type="forum_owner",
        ))
        registry.register_resource(ResourceDefinition(
            resource="forum_owner",
            module_id="test",
            resolver=lambda instance, context: {"name": instance.name},
        ))
        registry.register_endpoint(ResourceEndpointDefinition(
            resource="forum",
            endpoint="show",
            module_id="test",
            operation="mutate",
            mutator=lambda endpoint: replace(endpoint, default_include=("owner",)),
        ))

        with patch("bias_core.resource_registry.get_resource_registry", return_value=registry):
            payload = _serialize_forum_resource_fields({}, user=None)

        self.assertEqual(payload["owner"], {"name": "neo"})

    def test_resource_registry_ignores_non_filesystem_installation_state_overrides(self):
        registry = ResourceRegistry()

        registry.register_field(ResourceFieldDefinition(
            resource="discussion",
            field="core_runtime_field",
            module_id="core",
            resolver=lambda instance, context: True,
        ))
        ExtensionInstallation.objects.create(
            extension_id="core",
            version="1.0.0",
            source="core-module",
            enabled=False,
            installed=True,
            booted=False,
        )

        fields = registry.get_fields("discussion")

        self.assertTrue(any(item.field == "core_runtime_field" for item in fields))

    def test_resource_extender_resolves_endpoint_pipeline_callbacks(self):
        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        class BeforeHook:
            def __call__(self, context):
                context["seen_before"] = True

        class ResponseCallback:
            def __call__(self, context, response):
                return {
                    "response": response,
                    "seen_before": context.get("seen_before"),
                }

        class PlainResponseCallback:
            def __call__(self, context, response):
                return {
                    "plain": response,
                    "seen_before": context.get("seen_before"),
                }

        endpoint = ResourceEndpointDefinition(
            resource="demo",
            endpoint="custom",
            module_id="",
            handler=lambda context: {"ok": True},
            before_hook=BeforeHook,
            response_callback=ResponseCallback,
            plain_response_callback=PlainResponseCallback,
        )

        ResourceExtender(endpoints=(endpoint,)).extend(app, extension)
        resources = app.make("resources")
        definition = resources.get_dispatch_endpoint("demo", "custom", "GET")

        self.assertEqual(definition.module_id, "alpha-tools")
        self.assertIsNot(definition.before_hook, BeforeHook)
        self.assertIsNot(definition.response_callback, ResponseCallback)
        context = {}
        definition.before_hook(context)
        self.assertEqual(definition.response_callback(context, {"ok": True}), {
            "response": {"ok": True},
            "seen_before": True,
        })
        self.assertIsNot(definition.plain_response_callback, PlainResponseCallback)
        self.assertEqual(definition.plain_response_callback(context, {"ok": True}), {
            "plain": {"ok": True},
            "seen_before": True,
        })

    def test_api_resource_extender_supports_string_resource_endpoint_helpers(self):
        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="alpha-tools")

        ApiResourceExtender("post").add_default_include(("index", "show"), ("flags",)).extend(app, extension)
        resources = app.make("resources")
        endpoint = ResourceEndpointDefinition(
            resource="post",
            endpoint="index",
            module_id="core",
            kind="index",
        )

        mutated = resources.apply_endpoint_mutators("post", "index", endpoint)

        self.assertEqual(mutated.default_include, ("flags",))

    def test_resource_endpoint_runner_applies_hooks_to_custom_handlers(self):
        from bias_core.resource_endpoint_runner import ResourceEndpointRunner

        registry = ResourceRegistry()
        events = []

        definition = ResourceEndpointDefinition(
            resource="demo",
            endpoint="custom",
            module_id="alpha-tools",
            handler=lambda context: {
                "data": {"ok": context["prepared"]},
                "queried": context["queried"],
                "included": context["include"],
                "sort": context["sort"],
                "filters": context["filters"],
            },
            default_include=("owner",),
            default_sort="-created_at",
            query_callback=lambda context: context.with_value("queried", True),
            action_callback=lambda context: {**context["result"], "action": True},
            before_serialization_callback=lambda context, result: {**result, "serialized": True},
            before_hook=lambda context: (events.append("before"), context.update({"prepared": True})),
            after_hook=lambda context, result: {**result, "meta": {"after": True}},
            response_callback=lambda context, response: {**response, "links": {"self": "/demo/custom"}},
        )

        response = ResourceEndpointRunner(registry).run(definition, {
            "query": {
                "filter[state]": "open",
            },
        })

        self.assertEqual(events, ["before"])
        self.assertEqual(response["data"], {"ok": True})
        self.assertTrue(response["queried"])
        self.assertTrue(response["action"])
        self.assertTrue(response["serialized"])
        self.assertEqual(response["included"], ("owner",))
        self.assertEqual(response["sort"], "-created_at")
        self.assertEqual(response["filters"], {"state": "open"})
        self.assertEqual(response["meta"], {"after": True})
        self.assertEqual(response["links"], {"self": "/demo/custom"})

    def test_resource_endpoint_eager_loads_when_included_and_where_callbacks(self):
        registry = ResourceRegistry()

        def visible_comments(queryset, context):
            return queryset

        class DemoResource(Resource):
            def type(self):
                return "eager_demo"

            def endpoints(self):
                return [
                    ResourceEndpoint.index()
                    .add_default_include(["owner"])
                    .eager_load_when_included("owner", "owner__profile")
                    .eager_load_where("comments", visible_comments)
                ]

        registry.register_resource(DemoResource())

        plan = registry.build_endpoint_preload_plan("eager_demo", "index", {"method": "GET"})

        self.assertIn("owner__profile", plan.prefetch_related)
        self.assertIn("comments", plan.prefetch_related)
        self.assertEqual(plan.prefetch_where, (("comments", visible_comments),))

    def test_resource_endpoint_select_related_contributes_to_preload_plan(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "endpoint_select_demo"

            def endpoints(self):
                return [
                    ResourceEndpoint.show().select_related_with("owner"),
                ]

        registry.register_resource(DemoResource())

        plan = registry.build_endpoint_preload_plan("endpoint_select_demo", "show", {"method": "GET"})

        self.assertEqual(plan.select_related, ("owner",))

    def test_relationship_scope_contributes_prefetch_where_for_included_relationship(self):
        registry = ResourceRegistry()

        def only_visible(queryset, context):
            return queryset

        class DemoResource(Resource):
            def type(self):
                return "relationship_scope_demo"

            def relationships(self):
                return [
                    ResourceRelationship(
                        "children",
                        resolver=lambda instance, context: [],
                        resource_type="relationship_scope_demo",
                    )
                    .to_many("relationship_scope_demo")
                    .scope(only_visible)
                    .prefetch_to("visible_children")
                ]

        registry.register_resource(DemoResource())

        plan = registry.build_preload_plan("relationship_scope_demo", include=("children",))

        self.assertEqual(plan.prefetch_related, ("children",))
        self.assertEqual(plan.prefetch_where, (("children", only_visible, "visible_children"),))

    def test_resource_endpoint_builder_sets_methods_and_absolute_path(self):
        endpoint = (
            ResourceEndpoint.update("rename")
            .with_methods("patch", ("post", ""))
            .at("/items/{object_id}/rename", absolute=True)
            .select_related_with("owner")
            .for_module("demo")
        )

        self.assertEqual(endpoint.endpoint, "rename")
        self.assertEqual(endpoint.methods, ("PATCH", "POST"))
        self.assertEqual(endpoint.path, "/items/{object_id}/rename")
        self.assertTrue(endpoint.absolute_path)
        self.assertEqual(endpoint.select_related, ("owner",))
        self.assertEqual(endpoint.module_id, "demo")

    def test_endpoint_where_eager_load_builds_prefetch_before_serialization(self):
        from bias_core.resource_endpoint_runner import DatabaseResourceEndpoint
        from django.db.models import Prefetch

        registry = ResourceRegistry()
        seen = {}

        class RelationManager:
            def all(self):
                return ["base-queryset"]

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id
                self.comments = RelationManager()

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        def only_visible(queryset, context):
            seen["queryset"] = queryset
            return queryset

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "where_eager_items"

            def endpoints(self):
                return [ResourceEndpoint.index().eager_load_where("comments", only_visible)]

        resource = ItemResource()
        definition = ResourceEndpointDefinition(
            resource="where_eager_items",
            endpoint="index",
            module_id="test",
            kind="index",
            methods=("GET",),
            eager_load_where_rules=(("comments", only_visible),),
        )
        endpoint = DatabaseResourceEndpoint(registry, resource, definition)

        with patch("django.db.models.prefetch_related_objects") as prefetch:
            endpoint.before_serialize_includes(ResourceContext({"resource": "where_eager_items"}), [Item()])

        prefetch_arg = prefetch.call_args.args[1]
        self.assertIsInstance(prefetch_arg, Prefetch)
        self.assertEqual(seen["queryset"], ["base-queryset"])

    def test_database_resource_lifecycle_hooks_wrap_save_and_delete_actions(self):
        events = []

        class Instance:
            def save(self):
                events.append("save")

            def delete(self):
                events.append("delete")

        class DemoDatabaseResource(DatabaseResource):
            def type(self):
                return "demo"

            def creating(self, instance, context):
                events.append("creating")
                return instance

            def saving(self, instance, context):
                events.append("saving")
                return instance

            def saved(self, instance, context):
                events.append("saved")
                return instance

            def created(self, instance, context):
                events.append("created")
                return instance

            def updating(self, instance, context):
                events.append("updating")
                return instance

            def updated(self, instance, context):
                events.append("updated")
                return instance

            def deleting(self, instance, context):
                events.append("deleting")

            def deleted(self, instance, context):
                events.append("deleted")

        resource = DemoDatabaseResource()

        resource.create_action(Instance(), {})
        resource.update_action(Instance(), {})
        resource.delete_action(Instance(), {})

        self.assertEqual(
            events,
            [
                "creating",
                "saving",
                "save",
                "saved",
                "created",
                "updating",
                "saving",
                "save",
                "saved",
                "updated",
                "deleting",
                "delete",
                "deleted",
            ],
        )

    def test_database_resource_crud_endpoints_dispatch_without_custom_handlers(self):
        registry = ResourceRegistry()
        events = []

        class Item:
            objects = None

            def __init__(self, id=None, title=""):
                self.id = id
                self.title = title
                self.deleted = False

            def save(self):
                events.append(("save", self.title))

            def delete(self):
                self.deleted = True
                events.append(("delete", self.id))

        class QuerySet(list):
            def filter(self, **kwargs):
                if "pk" in kwargs:
                    return QuerySet([item for item in self if str(item.id) == str(kwargs["pk"])])
                return self

            def first(self):
                return self[0] if self else None

            def order_by(self, *fields):
                events.append(("order_by", fields))
                return self

            def select_related(self, *fields):
                events.append(("select_related", fields))
                return self

            def prefetch_related(self, *fields):
                events.append(("prefetch_related", fields))
                return self

            def __getitem__(self, item):
                result = super().__getitem__(item)
                if isinstance(item, slice):
                    return QuerySet(result)
                return result

        class Manager:
            def __init__(self, items):
                self.items = items

            def all(self):
                return QuerySet(self.items)

        items = [Item(1, "first"), Item(2, "second"), Item(3, "third-page")]
        Item.objects = Manager(items)

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "item"

            def base(self, instance, context):
                return {"id": instance.id}

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: instance.title,
                        writable=True,
                        required_on_create=True,
                    ),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: {"id": "owner"},
                        resource_type="users",
                        select_related=("owner",),
                    ),
                ]

            def endpoints(self):
                return [
                    ResourceEndpoint.index().add_default_include(["owner"]).with_default_sort("recent").with_pagination(default_limit=1, max_limit=2),
                    ResourceEndpoint.show(),
                    ResourceEndpoint.create().add_default_include(["owner"]),
                    ResourceEndpoint.update(),
                    ResourceEndpoint.delete(),
                ]

            def sorts(self):
                return [ResourceSort("recent", handler=("-id",))]

            def new_model(self, context):
                item = Item(4)
                items.append(item)
                return item

            def created(self, instance, context):
                events.append(("created", instance.title))
                return instance

            def updated(self, instance, context):
                events.append(("updated", instance.title))
                return instance

        registry.register_resource(ItemResource())

        index_payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("item", "index", "GET"),
            {"resource": "item", "endpoint": "index", "method": "GET", "query": {"page[offset]": "1", "page[limit]": "2"}},
        )
        show_payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("item", "show", "GET"),
            {"resource": "item", "endpoint": "show", "method": "GET", "object_id": "1", "query": {}},
        )
        create_status, create_payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("item", "create", "POST"),
            {"resource": "item", "endpoint": "create", "method": "POST", "payload": {"data": {"type": "item", "attributes": {"title": "third"}}}, "query": {}},
        )
        update_payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("item", "update", "PATCH"),
            {"resource": "item", "endpoint": "update", "method": "PATCH", "object_id": "1", "payload": {"data": {"type": "item", "id": "1", "attributes": {"title": "updated"}}}, "query": {}},
        )
        delete_status, delete_payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("item", "delete", "DELETE"),
            {"resource": "item", "endpoint": "delete", "method": "DELETE", "object_id": "2", "query": {}},
        )

        self.assertEqual(
            index_payload["data"][0],
            {
                "type": "item",
                "id": "2",
                "links": {"self": "/api/item/2"},
                "attributes": {"title": "second"},
                "relationships": {"owner": {"data": {"type": "users", "id": "owner"}}},
            },
        )
        self.assertNotIn("included", index_payload)
        self.assertEqual(index_payload["data"][1]["id"], "3")
        self.assertEqual(index_payload["meta"], {"total": 3, "count": 2, "limit": 2, "offset": 1})
        self.assertEqual(
            show_payload,
            {
                "data": {
                    "type": "item",
                    "id": "1",
                    "links": {"self": "/api/item/1"},
                    "attributes": {"title": "first"},
                    "relationships": {"owner": {"data": {"type": "users", "id": "owner"}}},
                }
            },
        )
        self.assertEqual(create_status, 201)
        self.assertEqual(
            create_payload,
            {
                "data": {
                    "type": "item",
                    "id": "4",
                    "links": {"self": "/api/item/4"},
                    "attributes": {"title": "third"},
                    "relationships": {"owner": {"data": {"type": "users", "id": "owner"}}},
                },
            },
        )
        self.assertEqual(
            update_payload,
            {
                "data": {
                    "type": "item",
                    "id": "1",
                    "links": {"self": "/api/item/1"},
                    "attributes": {"title": "updated"},
                    "relationships": {"owner": {"data": {"type": "users", "id": "owner"}}},
                }
            },
        )
        self.assertEqual(delete_status, 204)
        self.assertIsNone(delete_payload)
        self.assertTrue(items[1].deleted)
        self.assertIn(("created", "third"), events)
        self.assertIn(("updated", "updated"), events)

    def test_database_resource_crud_parses_jsonapi_attributes_and_relationships(self):
        registry = ResourceRegistry()
        relationship_updates = []

        class Item:
            objects = None

            def __init__(self, id=None, title=""):
                self.id = id
                self.title = title
                self.owner = None

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item(1, "first")])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "jsonapi_item"

            def base(self, instance, context):
                return {"id": instance.id}

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title, writable=True),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        writable=True,
                    ).set_relationship_with(
                        lambda instance, value, context: (
                            relationship_updates.append(value),
                            setattr(instance, "owner", value),
                        )
                    ),
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("jsonapi_item", "update", "PATCH"),
            {
                "resource": "jsonapi_item",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {
                    "data": {
                        "type": "jsonapi_item",
                        "id": "1",
                        "attributes": {"title": "updated"},
                        "relationships": {"owner": {"data": {"type": "users", "id": "7"}}},
                    }
                },
                "query": {"include": "owner"},
            },
        )

        self.assertEqual(payload["data"]["attributes"]["title"], "updated")
        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "users", "id": "7"})
        self.assertEqual(relationship_updates, [{"type": "users", "id": "7"}])

    def test_database_resource_crud_validates_field_schema_before_writing(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=None, title="", score=0):
                self.id = id
                self.title = title
                self.score = score

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item(1, "first", 1)])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "validated_item"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title, writable=True)
                    .string()
                    .required_on_create_field()
                    .min_length(3)
                    .max_length(20),
                    ResourceField("score", resolver=lambda instance, context: instance.score, writable=True)
                    .integer()
                    .min(0)
                    .max(10),
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("validated_item", "update", "PATCH")

        with self.assertRaises(ValueError):
            registry.dispatch_resource_endpoint(
                endpoint,
                {
                    "resource": "validated_item",
                    "endpoint": "update",
                    "method": "PATCH",
                    "object_id": "1",
                    "payload": {"data": {"type": "validated_item", "id": "1", "attributes": {"title": "ok", "score": 3}}},
                    "query": {},
                },
            )
        with self.assertRaises(ValueError):
            registry.dispatch_resource_endpoint(
                endpoint,
                {
                    "resource": "validated_item",
                    "endpoint": "update",
                    "method": "PATCH",
                    "object_id": "1",
                    "payload": {"data": {"type": "validated_item", "id": "1", "attributes": {"title": "valid", "score": "high"}}},
                    "query": {},
                },
            )

        payload = registry.dispatch_resource_endpoint(
            endpoint,
            {
                "resource": "validated_item",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {"data": {"type": "validated_item", "id": "1", "attributes": {"title": "valid", "score": 7}}},
                "query": {},
            },
        )

        self.assertEqual(payload["data"]["attributes"], {"title": "valid", "score": 7})

    def test_database_resource_crud_validates_relationship_schema(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=None):
                self.id = id
                self.owner = None

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item(1)])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "validated_relationship_item"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        writable=True,
                        resource_type="users",
                    )
                    .object()
                    .required_on_update_field()
                    .set_relationship_with(lambda instance, value, context: setattr(instance, "owner", value))
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("validated_relationship_item", "update", "PATCH")

        with self.assertRaises(ValueError):
            registry.dispatch_resource_endpoint(
                endpoint,
                {
                    "resource": "validated_relationship_item",
                    "endpoint": "update",
                    "method": "PATCH",
                    "object_id": "1",
                    "payload": {"data": {"type": "validated_relationship_item", "id": "1", "relationships": {}}},
                    "query": {},
                },
            )
        with self.assertRaises(ValueError):
            registry.dispatch_resource_endpoint(
                endpoint,
                {
                    "resource": "validated_relationship_item",
                    "endpoint": "update",
                    "method": "PATCH",
                    "object_id": "1",
                    "payload": {"data": {"type": "validated_relationship_item", "id": "1", "relationships": {"owner": {"data": "bad"}}}},
                    "query": {},
                },
            )

        payload = registry.dispatch_resource_endpoint(
            endpoint,
            {
                "resource": "validated_relationship_item",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {"data": {"type": "validated_relationship_item", "id": "1", "relationships": {"owner": {"data": {"type": "users", "id": "7"}}}}},
                "query": {},
            },
        )

        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "users", "id": "7"})

    def test_database_resource_crud_checks_object_level_ability(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "ability_item"

            def endpoints(self):
                return [ResourceEndpoint.show().can("view")]

            def can(self, user, ability, instance, context):
                return bool(user and getattr(user, "can_view", False))

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("ability_item", "show", "GET")

        with self.assertRaises(PermissionError):
            registry.dispatch_resource_endpoint(
                endpoint,
                {"resource": "ability_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(can_view=False), "query": {}},
            )

        payload = registry.dispatch_resource_endpoint(
            endpoint,
            {"resource": "ability_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(can_view=True), "query": {}},
        )
        self.assertEqual(payload, {"data": {"type": "ability_item", "id": "1", "links": {"self": "/api/ability_item/1"}}})

    def test_resource_endpoint_can_keeps_dotted_ability_as_resource_policy(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "dotted_ability_item"

            def endpoints(self):
                return [ResourceEndpoint.show().can("secure.view")]

            def can(self, user, ability, instance, context):
                return ability == "secure.view" and getattr(user, "allowed", False)

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("dotted_ability_item", "show", "GET")

        with self.assertRaises(PermissionError):
            registry.dispatch_resource_endpoint(
                endpoint,
                {"resource": "dotted_ability_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(allowed=False), "query": {}},
            )

        payload = registry.dispatch_resource_endpoint(
            endpoint,
            {"resource": "dotted_ability_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(allowed=True), "query": {}},
        )
        self.assertEqual(payload, {"data": {"type": "dotted_ability_item", "id": "1", "links": {"self": "/api/dotted_ability_item/1"}}})

    def test_resource_endpoint_can_uses_global_and_model_policies_before_resource_can(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "policy_item"

            def endpoints(self):
                return [ResourceEndpoint.show().can("view")]

            def can(self, user, ability, instance, context):
                return False

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("policy_item", "show", "GET")
        app = ExtensionApplication(resource_registry=registry)
        app.policies.global_policy("alpha", lambda **context: True if context["ability"] == "view" else None)

        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            payload = registry.dispatch_resource_endpoint(
                endpoint,
                {"resource": "policy_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(is_authenticated=True), "query": {}},
            )

        self.assertEqual(payload, {"data": {"type": "policy_item", "id": "1", "links": {"self": "/api/policy_item/1"}}})

        app = ExtensionApplication(resource_registry=registry)
        app.policies.model_policy("alpha", Item, lambda **context: False if context["ability"] == "view" else None)
        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            with self.assertRaises(PermissionError):
                registry.dispatch_resource_endpoint(
                    endpoint,
                    {"resource": "policy_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(is_authenticated=True), "query": {}},
                )

    def test_resource_endpoint_policy_deny_can_be_refined_by_resource_can_override(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "policy_refined_item"

            def endpoints(self):
                return [ResourceEndpoint.show().can("view")]

            def can(self, user, ability, instance, context):
                raise PermissionDenied("custom resource deny")

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("policy_refined_item", "show", "GET")
        app = ExtensionApplication(resource_registry=registry)
        app.policies.model_policy("alpha", Item, lambda **context: False if context["ability"] == "view" else None)

        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            with self.assertRaisesMessage(PermissionDenied, "custom resource deny"):
                registry.dispatch_resource_endpoint(
                    endpoint,
                    {"resource": "policy_refined_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(is_authenticated=True), "query": {}},
                )

    def test_resource_endpoint_policy_deny_is_not_bypassed_by_default_resource_can(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "policy_default_item"

            def endpoints(self):
                return [ResourceEndpoint.show().can("view")]

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("policy_default_item", "show", "GET")
        app = ExtensionApplication(resource_registry=registry)
        app.policies.model_policy("alpha", Item, lambda **context: False if context["ability"] == "view" else None)

        with patch("bias_core.extensions.policy_runtime_service.get_extension_application", return_value=app):
            with self.assertRaises(PermissionError):
                registry.dispatch_resource_endpoint(
                    endpoint,
                    {"resource": "policy_default_item", "endpoint": "show", "method": "GET", "object_id": "1", "user": SimpleNamespace(is_authenticated=True), "query": {}},
                )

    def test_resource_endpoint_hooks_meta_and_links_are_applied_to_default_crud(self):
        registry = ResourceRegistry()
        events = []

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "hooked_item"

            def endpoints(self):
                return [
                    ResourceEndpoint.show()
                    .before(lambda context: events.append(("before", context["endpoint"])))
                    .after(lambda context, item: events.append(("after", getattr(item, "id", None))) or item)
                    .meta(lambda context, item: {"hooked": True})
                    .links(lambda context, item: {"related": "/api/hooked_item/related"})
                ]

        registry.register_resource(ItemResource())
        payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("hooked_item", "show", "GET"),
            {"resource": "hooked_item", "endpoint": "show", "method": "GET", "object_id": "1", "query": {}},
        )

        self.assertEqual(events, [("before", "show"), ("after", 1)])
        self.assertEqual(payload["meta"], {"hooked": True})
        self.assertEqual(payload["links"], {"related": "/api/hooked_item/related"})

    def test_jsonapi_document_serializes_relationship_linkage_and_included_resources(self):
        registry = ResourceRegistry()

        class UserModel:
            def __init__(self, id, username):
                self.id = id
                self.username = username

        class DiscussionModel:
            def __init__(self, id, title, owner):
                self.id = id
                self.title = title
                self.owner = owner

        class UserResource(Resource):
            def type(self):
                return "users"

            def fields(self):
                return [
                    ResourceField("username", resolver=lambda instance, context: instance.username),
                ]

        class DiscussionResource(Resource):
            def type(self):
                return "discussions"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="users",
                    ),
                ]

        owner = UserModel(7, "neo")
        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())

        payload = registry.serialize_jsonapi_document(
            "discussions",
            [DiscussionModel(1, "first", owner), DiscussionModel(2, "second", owner)],
            include=("owner",),
            many=True,
        )

        self.assertEqual(
            payload["data"][0],
            {
                "type": "discussions",
                "id": "1",
                "links": {"self": "/api/discussions/1"},
                "attributes": {"title": "first"},
                "relationships": {"owner": {"data": {"type": "users", "id": "7"}}},
            },
        )
        self.assertEqual(payload["included"], [{"type": "users", "id": "7", "links": {"self": "/api/users/7"}, "attributes": {"username": "neo"}}])

    def test_jsonapi_document_adds_self_links_and_resolves_related_resource_from_model(self):
        registry = ResourceRegistry()

        class UserModel:
            def __init__(self, id, username):
                self.id = id
                self.username = username

        class DiscussionModel:
            def __init__(self, id, owner):
                self.id = id
                self.owner = owner

        class UserResource(DatabaseResource):
            model = UserModel

            def type(self):
                return "linked_users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class DiscussionResource(Resource):
            def type(self):
                return "linked_discussions"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                    ),
                ]

        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())

        payload = registry.serialize_jsonapi_document(
            "linked_discussions",
            DiscussionModel(4, UserModel(7, "neo")),
            {"api_base_path": "/api"},
            include=("owner",),
        )

        self.assertEqual(payload["data"]["links"]["self"], "/api/linked_discussions/4")
        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "linked_users", "id": "7"})
        self.assertEqual(payload["included"][0]["links"]["self"], "/api/linked_users/7")

    def test_jsonapi_document_uses_resource_wire_type_for_output_links_and_linkage(self):
        registry = ResourceRegistry()

        class UserModel:
            def __init__(self, id, username):
                self.id = id
                self.username = username

        class DiscussionModel:
            def __init__(self, id, owner):
                self.id = id
                self.owner = owner

        class UserResource(DatabaseResource):
            model = UserModel

            def type(self):
                return "wire_user"

            def jsonapi_types(self):
                return ("wire_user", "wire-users")

            def jsonapi_type(self):
                return "wire-users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class DiscussionResource(Resource):
            def type(self):
                return "wire_discussion"

            def jsonapi_type(self):
                return "wire-discussions"

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="wire_user",
                    ),
                ]

        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())

        payload = registry.serialize_jsonapi_document(
            "wire_discussion",
            DiscussionModel(4, UserModel(7, "neo")),
            {"api_base_path": "/api"},
            include=("owner",),
        )

        self.assertEqual(payload["data"]["type"], "wire-discussions")
        self.assertEqual(payload["data"]["links"]["self"], "/api/wire-discussions/4")
        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "wire-users", "id": "7"})
        self.assertEqual(payload["included"][0]["type"], "wire-users")
        self.assertEqual(payload["included"][0]["links"]["self"], "/api/wire-users/7")

    def test_nested_include_contributes_nested_preload_plan(self):
        registry = ResourceRegistry()

        class OwnerResource(Resource):
            def type(self):
                return "nested_owner"

            def fields(self):
                return [
                    ResourceRelationship(
                        "profile",
                        resolver=lambda instance, context: getattr(instance, "profile", None),
                        resource_type="nested_profile",
                        select_related=("profile",),
                    )
                ]

        class DiscussionResource(Resource):
            def type(self):
                return "nested_discussion"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: getattr(instance, "owner", None),
                        resource_type="nested_owner",
                        select_related=("owner",),
                    )
                ]

        registry.register_resource(OwnerResource())
        registry.register_resource(DiscussionResource())

        plan = registry.build_preload_plan("nested_discussion", include=("owner.profile",))
        self.assertIn("owner", plan.select_related)
        self.assertIn("owner__profile", plan.select_related)

    def test_included_resource_default_fields_contribute_preload_plan(self):
        registry = ResourceRegistry()

        class OwnerResource(Resource):
            def type(self):
                return "nested_default_owner"

            def fields(self):
                return [
                    ResourceField(
                        "score",
                        resolver=lambda instance, context: getattr(instance, "score", 0),
                        select_related=("score_account",),
                        prefetch_related=("badges",),
                    )
                ]

        class DiscussionResource(Resource):
            def type(self):
                return "nested_default_discussion"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: getattr(instance, "owner", None),
                        resource_type="nested_default_owner",
                        select_related=("owner",),
                    )
                ]

        registry.register_resource(OwnerResource())
        registry.register_resource(DiscussionResource())

        plan = registry.build_preload_plan("nested_default_discussion", include=("owner",))
        self.assertIn("owner", plan.select_related)
        self.assertIn("owner__score_account", plan.select_related)
        self.assertIn("owner__badges", plan.prefetch_related)

    def test_nested_default_prefetch_uses_relationship_path_not_auxiliary_prefetch_path(self):
        registry = ResourceRegistry()

        class UserResource(Resource):
            def type(self):
                return "nested_group_user"

            def fields(self):
                return [
                    ResourceField(
                        "primary_group",
                        resolver=lambda instance, context: None,
                        prefetch_related=("user_groups",),
                    )
                ]

        class PostResource(Resource):
            def type(self):
                return "nested_group_post"

            def fields(self):
                return [
                    ResourceRelationship(
                        "user",
                        resolver=lambda instance, context: getattr(instance, "user", None),
                        resource_type="nested_group_user",
                        select_related=("user",),
                        prefetch_related=("user__user_groups",),
                    )
                ]

        registry.register_resource(UserResource())
        registry.register_resource(PostResource())

        plan = registry.build_preload_plan("nested_group_post", include=("user",))

        self.assertIn("user__user_groups", plan.prefetch_related)
        self.assertNotIn("user__user_groups__user_groups", plan.prefetch_related)

    def test_nested_default_select_ignores_auxiliary_prefetch_paths_when_select_path_exists(self):
        registry = ResourceRegistry()

        class UserResource(Resource):
            def type(self):
                return "nested_account_user"

            def fields(self):
                return [
                    ResourceField(
                        "points",
                        resolver=lambda instance, context: 0,
                        select_related=("point_account",),
                    )
                ]

        class PostResource(Resource):
            def type(self):
                return "nested_account_post"

            def fields(self):
                return [
                    ResourceRelationship(
                        "user",
                        resolver=lambda instance, context: getattr(instance, "user", None),
                        resource_type="nested_account_user",
                        select_related=("user",),
                        prefetch_related=("user__user_groups",),
                    )
                ]

        registry.register_resource(UserResource())
        registry.register_resource(PostResource())

        plan = registry.build_preload_plan("nested_account_post", include=("user",))

        self.assertIn("user__point_account", plan.select_related)
        self.assertIn("user__user_groups", plan.prefetch_related)
        self.assertNotIn("user__user_groups__point_account", plan.prefetch_related)

    def test_nested_select_under_prefetch_relationship_stays_in_prefetch_plan(self):
        registry = ResourceRegistry()

        class TagResource(Resource):
            def type(self):
                return "nested_prefetch_tag"

            def fields(self):
                return [
                    ResourceField(
                        "last_posted_discussion",
                        resolver=lambda instance, context: None,
                        select_related=("last_posted_discussion",),
                    )
                ]

        class DiscussionResource(Resource):
            def type(self):
                return "nested_prefetch_discussion"

            def fields(self):
                return [
                    ResourceRelationship(
                        "tags",
                        resolver=lambda instance, context: (),
                        resource_type="nested_prefetch_tag",
                        many=True,
                        prefetch_related=("discussion_tags__tag",),
                    )
                ]

        registry.register_resource(TagResource())
        registry.register_resource(DiscussionResource())

        plan = registry.build_preload_plan("nested_prefetch_discussion", include=("tags",))

        self.assertNotIn("discussion_tags__tag__last_posted_discussion", plan.select_related)
        self.assertIn("discussion_tags__tag__last_posted_discussion", plan.prefetch_related)

    def test_plain_serializer_applies_nested_relationship_includes(self):
        registry = ResourceRegistry()

        class ProfileModel:
            def __init__(self, id, bio):
                self.id = id
                self.bio = bio

        class OwnerModel:
            def __init__(self, id, username, profile):
                self.id = id
                self.username = username
                self.profile = profile

        class DiscussionModel:
            def __init__(self, id, owner):
                self.id = id
                self.owner = owner

        class ProfileResource(Resource):
            def type(self):
                return "plain_profiles"

            def fields(self):
                return [ResourceField("bio", resolver=lambda instance, context: instance.bio)]

        class OwnerResource(Resource):
            def type(self):
                return "plain_owners"

            def fields(self):
                return [
                    ResourceField("username", resolver=lambda instance, context: instance.username),
                    ResourceRelationship(
                        "profile",
                        resolver=lambda instance, context: instance.profile,
                        resource_type="plain_profiles",
                    ),
                ]

        class DiscussionResource(Resource):
            def type(self):
                return "plain_discussions"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="plain_owners",
                    )
                ]

        registry.register_resource(ProfileResource())
        registry.register_resource(OwnerResource())
        registry.register_resource(DiscussionResource())

        payload = registry.serialize(
            "plain_discussions",
            DiscussionModel(1, OwnerModel(2, "ada", ProfileModel(3, "engineer"))),
            include=("owner.profile",),
        )

        self.assertEqual(payload["owner"]["username"], "ada")
        self.assertEqual(payload["owner"]["profile"]["bio"], "engineer")

    def test_custom_relationship_preload_resolver_owns_nested_preload_plan(self):
        registry = ResourceRegistry()

        class OwnerResource(Resource):
            def type(self):
                return "custom_preload_owner"

            def fields(self):
                return [
                    ResourceRelationship(
                        "profile",
                        resolver=lambda instance, context: getattr(instance, "profile", None),
                        resource_type="custom_preload_profile",
                        select_related=("profile",),
                    )
                ]

        class DiscussionResource(Resource):
            def type(self):
                return "custom_preload_discussion"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: getattr(instance, "owner", None),
                        resource_type="custom_preload_owner",
                        preload_resolver=lambda context: (("virtual_owner",), ()),
                    )
                ]

        registry.register_resource(OwnerResource())
        registry.register_resource(DiscussionResource())

        plan = registry.build_preload_plan("custom_preload_discussion", include=("owner.profile",))

        self.assertIn("virtual_owner", plan.select_related)
        self.assertNotIn("owner__profile", plan.select_related)

    def test_virtual_relationship_without_orm_path_does_not_autogenerate_nested_select_related(self):
        registry = ResourceRegistry()

        class TagResource(Resource):
            def type(self):
                return "virtual_nested_tag"

            def fields(self):
                return [
                    ResourceRelationship(
                        "last_discussion",
                        resolver=lambda instance, context: getattr(instance, "last_discussion", None),
                        resource_type="virtual_nested_discussion",
                        select_related=("last_discussion",),
                    )
                ]

        class PostResource(Resource):
            def type(self):
                return "virtual_nested_post"

            def fields(self):
                return [
                    ResourceRelationship(
                        "mentioned_tags",
                        resolver=lambda instance, context: (),
                        resource_type="virtual_nested_tag",
                        many=True,
                    )
                ]

        registry.register_resource(TagResource())
        registry.register_resource(PostResource())

        plan = registry.build_preload_plan("virtual_nested_post", include=("mentioned_tags.last_discussion",))

        self.assertEqual(plan.select_related, ())
        self.assertNotIn("mentioned_tags__last_discussion", plan.select_related)

    def test_jsonapi_serializer_resolves_deferred_field_and_relationship_values(self):
        registry = ResourceRegistry()

        class UserModel:
            def __init__(self, id, username):
                self.id = id
                self.username = username

        class DiscussionModel:
            def __init__(self, id, owner):
                self.id = id
                self.owner = owner

        class UserResource(Resource):
            def type(self):
                return "deferred_users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: lambda: instance.username)]

        class DiscussionResource(Resource):
            def type(self):
                return "deferred_discussions"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: lambda: "deferred title"),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: lambda: instance.owner,
                        resource_type="deferred_users",
                    ),
                ]

        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())

        payload = registry.serialize_jsonapi_document(
            "deferred_discussions",
            DiscussionModel(1, UserModel(7, "neo")),
            include=("owner",),
        )

        self.assertEqual(payload["data"]["attributes"]["title"], "deferred title")
        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "deferred_users", "id": "7"})
        self.assertEqual(payload["included"][0]["attributes"]["username"], "neo")

    def test_resource_modifiers_apply_parent_before_child_like_upstream_extendable(self):
        registry = ResourceRegistry()

        class BaseResource(Resource):
            def fields(self):
                return [ResourceField("base", resolver=lambda instance, context: "base")]

        class ChildResource(BaseResource):
            def type(self):
                return "extendable_child"

            def fields(self):
                return [*super().fields(), ResourceField("child", resolver=lambda instance, context: "child")]

        registry.register_resource_modifier(
            BaseResource,
            "fields",
            lambda fields, resource: [*fields, ResourceField("from_base_modifier", resolver=lambda instance, context: "base-mod")],
        )
        registry.register_resource_modifier(
            ChildResource,
            "fields",
            lambda fields, resource: [*fields, ResourceField("from_child_modifier", resolver=lambda instance, context: "child-mod")],
        )
        registry.register_resource(ChildResource())

        fields = [field.field for field in registry.get_effective_fields("extendable_child")]
        self.assertEqual(fields, ["base", "child", "from_base_modifier", "from_child_modifier"])

    def test_resource_modifiers_are_deduped_and_can_be_reset(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "modifier_reset_demo"

            def fields(self):
                return [ResourceField("base", resolver=lambda instance, context: "base")]

        def add_field(fields, resource):
            return [*fields, ResourceField("extra", resolver=lambda instance, context: "extra")]

        registry.register_resource_modifier(DemoResource, "fields", add_field)
        registry.register_resource_modifier(DemoResource, "fields", add_field)
        registry.register_resource(DemoResource())

        self.assertEqual(
            [field.field for field in registry.get_effective_fields("modifier_reset_demo")],
            ["base", "extra"],
        )

        registry.reset_resource_modifiers(DemoResource, "fields")

        self.assertEqual(
            [field.field for field in registry.get_effective_fields("modifier_reset_demo")],
            ["base"],
        )

    def test_resource_class_level_modifiers_resolve_like_upstream_extendable(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "class_modifier_demo"

            def fields(self):
                return [ResourceField("base", resolver=lambda instance, context: "base")]

        def add_extra(fields, resource):
            return [*fields, ResourceField("extra", resolver=lambda instance, context: "extra")]

        DemoResource.mutate_fields(add_extra)
        registry.register_resource(DemoResource())

        try:
            self.assertEqual(
                [field.field for field in registry.get_effective_fields("class_modifier_demo")],
                ["base", "extra"],
            )
        finally:
            DemoResource.reset_modifiers("fields")

    def test_resource_object_relationships_method_is_resolved(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "relationship_method_demo"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: "title")]

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: getattr(instance, "owner", None),
                        resource_type="users",
                    )
                ]

        registry.register_resource(DemoResource())

        self.assertEqual(
            [field.field for field in registry.get_effective_fields("relationship_method_demo")],
            ["title"],
        )
        self.assertEqual(
            [relationship.relationship for relationship in registry.get_effective_relationships("relationship_method_demo")],
            ["owner"],
        )

    def test_resource_relationship_modifiers_are_deduped_and_can_be_reset(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "relationship_modifier_reset_demo"

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: getattr(instance, "owner", None),
                        resource_type="users",
                    )
                ]

        def add_relationship(relationships, resource):
            return [
                *relationships,
                ResourceRelationship(
                    "last_editor",
                    resolver=lambda instance, context: getattr(instance, "last_editor", None),
                    resource_type="users",
                ),
            ]

        registry.register_resource_modifier(DemoResource, "relationships", add_relationship)
        registry.register_resource_modifier(DemoResource, "relationships", add_relationship)
        registry.register_resource(DemoResource())

        self.assertEqual(
            [relationship.relationship for relationship in registry.get_effective_relationships("relationship_modifier_reset_demo")],
            ["owner", "last_editor"],
        )

        registry.reset_resource_modifiers(DemoResource, "relationships")

        self.assertEqual(
            [relationship.relationship for relationship in registry.get_effective_relationships("relationship_modifier_reset_demo")],
            ["owner"],
        )

    def test_resource_class_level_relationship_modifiers_resolve(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "class_relationship_modifier_demo"

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: getattr(instance, "owner", None),
                        resource_type="users",
                    )
                ]

        def add_extra(relationships, resource):
            return [
                *relationships,
                ResourceRelationship(
                    "last_editor",
                    resolver=lambda instance, context: getattr(instance, "last_editor", None),
                    resource_type="users",
                ),
            ]

        DemoResource.mutate_relationships(add_extra)
        registry.register_resource(DemoResource())

        try:
            self.assertEqual(
                [relationship.relationship for relationship in registry.get_effective_relationships("class_relationship_modifier_demo")],
                ["owner", "last_editor"],
            )
        finally:
            DemoResource.reset_modifiers("relationships")

    def test_resource_extender_resolves_import_path_callbacks_like_upstream_container(self):
        registry = ResourceRegistry()
        app = ExtensionApplication(resource_registry=registry)
        extension = SimpleNamespace(extension_id="path-ext")

        extender = ResourceExtender(
            fields=(
                ExtensionResourceFieldDefinition(
                    resource="path_resource",
                    field="username",
                    module_id="",
                    resolver="tests.common.resolve_test_username",
                ),
            )
        )
        extender.extend(app, extension)
        app.make("resources")

        user = SimpleNamespace(username="neo")
        self.assertEqual(registry.serialize("path_resource", user), {"username": user.username})

    def test_api_resource_extender_accepts_bias_style_callable_groups(self):
        registry = ResourceRegistry()
        app = ExtensionApplication(resource_registry=registry)
        extension = SimpleNamespace(extension_id="bias-api")

        class ItemResource(Resource):
            def type(self):
                return "bias_api_items"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title),
                    ResourceRelationship("owner", resolver=lambda instance, context: instance.owner),
                    ResourceRelationship("legacy_owner", resolver=lambda instance, context: instance.owner),
                ]

            def endpoints(self):
                return [ResourceEndpoint.show()]

            def filters(self):
                return [ResourceFilter("state", handler=lambda queryset, value, context: queryset)]

            def sorts(self):
                return [ResourceSort("created", handler="created_at")]

        extender = (
            ApiResourceExtender.from_resource(ItemResource)
            .fields(lambda: [ResourceField("slug", resolver=lambda instance, context: instance.slug)])
            .relationship(
                "owner",
                lambda relationship: ResourceRelationshipDefinition(
                    resource=relationship.resource,
                    relationship=relationship.relationship,
                    module_id=relationship.module_id,
                    resolver=relationship.resolver,
                    description="mutated owner",
                ),
            )
            .relationships_after(
                "owner",
                ResourceRelationshipDefinition(
                    resource="bias_api_items",
                    relationship="last_editor",
                    module_id="bias-api",
                    resolver=lambda instance, context: None,
                ),
            )
            .remove_relationships("legacy_owner")
            .endpoints(lambda: [ResourceEndpoint.index()])
            .filters_before_all(
                ResourceFilterDefinition(
                    resource="bias_api_items",
                    filter="first",
                    module_id="bias-api",
                    handler=lambda queryset, value, context: queryset,
                ),
            )
            .filters_after(
                "state",
                ResourceFilterDefinition(
                    resource="bias_api_items",
                    filter="after_state",
                    module_id="bias-api",
                    handler=lambda queryset, value, context: queryset,
                ),
            )
            .sorts(lambda: [ResourceSort("hot", handler="score")])
        )
        extender.extend(app, extension)
        app.make("resources")

        self.assertEqual(
            [field.field for field in registry.get_effective_fields("bias_api_items")],
            ["title", "slug"],
        )
        self.assertEqual(
            [endpoint.endpoint for endpoint in registry.get_dispatch_endpoints("bias_api_items")],
            ["show", "index"],
        )
        self.assertEqual(
            [(relationship.relationship, relationship.description) for relationship in registry.get_effective_relationships("bias_api_items")],
            [("owner", "mutated owner"), ("last_editor", "")],
        )
        self.assertEqual(
            [item.filter for item in registry.get_effective_filters("bias_api_items")],
            ["first", "state", "after_state"],
        )
        self.assertEqual(
            [sort.sort for sort in registry.get_effective_sorts("bias_api_items")],
            ["created", "hot"],
        )

    def test_api_resource_extender_aliases_apply_fluent_mutations(self):
        registry = ResourceRegistry()
        app = ExtensionApplication(resource_registry=registry)
        extension = SimpleNamespace(extension_id="bias-api")

        registry.register_field(ResourceFieldDefinition(
            resource="alias_items",
            field="title",
            module_id="core",
            resolver=lambda instance, context: "title",
        ))
        registry.register_relationship(ResourceRelationshipDefinition(
            resource="alias_items",
            relationship="owner",
            module_id="core",
            resolver=lambda instance, context: "owner",
        ))
        registry.register_endpoint(ResourceEndpointDefinition(
            resource="alias_items",
            endpoint="show",
            module_id="core",
            handler=lambda context: {"show": True},
            operation="add",
        ))
        registry.register_sort(ResourceSortDefinition(
            resource="alias_items",
            sort="created",
            module_id="core",
            handler="created_at",
            operation="add",
        ))
        registry.register_filter(ResourceFilterDefinition(
            resource="alias_items",
            filter="state",
            module_id="core",
            handler=lambda queryset, value, context: queryset,
            operation="add",
        ))

        (
            ApiResourceExtender("alias_items")
            .fields_before_all(ResourceFieldDefinition(
                resource="alias_items",
                field="first_field",
                module_id="",
                resolver=lambda instance, context: "first",
            ))
            .mutate_field("title", lambda field: ResourceFieldDefinition(
                resource=field.resource,
                field=field.field,
                module_id=field.module_id,
                resolver=field.resolver,
                description="mutated title",
            ))
            .relationships_before_all(ResourceRelationshipDefinition(
                resource="alias_items",
                relationship="first_relation",
                module_id="",
                resolver=lambda instance, context: None,
            ))
            .mutate_relationship("owner", lambda relationship: ResourceRelationshipDefinition(
                resource=relationship.resource,
                relationship=relationship.relationship,
                module_id=relationship.module_id,
                resolver=relationship.resolver,
                description="mutated owner",
            ))
            .endpoint_before_all(ResourceEndpointDefinition(
                resource="alias_items",
                endpoint="first_endpoint",
                module_id="",
                handler=lambda context: {"first": True},
                operation="add",
            ))
            .mutate_endpoint("show", lambda endpoint: ResourceEndpointDefinition(
                resource=endpoint.resource,
                endpoint=endpoint.endpoint,
                module_id=endpoint.module_id,
                handler=lambda context: {"show": "mutated"},
            ))
            .sort_before_all(ResourceSortDefinition(
                resource="alias_items",
                sort="first_sort",
                module_id="",
                handler=("first_at",),
            ))
            .mutate_sort("created", lambda sort: ResourceSortDefinition(
                resource=sort.resource,
                sort=sort.sort,
                module_id=sort.module_id,
                handler=("-created_at",),
            ))
            .filter_before_all(ResourceFilterDefinition(
                resource="alias_items",
                filter="first_filter",
                module_id="",
                handler=lambda queryset, value, context: queryset,
            ))
            .mutate_filter("state", lambda item: ResourceFilterDefinition(
                resource=item.resource,
                filter=item.filter,
                module_id=item.module_id,
                handler=item.handler,
                description="mutated state",
            ))
            .extend(app, extension)
        )
        app.make("resources")

        self.assertEqual(
            [(item.field, item.description) for item in registry.get_effective_fields("alias_items")],
            [("first_field", ""), ("title", "mutated title")],
        )
        self.assertEqual(
            [(item.relationship, item.description) for item in registry.get_effective_relationships("alias_items")],
            [("first_relation", ""), ("owner", "mutated owner")],
        )
        self.assertEqual(
            [item.endpoint for item in registry.get_dispatch_endpoints("alias_items")],
            ["first_endpoint", "show"],
        )
        self.assertEqual(
            registry.get_dispatch_endpoint("alias_items", "show", "GET").handler({}),
            {"show": "mutated"},
        )
        self.assertEqual(
            [item.sort for item in registry.get_effective_sorts("alias_items")],
            ["first_sort", "created"],
        )
        self.assertEqual(
            [item.handler for item in registry.get_effective_sorts("alias_items")],
            [("first_at",), ("-created_at",)],
        )
        self.assertEqual(
            [(item.filter, item.description) for item in registry.get_effective_filters("alias_items")],
            [("first_filter", ""), ("state", "mutated state")],
        )

    def test_container_resolver_injects_services_by_constructor_name(self):
        from bias_core.extensions.container import resolve_container_value

        class NeedsResources:
            def __init__(self, resources):
                self.resources = resources

        app = ExtensionApplication()
        resolved = resolve_container_value(NeedsResources, app)

        self.assertIs(resolved.resources, app.resources)

    def test_container_resolver_recursively_injects_typed_dependencies(self):
        from bias_core.extensions.container import resolve_container_value

        class Dependency:
            pass

        class Service:
            def __init__(self, dependency: Dependency):
                self.dependency = dependency

        resolved = resolve_container_value(Service, ExtensionApplication())

        self.assertIsInstance(resolved.dependency, Dependency)

    def test_extension_container_resolves_bound_class_and_reuses_singletons(self):
        from bias_core.extensions.container import resolve_container_value

        class Dependency:
            pass

        class Replacement:
            pass

        class Service:
            def __init__(self, dependency: Dependency):
                self.dependency = dependency

        app = ExtensionApplication()
        app.instance(Dependency, Replacement())
        app.singleton(Service, Service)

        first = app.make(Service)
        second = app.make(Service)
        resolved = resolve_container_value(Service, app)

        self.assertIs(first, second)
        self.assertIs(resolved, first)
        self.assertIsInstance(first.dependency, Replacement)

    def test_wrap_callback_resolves_class_string_lazily_like_upstream_container(self):
        from bias_core.extensions.container import wrap_callback

        calls = []

        class Invokable:
            def __init__(self):
                calls.append("constructed")

            def __call__(self):
                calls.append("called")
                return "ok"

        app = ExtensionApplication()
        callback = wrap_callback(Invokable, app)

        self.assertEqual(calls, [])
        self.assertEqual(callback(), "ok")
        self.assertEqual(calls, ["constructed", "called"])

    def test_wrap_callback_does_not_hide_argument_type_errors(self):
        from bias_core.extensions.container import wrap_callback

        def callback(required):
            return required

        wrapped = wrap_callback(callback, ExtensionApplication())

        with self.assertRaises(TypeError):
            wrapped()

    def test_jsonapi_serializer_is_context_driven_and_keeps_included_deduped(self):
        registry = ResourceRegistry()

        class UserResource(Resource):
            def type(self):
                return "serializer_users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class DiscussionResource(Resource):
            def type(self):
                return "serializer_discussions"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="serializer_users",
                    ),
                ]

        owner = SimpleNamespace(id=7, username="neo")
        discussions = [
            SimpleNamespace(id=1, title="first", owner=owner),
            SimpleNamespace(id=2, title="second", owner=owner),
        ]
        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())

        payload = registry.serialize_jsonapi_document(
            "serializer_discussions",
            discussions,
            include=("owner",),
            many=True,
        )

        self.assertEqual(len(payload["included"]), 1)
        self.assertEqual(payload["included"][0]["type"], "serializer_users")

    def test_resource_serializer_exposes_bias_style_primary_and_included_api(self):
        registry = ResourceRegistry()

        class ItemResource(Resource):
            def type(self):
                return "serializer_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

        registry.register_resource(ItemResource())
        serializer = ResourceSerializer(registry)
        item = SimpleNamespace(id=1, title="hello")

        serializer.add_primary("serializer_items", item)
        primary, included = serializer.serialize()

        self.assertEqual(primary[0]["type"], "serializer_items")
        self.assertEqual(primary[0]["attributes"]["title"], "hello")
        self.assertEqual(included, [])

    def test_resource_serializer_add_included_returns_identifier(self):
        registry = ResourceRegistry()

        class ItemResource(Resource):
            def type(self):
                return "serializer_include_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

        registry.register_resource(ItemResource())
        serializer = ResourceSerializer(registry)
        item = SimpleNamespace(id=9, title="included")

        identifier = serializer.add_included("serializer_include_items", item)
        primary, included = serializer.serialize()

        self.assertEqual(identifier, {"type": "serializer_include_items", "id": "9"})
        self.assertEqual(primary, [])
        self.assertEqual(included[0]["attributes"]["title"], "included")

    def test_resource_serializer_owns_relationship_linkage_and_included_resolution(self):
        registry = ResourceRegistry()

        class UserResource(Resource):
            def type(self):
                return "owned_serializer_users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class DiscussionResource(Resource):
            def type(self):
                return "owned_serializer_discussions"

            def fields(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="owned_serializer_users",
                    )
                ]

        owner = SimpleNamespace(id=7, username="neo")
        discussion = SimpleNamespace(id=1, owner=owner)
        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())

        serializer = ResourceSerializer(registry)
        serializer.add_primary("owned_serializer_discussions", discussion, include_tree={"owner": {}})
        primary, included = serializer.serialize()

        self.assertEqual(primary[0]["relationships"]["owner"]["data"], {"type": "owned_serializer_users", "id": "7"})
        self.assertEqual(included[0]["attributes"]["username"], "neo")

    def test_jsonapi_relationship_can_emit_foreign_key_linkage_without_resolving_relation(self):
        registry = ResourceRegistry()
        calls = []

        class UserResource(Resource):
            def type(self):
                return "fk_linkage_users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class DiscussionResource(Resource):
            def type(self):
                return "fk_linkage_discussions"

            def relationships(self):
                def resolve_owner(instance, context):
                    calls.append("owner")
                    return SimpleNamespace(id=instance.owner_id, username="neo")

                return [
                    ResourceRelationship("owner", resolver=resolve_owner, resource_type="fk_linkage_users")
                    .to_one("fk_linkage_users")
                    .with_foreign_key_linkage("owner_id")
                ]

        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())
        discussion = SimpleNamespace(id=1, owner_id=7)

        payload = registry.serialize_jsonapi_document("fk_linkage_discussions", discussion)

        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "fk_linkage_users", "id": "7"})
        self.assertEqual(calls, [])

        included_payload = registry.serialize_jsonapi_document("fk_linkage_discussions", discussion, include=("owner",))

        self.assertEqual(calls, ["owner"])
        self.assertEqual(included_payload["included"][0]["attributes"]["username"], "neo")

    def test_plain_serializer_can_emit_relationship_linkage(self):
        registry = ResourceRegistry()

        class UserResource(Resource):
            def type(self):
                return "plain_linkage_users"

        class DiscussionResource(Resource):
            def type(self):
                return "plain_linkage_discussions"

        owner = SimpleNamespace(id=7)
        discussion = SimpleNamespace(id=1, owner=owner)
        registry.register_resource(UserResource())
        registry.register_resource(DiscussionResource())
        registry.register_relationship(ResourceRelationshipDefinition(
            resource="plain_linkage_discussions",
            relationship="owner",
            module_id="test",
            resolver=lambda instance, context: instance.owner,
            resource_type="plain_linkage_users",
            plain_output="linkage",
        ))

        payload = registry.serialize("plain_linkage_discussions", discussion, include=("owner",))

        self.assertEqual(payload["owner"], {"type": "plain_linkage_users", "id": "7"})

    def test_resource_serializer_uses_schema_object_visibility_and_value_methods(self):
        registry = ResourceRegistry()
        calls = []

        class CustomField(ResourceField):
            def get_value(self, context):
                calls.append(("value", context.model.title))
                return context.model.title.upper()

            def is_visible_for(self, context):
                calls.append(("visible", context.model.title))
                return True

        class ItemResource(Resource):
            def type(self):
                return "schema_serializer_items"

            def fields(self):
                return [CustomField("title", resolver=lambda instance, context: "unused")]

        registry.register_resource(ItemResource())
        payload = registry.serialize_jsonapi_document("schema_serializer_items", SimpleNamespace(id=1, title="hello"))

        self.assertEqual(payload["data"]["attributes"]["title"], "HELLO")
        self.assertEqual(calls, [("visible", "hello"), ("value", "hello")])

    def test_resource_context_sparse_fields_drives_jsonapi_serializer(self):
        registry = ResourceRegistry()

        class ItemResource(Resource):
            def type(self):
                return "sparse_context_items"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title),
                    ResourceField("body", resolver=lambda instance, context: instance.body),
                ]

        registry.register_resource(ItemResource())
        payload = registry.serialize_jsonapi_document(
            "sparse_context_items",
            SimpleNamespace(id=1, title="hello", body="hidden"),
            context={"query": {"fields": {"sparse_context_items": "title"}}},
        )

        self.assertEqual(payload["data"]["attributes"], {"title": "hello"})

    def test_resource_context_exposes_typed_body_and_collection_helpers(self):
        context = ResourceContext({
            "payload": {"data": {"type": "items", "attributes": {"title": "hello"}, "relationships": {"owner": {"data": None}}}},
            "query": {"fields": {"items": "title"}},
            "resource": "items",
        })

        self.assertEqual(context.data()["type"], "items")
        self.assertEqual(context.attributes(), {"title": "hello"})
        self.assertEqual(context.relationship_data(), {"owner": {"data": None}})
        self.assertEqual(context.collection_resources(), ("items",))


    def test_endpoint_runner_pipeline_stores_query_and_result_context(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id, title):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

        class Manager:
            def all(self):
                return QuerySet([Item(1, "first")])

        Item.objects = Manager()
        seen = {}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "pipeline_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def endpoints(self):
                return [
                    ResourceEndpoint.index()
                    .after(lambda context, results: seen.update({
                        "has_queryset": context.queryset is not None,
                        "result_count": len(results),
                    }) or results)
                ]

        registry.register_resource(ItemResource())
        payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("pipeline_items", "index", "GET"),
            {"resource": "pipeline_items", "endpoint": "index", "method": "GET"},
        )

        self.assertEqual(payload["data"][0]["attributes"]["title"], "first")
        self.assertEqual(seen, {"has_queryset": True, "result_count": 1})

    def test_resource_endpoint_pipeline_callbacks_can_override_response(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="first"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        order = []

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "pipeline_callback_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def endpoints(self):
                return [
                    ResourceEndpoint.show()
                    .query(lambda context: order.append("query") or context)
                    .before_serialization(lambda context, result: order.append("before_serialization") or result)
                    .response(lambda context, response: order.append("response") or {"data": {"type": "override"}})
                ]

        registry.register_resource(ItemResource())
        payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("pipeline_callback_items", "show", "GET"),
            {"resource": "pipeline_callback_items", "endpoint": "show", "method": "GET", "object_id": "1"},
        )

        self.assertEqual(order, ["query", "before_serialization", "response"])
        self.assertEqual(payload, {"data": {"type": "override"}})

    def test_database_resource_endpoint_pipeline_is_reusable_like_endpoint_concern(self):
        from bias_core.resource_endpoint_runner import DatabaseResourceEndpoint

        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="first"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "concern_pipeline_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

        resource = ItemResource()
        registry.register_resource(resource)
        definition = ResourceEndpointDefinition(
            resource="concern_pipeline_items",
            endpoint="index",
            module_id="test",
            kind="index",
            methods=("GET",),
        )

        pipeline = DatabaseResourceEndpoint(registry, resource, definition).index_pipeline()
        context = pipeline.query(ResourceContext({"resource": "concern_pipeline_items", "query": {}}))
        results = pipeline.action(context)
        response = pipeline.response(context.with_result(results), results)

        self.assertEqual(response["data"][0]["attributes"]["title"], "first")

    def test_database_resource_endpoint_prepares_include_plan_before_serialization(self):
        from bias_core.resource_endpoint_runner import DatabaseResourceEndpoint

        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="first", owner=None):
                self.id = id
                self.title = title
                self.owner = owner

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def select_related(self, *fields):
                self.select_related_fields = fields
                return self

            def prefetch_related(self, *fields):
                self.prefetch_related_fields = fields
                return self

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class UserResource(Resource):
            def type(self):
                return "concern_plan_users"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: "neo")]

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "concern_plan_items"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title),
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="concern_plan_users",
                        select_related=("owner",),
                    ),
                ]

        registry.register_resource(UserResource())
        resource = ItemResource()
        registry.register_resource(resource)
        definition = ResourceEndpointDefinition(
            resource="concern_plan_items",
            endpoint="index",
            module_id="test",
            kind="index",
            methods=("GET",),
            default_include=("owner",),
        )

        pipeline = DatabaseResourceEndpoint(registry, resource, definition).index_pipeline()
        context = pipeline.query(ResourceContext({"resource": "concern_plan_items", "query": {}}))
        results = pipeline.action(context)
        serialization_context = context.with_result(results)
        pipeline.before_serialization(serialization_context, results)

        self.assertEqual(serialization_context["preload_plan"].select_related, ("owner",))

    def test_database_resource_endpoint_applies_endpoint_select_related_during_query(self):
        from bias_core.resource_endpoint_runner import DatabaseResourceEndpoint

        registry = ResourceRegistry()
        seen = {}

        class Item:
            objects = None

        class QuerySet(list):
            def select_related(self, *fields):
                seen["select_related"] = fields
                return self

            def prefetch_related(self, *fields):
                return self

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "endpoint_select_query_items"

        resource = ItemResource()
        registry.register_resource(resource)
        definition = ResourceEndpointDefinition(
            resource="endpoint_select_query_items",
            endpoint="index",
            module_id="test",
            kind="index",
            methods=("GET",),
            select_related=("owner",),
        )

        pipeline = DatabaseResourceEndpoint(registry, resource, definition).index_pipeline()
        pipeline.query(ResourceContext({"resource": "endpoint_select_query_items", "method": "GET", "query": {}}))

        self.assertEqual(seen["select_related"], ("owner",))

    def test_database_resource_endpoint_listing_params_are_extracted_by_concern(self):
        from bias_core.resource_endpoint_runner import DatabaseResourceEndpoint

        registry = ResourceRegistry()

        class ItemResource(DatabaseResource):
            model = object

            def type(self):
                return "listing_param_items"

        definition = ResourceEndpointDefinition(
            resource="listing_param_items",
            endpoint="index",
            module_id="test",
            kind="index",
            paginate=True,
            default_include=("owner",),
        )
        endpoint = DatabaseResourceEndpoint(registry, ItemResource(), definition)
        params = endpoint.listing_params(ResourceContext({
            "query": {
                "page[limit]": "5",
                "page[offset]": "10",
                "filter[state]": "open",
                "sort": "-created",
            }
        }))

        self.assertEqual(params["pagination"], {"limit": 5, "offset": 10})
        self.assertEqual(params["include"], ("owner",))
        self.assertEqual(params["filters"], {"state": "open"})
        self.assertEqual(params["sort"], "-created")

    def test_database_resource_endpoint_search_concern_can_customize_listing_query(self):
        from bias_core.resource_endpoint_runner import DatabaseResourceEndpoint

        registry = ResourceRegistry()

        class Item:
            def __init__(self, id=1, title="first"):
                self.id = id
                self.title = title

        class QuerySet(list):
            pass

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "custom_listing_items"

            def query(self, context):
                return QuerySet([Item(1, "first"), Item(2, "second")])

            def scope(self, query, context):
                return query

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

        class CustomEndpoint(DatabaseResourceEndpoint):
            def apply_listing_query(self, queryset, context, params):
                return QuerySet([queryset[1]]), None, 1

        resource = ItemResource()
        definition = ResourceEndpointDefinition(
            resource="custom_listing_items",
            endpoint="index",
            module_id="test",
            kind="index",
            methods=("GET",),
            paginate=True,
        )
        endpoint = CustomEndpoint(registry, resource, definition)
        pipeline = endpoint.index_pipeline()
        context = pipeline.query(ResourceContext({"resource": "custom_listing_items", "query": {}}))
        results = pipeline.action(context)

        self.assertEqual([item.title for item in results], ["second"])
        self.assertEqual(context.get("total"), 1)

    def test_resource_payload_uses_schema_object_deserialize_validate_and_setter(self):
        registry = ResourceRegistry()
        calls = []

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class CustomField(ResourceField):
            def deserialize(self, value, context):
                calls.append(("deserialize", value))
                return value.strip()

            def validate(self, value, context):
                calls.append(("validate", value))
                if not value:
                    raise ValueError("title required")

            def set_value(self, instance, value, context):
                calls.append(("set", value))
                instance.title = value.upper()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "schema_payload_items"

            def fields(self):
                return [CustomField("title", resolver=lambda instance, context: instance.title).writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        response = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("schema_payload_items", "update", "PATCH"),
            {
                "resource": "schema_payload_items",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {"data": {"type": "schema_payload_items", "id": "1", "attributes": {"title": " new "}}},
                "query": {},
            },
        )

        self.assertEqual(response["data"]["attributes"]["title"], "NEW")
        self.assertEqual(calls[-1], ("set", "new"))
        self.assertIn(("deserialize", " new "), calls)
        self.assertIn(("validate", "new"), calls)

    def test_resource_validation_collects_schema_object_rules_messages_and_attributes(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title
                self.owner = None

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class TitleField(ResourceField):
            def get_validation_rules(self, context):
                return {"title": ("required_without:relationships.owner",)}

            def get_validation_messages(self, context):
                return {"title.required_without": "Need either title or owner"}

            def get_validation_attributes(self, context):
                return {"title": "Title"}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "schema_rule_items"

            def fields(self):
                return [
                    TitleField("title", resolver=lambda instance, context: instance.title)
                    .string()
                    .writable_when()
                    .with_validation_rules()
                ]

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="users",
                        writable=True,
                    )
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/schema_rule_items/1",
            data=json.dumps({"data": {"type": "schema_rule_items", "attributes": {"title": ""}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="schema_rule_items", endpoint="update", object_id="1")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["errors"][0]["detail"], "Need either title or owner")
        self.assertEqual(payload["errors"][0]["source"]["pointer"], "/data/attributes/title")

    def test_resource_validation_skips_unmarked_schema_rules_like_upstream_trait_gate(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        seen = {}

        class UnmarkedField(ResourceField):
            def get_validation_rules(self, context):
                return {"title": ("required",)}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "unmarked_rule_items"

            def fields(self):
                return [UnmarkedField("title", resolver=lambda instance, context: instance.title).writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                def validate(data, context, validation):
                    seen["rules"] = validation["rules"]
                    return None
                return validate

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/unmarked_rule_items/1",
            data=json.dumps({"data": {"type": "unmarked_rule_items", "attributes": {"title": ""}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="unmarked_rule_items", endpoint="update", object_id="1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["rules"]["attributes"], {})

    def test_resource_validation_rules_support_conditions_like_upstream(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old", summary="old"):
                self.id = id
                self.title = title
                self.summary = summary

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        seen = {}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "conditional_rule_items"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title)
                    .string()
                    .required(lambda context, model=None: bool(context.get("creating")))
                    .writable_when(),
                    ResourceField("summary", resolver=lambda instance, context: instance.summary)
                    .string()
                    .required_with(["title"])
                    .writable_when(),
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                def validate(data, context, validation):
                    seen["rules"] = validation["rules"]
                    return None
                return validate

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/conditional_rule_items/1",
            data=json.dumps({"data": {"type": "conditional_rule_items", "attributes": {"title": "new"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="conditional_rule_items", endpoint="update", object_id="1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["rules"]["attributes"], {"summary": ("required_with:title",)})

    def test_resource_endpoint_response_callback_receives_result_and_document_context(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="first"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        seen = {}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "pipeline_context_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def endpoints(self):
                return [
                    ResourceEndpoint.show().response(
                        lambda context, response: seen.update({
                            "result_title": context.result.title,
                            "document_type": context.document["data"]["type"],
                        }) or response
                    )
                ]

        registry.register_resource(ItemResource())
        registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("pipeline_context_items", "show", "GET"),
            {"resource": "pipeline_context_items", "endpoint": "show", "method": "GET", "object_id": "1"},
        )

        self.assertEqual(seen, {"result_title": "first", "document_type": "pipeline_context_items"})

    def test_validation_factory_receives_aggregated_rules_payload(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        seen = {}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "factory_payload_item"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title)
                    .string()
                    .min_length(2)
                    .writable_when()
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                def validate(data, context, validation):
                    seen["rules"] = validation["rules"]
                    return None
                return validate

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/factory_payload_item/1",
            data=json.dumps({"data": {"type": "factory_payload_item", "attributes": {"title": "ok"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="factory_payload_item", endpoint="update", object_id="1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["rules"]["attributes"]["title"], (("min_length", 2),))

    def test_validation_factory_collects_only_writable_schema_rules_like_upstream(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old", slug="old"):
                self.id = id
                self.title = title
                self.slug = slug

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        seen = {}

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "writable_rule_items"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title)
                    .string()
                    .rule("required")
                    .writable_when(),
                    ResourceField("slug", resolver=lambda instance, context: instance.slug)
                    .string()
                    .rule("required"),
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                def validate(data, context, validation):
                    seen["rules"] = validation["rules"]
                    return None
                return validate

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/writable_rule_items/1",
            data=json.dumps({"data": {"type": "writable_rule_items", "attributes": {"title": "new"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="writable_rule_items", endpoint="update", object_id="1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen["rules"]["attributes"], {"title": ("required",)})

    def test_validation_factory_can_return_validator_protocol(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        class Factory:
            def make(self, data, rules, messages, attributes):
                if data.get("title") == "bad":
                    return ResourceValidator([ResourceValidationError("title", "Validator rejected")])
                return ResourceValidator()

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "validator_protocol_item"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).string().writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                return Factory()

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/validator_protocol_item/1",
            data=json.dumps({"data": {"type": "validator_protocol_item", "attributes": {"title": "bad"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="validator_protocol_item", endpoint="update", object_id="1")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["errors"][0]["detail"], "Validator rejected")

    def test_validation_factory_preserves_relationship_error_section(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1):
                self.id = id
                self.owner = None

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "relationship_validation_items"

            def fields(self):
                return []

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                return ResourceValidatorFactory()

            def validation_attributes(self):
                return {"owner": "Owner"}

        registry.register_resource(ItemResource())
        registry.register_relationship(
            ResourceRelationshipDefinition(
                resource="relationship_validation_items",
                relationship="owner",
                module_id="test",
                resolver=lambda instance, context: instance.owner,
                writable=True,
                validation_rules=(("in", ("1",)),),
            )
        )
        request = RequestFactory().patch(
            "/api/resources/relationship_validation_items/1",
            data=json.dumps({
                "data": {
                    "type": "relationship_validation_items",
                    "relationships": {"owner": {"data": {"type": "users", "id": "2"}}},
                }
            }),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="relationship_validation_items", endpoint="update", object_id="1")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["errors"][0]["source"]["pointer"], "/data/relationships/owner")

    def test_default_validator_factory_interprets_field_rules(self):
        from bias_core.resource_validation import ResourceValidatorFactory

        validator = ResourceValidatorFactory().make(
            {"title": "x"},
            {"title": (("min_length", 3),)},
            attributes={"title": "Title"},
        )

        self.assertTrue(validator.fails())
        self.assertEqual(validator.messages()["title"], ["Title length must be at least 3"])

    def test_resource_field_hex_color_rule_matches_flarum_schema(self):
        field = ResourceField("color", resolver=lambda instance, context: instance.color).string().nullable_field().hex_color()

        self.assertIn("hex_color", [entry["rule"] for entry in field.validation_rules])
        field.validate("#abc", {})
        field.validate("#123abc", {})
        field.validate(None, {})
        with self.assertRaisesMessage(ValueError, "color must be a valid hex color"):
            field.validate("red", {})

    def test_default_validator_factory_interprets_hex_color_rule(self):
        from bias_core.resource_validation import ResourceValidatorFactory

        valid = ResourceValidatorFactory().make({"color": "#4d698e"}, {"color": ("hex_color",)})
        invalid = ResourceValidatorFactory().make({"color": "red"}, {"color": ("hex_color",)})

        self.assertFalse(valid.fails())
        self.assertTrue(invalid.fails())
        self.assertEqual(invalid.messages()["color"], ["color must be a valid hex color"])

    def test_can_select_only_specific_resource_fields(self):
        registry = ResourceRegistry()

        class Target:
            id = 2

        registry.register_field(
            ResourceFieldDefinition(
                resource="discussion",
                field="first",
                module_id="test",
                resolver=lambda instance, context: "a",
            )
        )
        registry.register_field(
            ResourceFieldDefinition(
                resource="discussion",
                field="second",
                module_id="test",
                resolver=lambda instance, context: "b",
            )
        )

        payload = registry.serialize("discussion", Target(), only=("second",))
        self.assertEqual(payload, {"second": "b"})

    def test_serialize_applies_registered_field_mutators_to_payload(self):
        registry = ResourceRegistry()

        class Target:
            title = "hello"

        registry.register_field(
            ResourceFieldDefinition(
                resource="discussion",
                field="title",
                module_id="core",
                resolver=lambda instance, context: instance.title,
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="title",
                module_id="extension",
                mutator=lambda value: value.upper(),
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="secret",
                module_id="extension",
                mutator=lambda value: value,
                operation="remove",
            )
        )

        payload = registry.serialize("discussion", Target())

        self.assertEqual(payload["title"], "HELLO")
        self.assertNotIn("secret", payload)

    def test_serialize_applies_bias_like_field_definition_mutators(self):
        registry = ResourceRegistry()

        class Target:
            title = "hello"

        title = ResourceFieldDefinition(
            resource="discussion",
            field="title",
            module_id="core",
            resolver=lambda instance, context: instance.title,
        )
        summary = ResourceFieldDefinition(
            resource="discussion",
            field="summary",
            module_id="extension",
            resolver=lambda instance, context: "summary",
        )
        mutated_title = ResourceFieldDefinition(
            resource="discussion",
            field="title",
            module_id="extension",
            resolver=lambda instance, context: instance.title.upper(),
        )
        registry.register_field(title)
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="summary",
                module_id="extension",
                operation="add",
                mutator=lambda field: summary,
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="title",
                module_id="extension",
                operation="mutate",
                mutator=lambda field: mutated_title,
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="removed",
                module_id="extension",
                operation="add",
                mutator=lambda field: ResourceFieldDefinition(
                    resource="discussion",
                    field="removed",
                    module_id="extension",
                    resolver=lambda instance, context: "removed",
                ),
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="removed",
                module_id="extension",
                operation="remove",
                mutator=lambda field: field,
            )
        )

        payload = registry.serialize("discussion", Target())

        self.assertEqual(payload, {"title": "HELLO", "summary": "summary"})

    def test_relationship_includes_follow_bias_like_field_removal(self):
        registry = ResourceRegistry()

        class Target:
            owner = type("Owner", (), {"username": "neo"})()

        registry.register_relationship(
            ResourceRelationshipDefinition(
                resource="discussion",
                relationship="owner",
                module_id="core",
                resolver=lambda instance, context: {"username": instance.owner.username},
                select_related=("owner",),
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="owner",
                module_id="extension",
                operation="remove",
                mutator=lambda field: field,
            )
        )

        payload = registry.serialize("discussion", Target(), include=("owner",))
        plan = registry.build_preload_plan("discussion", include=("owner",))

        self.assertNotIn("owner", payload)
        self.assertEqual(plan.select_related, ())

    def test_relationship_includes_follow_bias_like_field_mutation(self):
        registry = ResourceRegistry()

        class Target:
            owner = type("Owner", (), {"username": "neo"})()

        registry.register_relationship(
            ResourceRelationshipDefinition(
                resource="discussion",
                relationship="owner",
                module_id="core",
                resolver=lambda instance, context: {"username": instance.owner.username},
                select_related=("owner",),
            )
        )
        registry.register_field_mutator(
            ResourceFieldMutatorDefinition(
                resource="discussion",
                field="owner",
                module_id="extension",
                operation="mutate",
                mutator=lambda relationship: ResourceRelationshipDefinition(
                    resource=relationship.resource,
                    relationship=relationship.relationship,
                    module_id=relationship.module_id,
                    resolver=lambda instance, context: {"username": instance.owner.username.upper()},
                    select_related=("profile",),
                ),
            )
        )

        payload = registry.serialize("discussion", Target(), include=("owner",))
        plan = registry.build_preload_plan("discussion", include=("owner",))

        self.assertEqual(payload["owner"], {"username": "NEO"})
        self.assertEqual(plan.select_related, ("profile",))

    def test_apply_named_sort_runs_registered_sort_handler(self):
        registry = ResourceRegistry()
        queryset = Mock()
        sorted_queryset = Mock()
        handler = Mock(return_value=sorted_queryset)

        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="hot",
                module_id="extension",
                handler=handler,
            )
        )

        result = registry.apply_named_sort(
            "discussion",
            queryset,
            "hot",
            {"user": "alice"},
        )

        self.assertIs(result, sorted_queryset)
        handler.assert_called_once_with(queryset, {"user": "alice", "sort": "hot", "descending": False})

    def test_apply_named_sort_can_order_by_registered_field_list(self):
        registry = ResourceRegistry()
        queryset = Mock()
        ordered_queryset = Mock()
        queryset.order_by.return_value = ordered_queryset

        registry.register_sort(
            ResourceSortDefinition(
                resource="post",
                sort="recent",
                module_id="extension",
                handler=("-created_at", "id"),
            )
        )

        result = registry.apply_named_sort("post", queryset, "recent")

        self.assertIs(result, ordered_queryset)
        queryset.order_by.assert_called_once_with("-created_at", "id")
        self.assertTrue(registry.has_named_sort("post", "recent"))
        self.assertFalse(registry.has_named_sort("post", "missing"))

    def test_named_sort_uses_effective_sort_definitions(self):
        registry = ResourceRegistry()
        queryset = Mock()
        ordered_queryset = Mock()
        queryset.order_by.return_value = ordered_queryset

        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="hot",
                module_id="extension",
                handler=("hot",),
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="hot",
                module_id="extension",
                operation="mutate",
                mutator=lambda sort: ResourceSortDefinition(
                    resource=sort.resource,
                    sort=sort.sort,
                    module_id=sort.module_id,
                    handler=("-hot_score",),
                ),
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="old",
                module_id="extension",
                handler=("old",),
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="old",
                module_id="extension",
                operation="remove",
            )
        )

        result = registry.apply_named_sort("discussion", queryset, "hot")

        self.assertIs(result, ordered_queryset)
        queryset.order_by.assert_called_once_with("-hot_score")
        self.assertTrue(registry.has_named_sort("discussion", "hot"))
        self.assertFalse(registry.has_named_sort("discussion", "old"))

    def test_sort_definitions_match_objects_by_code(self):
        registry = ResourceRegistry()
        sort = DiscussionSortDefinition(
            code="oldest",
            label="最早",
            module_id="core",
            applier=lambda queryset, context: queryset,
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="oldest",
                module_id="extension",
                operation="remove",
            )
        )

        self.assertEqual(registry.apply_sort_definitions("discussion", [sort]), [])

    def test_sort_definitions_apply_before_after_and_before_all_ordering(self):
        registry = ResourceRegistry()
        base = ResourceSortDefinition(
            resource="discussion",
            sort="base",
            module_id="core",
            handler={"name": "base"},
        )
        first = ResourceSortDefinition(
            resource="discussion",
            sort="first",
            module_id="extension",
            handler={"name": "first"},
            operation="before_all",
        )
        before = ResourceSortDefinition(
            resource="discussion",
            sort="before",
            module_id="extension",
            handler={"name": "before"},
            operation="before",
            anchor="base",
        )
        after = ResourceSortDefinition(
            resource="discussion",
            sort="after",
            module_id="extension",
            handler={"name": "after"},
            operation="after",
            anchor="base",
        )

        registry.register_sort(base)
        registry.register_sort(after)
        registry.register_sort(first)
        registry.register_sort(before)

        self.assertEqual(
            [item.sort for item in registry.get_effective_sorts("discussion")],
            ["first", "before", "base", "after"],
        )
        self.assertEqual(
            registry.apply_sort_definitions("discussion", []),
            [{"name": "first"}, {"name": "before"}, {"name": "base"}, {"name": "after"}],
        )

    def test_sort_definitions_apply_to_external_sort_list_with_anchors(self):
        registry = ResourceRegistry()
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="first",
                module_id="extension",
                handler={"name": "first"},
                operation="before_all",
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="before",
                module_id="extension",
                handler={"name": "before"},
                operation="before",
                anchor="base",
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="after",
                module_id="extension",
                handler={"name": "after"},
                operation="after",
                anchor="base",
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="base",
                module_id="extension",
                operation="mutate",
                mutator=lambda sort: {"name": sort["name"], "mutated": True},
            )
        )
        registry.register_sort(
            ResourceSortDefinition(
                resource="discussion",
                sort="old",
                module_id="extension",
                operation="remove",
            )
        )

        self.assertEqual(
            registry.apply_sort_definitions("discussion", [{"name": "base"}, {"name": "old"}]),
            [{"name": "first"}, {"name": "before"}, {"name": "base", "mutated": True}, {"name": "after"}],
        )

    def test_get_dispatch_endpoint_matches_method_path_and_condition(self):
        registry = ResourceRegistry()
        handler = Mock(return_value={"ok": True})

        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="discussion",
                endpoint="feature",
                module_id="extension",
                handler=handler,
                methods=("POST",),
                condition=lambda context: context.get("enabled") is True,
            )
        )

        self.assertIsNone(registry.get_dispatch_endpoint("discussion", "feature", "GET", {"enabled": True}))
        self.assertIsNone(registry.get_dispatch_endpoint("discussion", "feature", "POST", {"enabled": False}))
        self.assertIs(
            registry.get_dispatch_endpoint("discussion", "/feature/", "POST", {"enabled": True}),
            registry.get_endpoints("discussion")[0],
        )

    def test_dispatch_endpoint_list_applies_remove_and_mutate_operations(self):
        registry = ResourceRegistry()

        original = ResourceEndpointDefinition(
            resource="discussion",
            endpoint="feature",
            module_id="extension",
            handler=lambda context: {"version": 1},
            methods=("GET",),
        )
        replacement = ResourceEndpointDefinition(
            resource="discussion",
            endpoint="feature",
            module_id="extension",
            operation="mutate",
            mutator=lambda endpoint: ResourceEndpointDefinition(
                resource=endpoint.resource,
                endpoint=endpoint.endpoint,
                module_id=endpoint.module_id,
                handler=lambda context: {"version": 2},
                methods=endpoint.methods,
            ),
        )
        removed = ResourceEndpointDefinition(
            resource="discussion",
            endpoint="feature",
            module_id="extension",
            operation="remove",
        )

        registry.register_endpoint(original)
        registry.register_endpoint(replacement)

        endpoint = registry.get_dispatch_endpoint("discussion", "feature", "GET")
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint.handler({}), {"version": 2})

        registry.register_endpoint(removed)
        self.assertIsNone(registry.get_dispatch_endpoint("discussion", "feature", "GET"))

    def test_apply_endpoint_definitions_applies_remove_without_mutator(self):
        registry = ResourceRegistry()
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="discussion",
                endpoint="store",
                module_id="extension",
                operation="remove",
            )
        )

        self.assertEqual(
            registry.apply_endpoint_definitions("discussion", [{"name": "index"}, {"name": "store"}]),
            [{"name": "index"}],
        )

    def test_dispatch_endpoint_list_applies_before_and_after_ordering(self):
        registry = ResourceRegistry()
        base = ResourceEndpointDefinition(
            resource="discussion",
            endpoint="base",
            module_id="core",
            handler=lambda context: {"name": "base"},
        )
        before = ResourceEndpointDefinition(
            resource="discussion",
            endpoint="before",
            module_id="extension",
            operation="before",
            anchor="base",
            handler=lambda context: {"name": "before"},
        )
        after = ResourceEndpointDefinition(
            resource="discussion",
            endpoint="after",
            module_id="extension",
            operation="after",
            anchor="base",
            handler=lambda context: {"name": "after"},
        )

        registry.register_endpoint(base)
        registry.register_endpoint(after)
        registry.register_endpoint(before)

        self.assertEqual(
            [item.endpoint for item in registry.get_dispatch_endpoints("discussion")],
            ["before", "base", "after"],
        )

    def test_dispatch_resource_endpoint_invokes_registered_handler(self):
        registry = ResourceRegistry()

        def handler(context):
            return {
                "resource": context["resource"],
                "endpoint": context["endpoint"],
                "object_id": context["object_id"],
                "payload": context["payload"],
                "query": context["query"],
            }

        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="discussion",
                endpoint="feature",
                module_id="extension",
                handler=handler,
                methods=("POST",),
            )
        )
        request = RequestFactory().post(
            "/api/resources/discussion/12/feature?include=user",
            data=json.dumps({"enabled": True}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(
                request,
                resource="discussion",
                object_id="12",
                endpoint="feature",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content),
            {
                "resource": "discussion",
                "endpoint": "feature",
                "object_id": "12",
                "payload": {"enabled": True},
                "query": {"include": "user"},
            },
        )

    def test_dispatch_resource_endpoint_uses_jsonapi_content_type_when_requested(self):
        registry = ResourceRegistry()
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="discussion",
                endpoint="feature",
                module_id="extension",
                handler=lambda context: (201, {"data": {"type": "discussions", "id": "1"}}),
                methods=("POST",),
            )
        )
        request = RequestFactory().post(
            "/api/resources/discussion/feature",
            data=json.dumps({"data": {"type": "discussions"}}),
            content_type="application/json",
            HTTP_ACCEPT="application/vnd.api+json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="discussion", endpoint="feature")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response["Content-Type"], "application/vnd.api+json")
        self.assertEqual(json.loads(response.content)["data"]["type"], "discussions")

    def test_dispatch_resource_endpoint_requires_auth_when_declared(self):
        registry = ResourceRegistry()
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="discussion",
                endpoint="secure",
                module_id="extension",
                handler=lambda context: {"ok": True},
                auth_required=True,
            )
        )
        request = RequestFactory().get("/api/resources/discussion/secure")

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="discussion", endpoint="secure")

        self.assertEqual(response.status_code, 401)

    def test_dispatch_resource_endpoint_checks_declared_permission(self):
        registry = ResourceRegistry()
        registry.register_resource(
            type(
                "SecureResource",
                (Resource,),
                {
                    "type": lambda self: "secure",
                    "endpoints": lambda self: [
                        ResourceEndpoint(
                            "show",
                            handler=lambda context: {"ok": True},
                        ).authenticated().requires_permission("secure.view")
                    ],
                },
            )()
        )
        request = RequestFactory().get("/api/resources/secure/show")
        user = Mock(is_authenticated=True)
        request.user = user

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            with patch("bias_core.resource_dispatcher.get_optional_user", return_value=user):
                with patch("bias_core.resource_dispatcher.has_forum_permission", return_value=False):
                    denied = dispatch_resource_endpoint(request, resource="secure", endpoint="show")
                with patch("bias_core.resource_dispatcher.has_forum_permission", return_value=True):
                    allowed = dispatch_resource_endpoint(request, resource="secure", endpoint="show")

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)

    def test_dispatch_resource_endpoint_runs_database_resource_crud_endpoint(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="hello"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "dispatch_item"

            def base(self, instance, context):
                return {"id": instance.id}

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def endpoints(self):
                return [ResourceEndpoint.show()]

        registry.register_resource(ItemResource())
        request = RequestFactory().get("/api/resources/dispatch_item/1/show")

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(
                request,
                resource="dispatch_item",
                object_id="1",
                endpoint="show",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content),
            {"data": {"type": "dispatch_item", "id": "1", "links": {"self": "/api/dispatch_item/1"}, "attributes": {"title": "hello"}}},
        )

    def test_dispatch_resource_endpoint_passes_page_limit_and_offset_to_index_endpoint(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id):
                self.id = id

        class QuerySet(list):
            def __getitem__(self, item):
                result = super().__getitem__(item)
                if isinstance(item, slice):
                    return QuerySet(result)
                return result

        class Manager:
            def all(self):
                return QuerySet([Item(1), Item(2), Item(3)])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "paged_dispatch_item"

            def endpoints(self):
                return [ResourceEndpoint.index().with_pagination(default_limit=1, max_limit=2)]

        registry.register_resource(ItemResource())
        request = RequestFactory().get("/api/resources/paged_dispatch_item/index", {"page[offset]": "1", "page[limit]": "2"})

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="paged_dispatch_item", endpoint="index")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            json.loads(response.content),
            {
                "data": [
                    {"type": "paged_dispatch_item", "id": "2", "links": {"self": "/api/paged_dispatch_item/2"}},
                    {"type": "paged_dispatch_item", "id": "3", "links": {"self": "/api/paged_dispatch_item/3"}},
                ],
                "meta": {"total": 3, "count": 2, "limit": 2, "offset": 1},
            },
        )

    def test_database_resource_index_applies_bias_like_filter_and_searcher_pipeline(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id, title, state):
                self.id = id
                self.title = title
                self.state = state

        class QuerySet(list):
            def filter(self, *args, **kwargs):
                if kwargs.get("state") is not None:
                    return QuerySet([item for item in self if item.state == kwargs["state"]])
                return self

            def order_by(self, *fields):
                field = fields[0]
                reverse = field.startswith("-")
                key = field.lstrip("-")
                return QuerySet(sorted(self, key=lambda item: getattr(item, key), reverse=reverse))

        class Manager:
            def all(self):
                return QuerySet([
                    Item(1, "alpha", "open"),
                    Item(2, "beta", "closed"),
                    Item(3, "gamma", "open"),
                ])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "searchable_item"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title).string(),
                    ResourceField("state", resolver=lambda instance, context: instance.state).string(),
                ]

            def filters(self):
                return [ResourceFilter("state", handler=lambda queryset, value, context: queryset.filter(state=value))]

            def sorts(self):
                return [ResourceSort("title", "title")]

            def endpoints(self):
                return [ResourceEndpoint.index().with_pagination(default_limit=20)]

        registry.register_resource(ItemResource())
        payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("searchable_item", "index", "GET"),
            {
                "resource": "searchable_item",
                "endpoint": "index",
                "method": "GET",
                "query": {"filter[state]": "open", "sort": "-title"},
            },
        )

        self.assertEqual([item["id"] for item in payload["data"]], ["3", "1"])

        class SearchResource(ItemResource):
            def type(self):
                return "searcher_item"

            def search(self, criteria, context):
                if criteria.filters["q"] != "alpha":
                    raise AssertionError("unexpected search criteria")
                return ResourceSearchResults(QuerySet([Item(9, "alpha result", "open")]), total=1)

        registry.register_resource(SearchResource())
        search_payload = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("searcher_item", "index", "GET"),
            {
                "resource": "searcher_item",
                "endpoint": "index",
                "method": "GET",
                "query": {"filter[q]": "alpha"},
            },
        )

        self.assertEqual(search_payload["meta"]["total"], 1)
        self.assertEqual(search_payload["data"][0]["id"], "9")

    def test_search_manager_driver_searcher_receives_criteria_from_index_endpoint(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id, title):
                self.id = id
                self.title = title

        class QuerySet(list):
            pass

        class Manager:
            def all(self):
                return QuerySet([Item(1, "first"), Item(2, "second")])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "managed_search_item"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def endpoints(self):
                return [ResourceEndpoint.index().with_pagination(default_limit=1)]

        seen = {}

        def searcher(queryset, criteria, context):
            seen["filters"] = criteria.filters
            seen["limit"] = criteria.limit
            seen["offset"] = criteria.offset
            return ResourceSearchResults(QuerySet([Item(8, "managed")]), total=1, sort_applied=True, pagination_applied=True)

        manager = ResourceSearchManager()
        manager.register_searcher(Item, searcher)
        registry.register_resource(ItemResource())

        app = ExtensionApplication(resource_registry=registry)
        app.search.manager = manager
        with patch("bias_core.extensions.runtime_search.get_extension_host_service", side_effect=lambda key, default=None: app.search if key == "search" else default):
            payload = registry.dispatch_resource_endpoint(
                registry.get_dispatch_endpoint("managed_search_item", "index", "GET"),
                {
                    "resource": "managed_search_item",
                    "endpoint": "index",
                    "method": "GET",
                    "query": {"filter[q]": "needle", "page[limit]": "1", "page[offset]": "2"},
                },
            )

        self.assertEqual(seen["filters"], {"q": "needle"})
        self.assertEqual(seen["limit"], 1)
        self.assertEqual(seen["offset"], 2)
        self.assertEqual(payload["data"][0]["id"], "8")
        self.assertEqual(payload["meta"]["total"], 1)

    def test_search_manager_database_driver_applies_resource_filters(self):
        manager = ResourceSearchManager()
        manager.register_filter(
            "managed_filter_item",
            ResourceSearchFilter("state", lambda state, value, context: [item for item in state.queryset if item.state == value]),
        )
        class Item:
            def __init__(self, state):
                self.state = state

        results = manager.query(
            object,
            [Item("open"), Item("closed")],
            ResourceSearchCriteria(filters={"state": "open"}, resource="managed_filter_item"),
            {},
        )

        self.assertEqual([item.state for item in results.results], ["open"])

    def test_search_driver_extender_bias_style_api_registers_searcher_filters_fulltext_and_mutator(self):
        class Item:
            pass

        calls = []

        def searcher(queryset, criteria, context):
            calls.append(("search", list(queryset)))
            return list(queryset)

        def filter_handler(state, value, context):
            calls.append(("filter", value, context["negate"]))
            return [item for item in state.queryset if item == value]

        def fulltext(state, query, context):
            calls.append(("fulltext", query))
            return state.queryset

        def mutator(state, criteria):
            calls.append(("mutator", criteria.query))
            return state

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="search-ext")
        extender = (
            SearchDriverExtender("database")
            .add_searcher(Item, searcher, target="items")
            .add_filter(searcher, ("state", filter_handler), target="items")
            .set_fulltext(searcher, fulltext, target="items")
            .add_mutator(searcher, mutator, target="items")
        )
        extender.extend(app, extension)
        app.make("search")

        result = app.search.query(
            Item,
            ["open", "closed"],
            ResourceSearchCriteria(filters={"q": "needle", "state": "open"}, query="needle", resource="items"),
            {},
        )

        self.assertEqual(result.results, ["open"])
        self.assertEqual(calls[0], ("fulltext", "needle"))
        self.assertEqual(calls[1], ("filter", "open", False))
        self.assertEqual(calls[2], ("mutator", "needle"))
        self.assertEqual(calls[3], ("search", ["open"]))

    def test_search_filter_context_exposes_state_actor_and_fulltext_flag_like_upstream(self):
        class Item:
            pass

        actor = SimpleNamespace(username="actor")
        seen = {}

        def fulltext(state, query, context):
            seen["fulltext_state"] = context["search_state"] is state
            seen["fulltext_actor"] = context["actor"]
            seen["fulltext_flag"] = state.is_fulltext_search()
            return state

        def filter_handler(state, value, context):
            seen["filter_state"] = context["search_state"] is state
            seen["filter_actor"] = context["actor"]
            seen["state_actor"] = state.get_actor()
            seen["active_count"] = len(state.get_active_filters())
            return state

        manager = ResourceSearchManager()
        manager.register_searcher(Item, lambda queryset, criteria, context: list(queryset))
        manager.set_driver_fulltext("database", Item, fulltext)
        manager.register_driver_filter(
            "database",
            Item,
            ResourceSearchFilter("state", filter_handler),
        )

        result = manager.query(
            Item,
            ["open"],
            ResourceSearchCriteria(user=actor, filters={"q": "needle", "state": "open"}, resource="items"),
            {},
        )

        self.assertEqual(result.results, ["open"])
        self.assertTrue(seen["fulltext_state"])
        self.assertTrue(seen["filter_state"])
        self.assertIs(seen["fulltext_actor"], actor)
        self.assertIs(seen["filter_actor"], actor)
        self.assertIs(seen["state_actor"], actor)
        self.assertTrue(seen["fulltext_flag"])
        self.assertEqual(seen["active_count"], 2)

    def test_search_manager_prefers_default_driver_until_fulltext_like_upstream(self):
        class Item:
            pass

        calls = []

        def database_searcher(queryset, criteria, context):
            calls.append("database")
            return ["database"]

        def custom_searcher(queryset, criteria, context):
            calls.append("custom")
            return ["custom"]

        manager = ResourceSearchManager()
        manager.register_searcher(Item, database_searcher, driver="database")
        manager.register_searcher(Item, custom_searcher, driver="external")
        manager.use_driver_for(Item, "external")

        normal = manager.query(Item, [], ResourceSearchCriteria(resource="items"), {})
        fulltext = manager.query(Item, [], ResourceSearchCriteria(filters={"q": "needle"}, resource="items"), {})

        self.assertEqual(normal.results, ["database"])
        self.assertEqual(fulltext.results, ["custom"])
        self.assertEqual(calls, ["database", "custom"])

    def test_search_manager_uses_settings_driver_for_resource_like_upstream(self):
        class Item:
            pass

        calls = []

        def database_searcher(queryset, criteria, context):
            calls.append("database")
            return ["database"]

        def custom_searcher(queryset, criteria, context):
            calls.append("custom")
            return ["custom"]

        manager = ResourceSearchManager(settings={"search_driver_items": "external"})
        manager.register_searcher(Item, database_searcher, driver="database")
        manager.register_searcher(Item, custom_searcher, driver="external")

        result = manager.query(Item, [], ResourceSearchCriteria(filters={"q": "needle"}, resource="items"), {})

        self.assertEqual(result.results, ["custom"])
        self.assertEqual(calls, ["custom"])

    def test_search_manager_runs_indexer_lifecycle(self):
        class Item:
            pass

        calls = []

        class Indexer:
            def index(self, instance, context):
                calls.append(("index", instance, context["source"]))

            def unindex(self, instance):
                calls.append(("unindex", instance))

            def reindex(self, instances, context):
                calls.append(("reindex", tuple(instances), context["source"]))

        manager = ResourceSearchManager()
        indexer = Indexer()
        manager.register_indexer(Item, indexer)

        manager.index(Item, "a", {"source": "test"})
        manager.unindex(Item, "b")
        manager.reindex(Item, ["c", "d"], {"source": "bulk"})

        self.assertEqual(calls, [
            ("index", "a", "test"),
            ("unindex", "b"),
            ("reindex", ("c", "d"), "bulk"),
        ])

    def test_search_driver_extender_registers_indexer(self):
        class Item:
            pass

        class Indexer:
            pass

        app = ExtensionApplication()
        extension = SimpleNamespace(extension_id="indexer-ext")
        indexer = Indexer()

        SearchDriverExtender("database").add_indexer(Item, indexer, target="items").extend(app, extension)
        app.make("search")

        self.assertEqual(app.search.indexers(Item), (indexer,))

    def test_search_filter_manager_ignores_unknown_filters_like_upstream_search(self):
        class Item:
            pass

        manager = ResourceSearchManager()
        manager.register_searcher(Item, lambda queryset, criteria, context: list(queryset))

        result = manager.query(
            Item,
            ["open"],
            ResourceSearchCriteria(filters={"unknown": "value"}, resource="items"),
            {},
        )

        self.assertEqual(result.results, ["open"])

    def test_resource_dispatcher_returns_plain_error_document_by_default(self):
        registry = ResourceRegistry()
        request = RequestFactory().get("/api/resources/missing/index")

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="missing", endpoint="index")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(payload["error"], "资源端点不存在")
        self.assertNotIn("errors", payload)

    def test_resource_dispatcher_returns_jsonapi_error_document_when_requested(self):
        registry = ResourceRegistry()
        request = RequestFactory().get(
            "/api/resources/missing/index",
            HTTP_ACCEPT="application/vnd.api+json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="missing", endpoint="index")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 404)
        self.assertIn("errors", payload)
        self.assertEqual(payload["errors"][0]["status"], "404")

    def test_database_resource_crud_requires_strict_jsonapi_document(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "strict_item"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).string().writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        endpoint = registry.get_dispatch_endpoint("strict_item", "update", "PATCH")

        with self.assertRaisesMessage(ValueError, "data must be an object"):
            registry.dispatch_resource_endpoint(
                endpoint,
                {
                    "resource": "strict_item",
                    "endpoint": "update",
                    "method": "PATCH",
                    "object_id": "1",
                    "payload": {"title": "new"},
                },
            )

        with self.assertRaisesMessage(ValueError, "collection does not support this resource type"):
            registry.dispatch_resource_endpoint(
                endpoint,
                {
                    "resource": "strict_item",
                    "endpoint": "update",
                    "method": "PATCH",
                    "object_id": "1",
                    "payload": {"data": {"type": "wrong", "attributes": {"title": "new"}}},
                },
            )

        response = registry.dispatch_resource_endpoint(
            endpoint,
            {
                "resource": "strict_item",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {"data": {"attributes": {"title": "new"}}},
                "query": {},
            },
        )

        self.assertEqual(response["data"]["attributes"]["title"], "new")

    def test_database_resource_crud_can_opt_in_to_legacy_flat_payload(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def __init__(self):
                self.item = Item()

            def all(self):
                return QuerySet([self.item])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "legacy_item"

            def accepts_legacy_payload(self, context):
                return True

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).string().writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        response = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("legacy_item", "update", "PATCH"),
            {
                "resource": "legacy_item",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {"title": "new"},
                "query": {},
            },
        )

        self.assertEqual(response["data"]["attributes"]["title"], "new")
        self.assertEqual(Item.objects.item.title, "new")

    def test_database_resource_crud_accepts_declared_jsonapi_type_aliases(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def __init__(self):
                self.item = Item()

            def all(self):
                return QuerySet([self.item])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "alias_item"

            def jsonapi_types(self):
                return ("alias_item", "alias-items")

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).string().writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        response = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("alias_item", "update", "PATCH"),
            {
                "resource": "alias_item",
                "endpoint": "update",
                "method": "PATCH",
                "object_id": "1",
                "payload": {"data": {"type": "alias-items", "attributes": {"title": "new"}}},
                "query": {},
            },
        )

        self.assertEqual(response["data"]["attributes"]["title"], "new")
        self.assertEqual(Item.objects.item.title, "new")

    def test_resource_endpoint_can_delegate_response_entirely_to_callback(self):
        registry = ResourceRegistry()
        serialize_calls = []

        class Item:
            objects = None

            def __init__(self, id=1, title="first"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def all(self):
                return self

            def filter(self, **kwargs):
                return self

            def order_by(self, *args):
                return self

            def count(self):
                return len(self)

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "callback_only_item"

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: serialize_calls.append(instance.id) or instance.title,
                    )
                ]

            def endpoints(self):
                return [
                    ResourceEndpoint(
                        name="index",
                        kind="index",
                        response_callback=lambda context, response: {"count": len(response)},
                        response_callback_only=True,
                    )
                ]

        registry.register_resource(ItemResource())
        response = registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("callback_only_item", "index", "GET"),
            {
                "resource": "callback_only_item",
                "endpoint": "index",
                "method": "GET",
                "payload": {},
                "query": {},
            },
        )

        self.assertEqual(response, {"count": 1})
        self.assertEqual(serialize_calls, [])

    def test_database_resource_endpoint_context_exposes_registry_to_resource_methods(self):
        registry = ResourceRegistry()
        seen = {}

        class Item:
            def __init__(self, id=1):
                self.id = id

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "registry_context_item"

            def endpoints(self):
                return [ResourceEndpoint.show()]

            def find(self, object_id, context):
                seen["registry"] = context.registry
                seen["api"] = context.api
                return Item(object_id)

        registry.register_resource(ItemResource())

        registry.dispatch_resource_endpoint(
            registry.get_dispatch_endpoint("registry_context_item", "show", "GET"),
            {"resource": "registry_context_item", "endpoint": "show", "method": "GET", "object_id": "1", "query": {}},
        )

        self.assertIs(seen["registry"], registry)
        self.assertIs(seen["api"], registry)

    def test_database_resource_endpoint_plain_response_callback_runs_only_for_plain_requests(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="plain"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()
        serialize_calls = []

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "plain_callback_item"

            def fields(self):
                return [
                    ResourceField(
                        "title",
                        resolver=lambda instance, context: serialize_calls.append(instance.id) or instance.title,
                    )
                ]

            def endpoints(self):
                return [
                    ResourceEndpoint.show().plain_response(
                        lambda context, response: {
                            "id": context["result"].id,
                            "title": context["result"].title,
                        }
                    )
                ]

        registry.register_resource(ItemResource())
        definition = registry.get_dispatch_endpoint("plain_callback_item", "show", "GET")

        plain_response = registry.dispatch_resource_endpoint(
            definition,
            {
                "resource": "plain_callback_item",
                "endpoint": "show",
                "method": "GET",
                "object_id": "1",
                "payload": {},
                "query": {},
            },
        )
        self.assertEqual(serialize_calls, [])

        jsonapi_response = registry.dispatch_resource_endpoint(
            definition,
            {
                "resource": "plain_callback_item",
                "endpoint": "show",
                "method": "GET",
                "object_id": "1",
                "payload": {},
                "query": {},
                "request": RequestFactory().get("/api/plain-callback-items/1", HTTP_ACCEPT="application/vnd.api+json"),
            },
        )

        self.assertEqual(plain_response, {"id": 1, "title": "plain"})
        self.assertEqual(jsonapi_response["data"]["type"], "plain_callback_item")
        self.assertEqual(jsonapi_response["data"]["attributes"], {"title": "plain"})
        self.assertEqual(serialize_calls, [1])

    def test_serialize_resource_jsonapi_response_helper_respects_accept_and_options(self):
        from bias_core.resource_api import ResourceQueryOptions, serialize_resource_jsonapi_response

        registry = ResourceRegistry()

        class Owner:
            def __init__(self, id=7, username="neo"):
                self.id = id
                self.username = username

        class Item:
            def __init__(self, id=1, title="hello", owner=None):
                self.id = id
                self.title = title
                self.owner = owner or Owner()

        class OwnerResource(Resource):
            def type(self):
                return "helper_owner"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class ItemResource(Resource):
            def type(self):
                return "helper_item"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="helper_owner",
                    )
                ]

        registry.register_resource(OwnerResource())
        registry.register_resource(ItemResource())
        item = Item()
        plain_context = {"request": RequestFactory().get("/api/helper-items/1")}
        jsonapi_context = {"request": RequestFactory().get("/api/helper-items/1", HTTP_ACCEPT="application/vnd.api+json")}

        self.assertIsNone(
            serialize_resource_jsonapi_response(
                registry,
                "helper_item",
                item,
                plain_context,
            )
        )
        response = serialize_resource_jsonapi_response(
            registry,
            "helper_item",
            item,
            jsonapi_context,
            include=("owner",),
            resource_options=ResourceQueryOptions(),
        )

        payload = json.loads(response.content)
        self.assertEqual(response["Content-Type"], "application/vnd.api+json")
        self.assertEqual(payload["data"]["attributes"], {"title": "hello"})
        self.assertEqual(payload["data"]["relationships"]["owner"]["data"], {"type": "helper_owner", "id": "7"})
        self.assertEqual(payload["included"][0]["type"], "helper_owner")

        sparse_response = serialize_resource_jsonapi_response(
            registry,
            "helper_item",
            item,
            jsonapi_context,
            resource_options=ResourceQueryOptions(fields=("title",)),
        )
        sparse_payload = json.loads(sparse_response.content)
        self.assertEqual(sparse_payload["data"]["attributes"], {"title": "hello"})
        self.assertNotIn("relationships", sparse_payload["data"])

    def test_serialize_resource_plain_helper_respects_options_and_includes(self):
        from bias_core.resource_api import ResourceQueryOptions, serialize_resource_plain

        registry = ResourceRegistry()

        class Owner:
            def __init__(self, id=7, username="neo"):
                self.id = id
                self.username = username

        class Item:
            def __init__(self, id=1, title="hello", owner=None):
                self.id = id
                self.title = title
                self.owner = owner or Owner()

        class OwnerResource(Resource):
            def type(self):
                return "plain_helper_owner"

            def fields(self):
                return [ResourceField("username", resolver=lambda instance, context: instance.username)]

        class ItemResource(Resource):
            def type(self):
                return "plain_helper_item"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def relationships(self):
                return [
                    ResourceRelationship(
                        "owner",
                        resolver=lambda instance, context: instance.owner,
                        resource_type="plain_helper_owner",
                    )
                ]

        registry.register_resource(OwnerResource())
        registry.register_resource(ItemResource())

        payload = serialize_resource_plain(
            registry,
            "plain_helper_item",
            Item(),
            {"plain_related_fields": {"plain_helper_owner": ("username",)}},
            resource_options=ResourceQueryOptions(fields=("title",), includes=("owner",)),
        )

        self.assertEqual(payload, {"title": "hello", "owner": {"username": "neo"}})

    def test_plain_relationship_serialization_isolates_child_context(self):
        registry = ResourceRegistry()

        class Node:
            def __init__(self, id, name, children=()):
                self.id = id
                self.name = name
                self.children = list(children)

        class NodeResource(Resource):
            def type(self):
                return "depth_node"

            def fields(self):
                return [ResourceField("name", resolver=lambda instance, context: instance.name)]

            def relationships(self):
                return [
                    ResourceRelationship(
                        "children",
                        resolver=lambda instance, context: instance.children if context.get("plain_children_depth", 0) > 0 else [],
                        resource_type="depth_node",
                        many=True,
                    )
                ]

        registry.register_resource(NodeResource())
        first = Node(2, "first", [Node(4, "first-child")])
        second = Node(3, "second", [Node(5, "second-child")])
        root = Node(1, "root", [first, second])

        payload = registry.serialize(
            "depth_node",
            root,
            {"plain_children_depth": 1},
            include=("children",),
        )

        self.assertEqual(
            payload["children"],
            [
                {"name": "first"},
                {"name": "second"},
            ],
        )

    def test_resource_field_plain_and_jsonapi_visibility_helpers(self):
        plain_field = ResourceField("legacy", resolver=lambda instance, context: "plain").plain_only()
        jsonapi_field = ResourceField("wire", resolver=lambda instance, context: "jsonapi").jsonapi_only()
        conditional_plain_field = (
            ResourceField("adminLegacy", resolver=lambda instance, context: "plain")
            .visible_when(lambda instance, context: bool(context.get("admin")))
            .plain_only()
        )
        plain_context = {"request": RequestFactory().get("/api/items/1")}
        jsonapi_context = {"request": RequestFactory().get("/api/items/1", HTTP_ACCEPT="application/vnd.api+json")}

        self.assertTrue(plain_field.is_visible(None, plain_context))
        self.assertFalse(plain_field.is_visible(None, jsonapi_context))
        self.assertFalse(jsonapi_field.is_visible(None, plain_context))
        self.assertTrue(jsonapi_field.is_visible(None, jsonapi_context))
        self.assertFalse(conditional_plain_field.is_visible(None, plain_context))
        self.assertTrue(conditional_plain_field.is_visible(None, {**plain_context, "admin": True}))
        self.assertFalse(conditional_plain_field.is_visible(None, {**jsonapi_context, "admin": True}))

    def test_apply_resource_preloads_merges_default_and_requested_includes(self):
        from bias_core.resource_api import ResourceQueryOptions, apply_resource_preloads

        class Registry:
            def __init__(self):
                self.calls = []

            def apply_preload_plan(self, queryset, resource, context, *, only=None, include=()):
                self.calls.append((queryset, resource, context, only, include))
                return ["preloaded"]

        registry = Registry()
        result = apply_resource_preloads(
            registry,
            ["row"],
            "tag",
            context={"user": "alice"},
            resource_options=ResourceQueryOptions(fields=("name",), includes=("children", "parent")),
            default_includes=("parent",),
        )

        self.assertEqual(result, ["preloaded"])
        self.assertEqual(
            registry.calls,
            [(["row"], "tag", {"user": "alice"}, ("name",), ("parent", "children"))],
        )

    def test_jsonapi_validation_error_carries_source_pointer(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, email="old@example.com"):
                self.id = id
                self.email = email

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "validated_item"

            def fields(self):
                return [ResourceField("email", resolver=lambda instance, context: instance.email).string().email().writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/validated_item/1",
            data=json.dumps({"data": {"type": "validated_item", "attributes": {"email": "bad"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="validated_item", endpoint="update", object_id="1")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["errors"][0]["source"]["pointer"], "/data/attributes/email")

    def test_resource_validation_factory_returns_jsonapi_pointer_errors(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "factory_validated_item"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title).string().writable_when()]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_factory(self):
                return lambda data, context: {"title": "Title rejected"}

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/factory_validated_item/1",
            data=json.dumps({"data": {"type": "factory_validated_item", "attributes": {"title": "new"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="factory_validated_item", endpoint="update", object_id="1")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(payload["errors"][0]["source"]["pointer"], "/data/attributes/title")
        self.assertEqual(payload["errors"][0]["detail"], "Title rejected")

    def test_resource_validation_collects_field_rules_before_factory(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="old"):
                self.id = id
                self.title = title

            def save(self):
                return None

        class QuerySet(list):
            def filter(self, **kwargs):
                return self

            def first(self):
                return self[0]

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "aggregated_validated_item"

            def fields(self):
                return [
                    ResourceField("title", resolver=lambda instance, context: instance.title)
                    .string()
                    .min_length(3)
                    .writable_when()
                ]

            def endpoints(self):
                return [ResourceEndpoint.update()]

            def validation_messages(self):
                return {"title": "Title too short"}

            def validation_factory(self):
                return lambda data, context: {"title": "Factory rejected"}

        registry.register_resource(ItemResource())
        request = RequestFactory().patch(
            "/api/resources/aggregated_validated_item/1",
            data=json.dumps({"data": {"type": "aggregated_validated_item", "attributes": {"title": "x"}}}),
            content_type="application/json",
        )

        with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
            response = dispatch_resource_endpoint(request, resource="aggregated_validated_item", endpoint="update", object_id="1")

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            [item["detail"] for item in payload["errors"]],
            ["Title too short", "Factory rejected"],
        )

    def test_resource_route_definitions_follow_Bias_endpoint_paths(self):
        registry = ResourceRegistry()

        class DemoResource(Resource):
            def type(self):
                return "demo_items"

            def endpoints(self):
                return [
                    ResourceEndpoint.index(),
                    ResourceEndpoint.show(),
                    ResourceEndpoint.update(),
                    ResourceEndpoint("feature", methods=("POST",), handler=lambda context: {"ok": True}),
                    ResourceEndpoint("named", methods=("GET",), path="/{object_id}/named", handler=lambda context: {"ok": True}),
                ]

        registry.register_resource(DemoResource())

        routes = {
            (route.endpoint, route.methods): route.path
            for route in build_resource_route_definitions(registry)
        }

        self.assertEqual(routes[("index", ("GET",))], "/demo_items")
        self.assertEqual(routes[("show", ("GET",))], "/demo_items/{object_id}")
        self.assertEqual(routes[("update", ("PATCH", "PUT"))], "/demo_items/{object_id}")
        self.assertEqual(routes[("feature", ("POST",))], "/demo_items/feature")
        self.assertEqual(routes[("named", ("GET",))], "/demo_items/{object_id}/named")

    def test_resource_route_definitions_include_extension_endpoint_only_resources(self):
        registry = ResourceRegistry()
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="post",
                endpoint="like",
                module_id="likes",
                handler=lambda context: {"ok": True},
                methods=("POST", "DELETE"),
                path="posts/{object_id}/like",
                absolute_path=True,
            )
        )

        routes = {
            (route.resource, route.endpoint, route.methods): route.path
            for route in build_resource_route_definitions(registry)
        }

        self.assertEqual(routes[("post", "like", ("DELETE", "POST"))], "/posts/{object_id}/like")

    def test_resource_path_routes_group_same_path_operations(self):
        registry = ResourceRegistry()
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="shared_item",
                endpoint="create",
                module_id="shared",
                handler=lambda context: {"method": "POST"},
                methods=("POST",),
                path="/shared-items",
                absolute_path=True,
            )
        )
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="shared_item",
                endpoint="index",
                module_id="shared",
                handler=lambda context: {"method": "GET"},
                methods=("GET",),
                path="/shared-items",
                absolute_path=True,
            )
        )

        routes = {
            route.path: route
            for route in build_resource_path_route_definitions(registry)
        }

        route = routes["/shared-items"]
        self.assertEqual(route.methods, ("GET", "POST"))
        self.assertEqual(
            {(operation.endpoint, operation.methods) for operation in route.operations},
            {("create", ("POST",)), ("index", ("GET",))},
        )

    def test_resource_endpoint_router_dispatches_same_path_by_method(self):
        registry = ResourceRegistry()
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="shared_item",
                endpoint="create",
                module_id="shared",
                handler=lambda context: {"endpoint": context["endpoint"], "method": context["method"]},
                methods=("POST",),
                path="/shared-items",
                absolute_path=True,
            )
        )
        registry.register_endpoint(
            ResourceEndpointDefinition(
                resource="shared_item",
                endpoint="index",
                module_id="shared",
                handler=lambda context: {"endpoint": context["endpoint"], "method": context["method"]},
                methods=("GET",),
                path="/shared-items",
                absolute_path=True,
            )
        )
        host = SimpleNamespace(
            resources=registry,
            make=lambda key, default=None: SimpleNamespace(get_mounts=lambda: ()) if key == "routes" else default,
        )
        api = build_api_application(extension_host=host, urls_namespace=f"same-path-resource-test-api-{uuid.uuid4().hex}")
        api_urls = api.urls
        urlconf_name = "bias_core.tests_same_path_resource_urls"
        urlconf = ModuleType(urlconf_name)
        urlconf.urlpatterns = [path("api/", api_urls)]
        sys.modules[urlconf_name] = urlconf

        try:
            clear_url_caches()
            with override_settings(ROOT_URLCONF=urlconf_name):
                with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
                    get_response = self.client.get("/api/shared-items")
                    post_response = self.client.post(
                        "/api/shared-items",
                        data=json.dumps({}),
                        content_type="application/json",
                    )
        finally:
            clear_url_caches()
            sys.modules.pop(urlconf_name, None)

        self.assertEqual(get_response.status_code, 200, get_response.content)
        self.assertEqual(get_response.json(), {"endpoint": "index", "method": "GET"})
        self.assertEqual(post_response.status_code, 200, post_response.content)
        self.assertEqual(post_response.json(), {"endpoint": "create", "method": "POST"})

    def test_resource_endpoint_routes_are_registered_on_api_application(self):
        registry = ResourceRegistry()

        class Item:
            objects = None

            def __init__(self, id=1, title="hello"):
                self.id = id
                self.title = title

        class QuerySet(list):
            def filter(self, **kwargs):
                return QuerySet([item for item in self if str(item.id) == str(kwargs.get("pk"))])

            def first(self):
                return self[0] if self else None

        class Manager:
            def all(self):
                return QuerySet([Item()])

        Item.objects = Manager()

        class ItemResource(DatabaseResource):
            model = Item

            def type(self):
                return "auto_items"

            def fields(self):
                return [ResourceField("title", resolver=lambda instance, context: instance.title)]

            def endpoints(self):
                return [ResourceEndpoint.show()]

        registry.register_resource(ItemResource())
        host = SimpleNamespace(
            resources=registry,
            make=lambda key, default=None: SimpleNamespace(get_mounts=lambda: ()) if key == "routes" else default,
        )
        api = build_api_application(extension_host=host, urls_namespace=f"auto-resource-test-api-{uuid.uuid4().hex}")
        api_urls = api.urls
        self.assertTrue(any(
            "auto_items" in str(pattern)
            for pattern in api_urls[0]
        ))
        urlconf_name = "bias_core.tests_auto_resource_urls"
        urlconf = ModuleType(urlconf_name)
        urlconf.urlpatterns = [path("api/", api_urls)]
        sys.modules[urlconf_name] = urlconf

        try:
            clear_url_caches()
            with override_settings(ROOT_URLCONF=urlconf_name):
                with patch("bias_core.resource_dispatcher.get_runtime_resource_registry", return_value=registry):
                    response = self.client.get("/api/auto_items/1")
        finally:
            clear_url_caches()
            sys.modules.pop(urlconf_name, None)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"data": {"type": "auto_items", "id": "1", "links": {"self": "/api/auto_items/1"}, "attributes": {"title": "hello"}}},
        )

