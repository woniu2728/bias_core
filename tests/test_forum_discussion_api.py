from tests.common import *
from django.contrib.auth import get_user_model
from django.test.utils import CaptureQueriesContext


class ForumDiscussionApiTests(TestCase):
    def setUp(self):
        reset_extension_runtime_state()
        clear_url_caches()
        import tests.urls as test_urls

        test_urls.rebuild_api_urlpatterns()
        self.addCleanup(reset_extension_runtime_state)
        self.addCleanup(clear_url_caches)

        self.user = get_user_model().objects.create_user(
            username="forum-user",
            email="forum-user@example.com",
            password="password123",
            is_email_confirmed=True,
        )
        self.other_user = get_user_model().objects.create_user(
            username="other-user",
            email="other-user@example.com",
            password="password123",
            is_email_confirmed=True,
        )
        self.pending_author = get_user_model().objects.create_user(
            username="pending-author",
            email="pending-author@example.com",
            password="password123",
            is_email_confirmed=True,
        )
        self.pending_replier = get_user_model().objects.create_user(
            username="pending-replier",
            email="pending-replier@example.com",
            password="password123",
            is_email_confirmed=True,
        )
        self.permission_moderator = get_user_model().objects.create_user(
            username="permission-moderator",
            email="permission-moderator@example.com",
            password="password123",
            is_email_confirmed=True,
        )
        self.moderator = get_user_model().objects.create_user(
            username="forum-moderator",
            email="forum-moderator@example.com",
            password="password123",
            is_email_confirmed=True,
            is_staff=True,
        )
        self.admin = get_user_model().objects.create_superuser(
            username="forum-admin",
            email="forum-admin@example.com",
            password="password123",
        )
        from bias_ext_tags.backend.models import Tag

        self.tag = Tag.objects.create(
            name="General",
            slug="general",
            position=1,
            is_primary=True,
        )
        self.grant_permissions(
            self.moderator,
            "viewForum",
            "discussion.reply",
            "discussion.edit",
            "discussion.rename",
            "discussion.hide",
            "discussion.delete",
            "post.edit",
            "post.hide",
            "post.delete",
            "admin.approval.view",
            "admin.approval.approve",
            "admin.approval.reject",
        )
        self.grant_permissions(
            self.admin,
            "viewForum",
            "admin.approval.view",
            "admin.approval.approve",
            "admin.approval.reject",
        )
        self.grant_permissions(
            self.user,
            "viewForum",
            "startDiscussion",
            "startDiscussionWithoutApproval",
            "discussion.reply",
            "replyWithoutApproval",
        )
        self.grant_permissions(
            self.other_user,
            "viewForum",
            "startDiscussion",
            "startDiscussionWithoutApproval",
            "discussion.reply",
            "replyWithoutApproval",
        )
        self.grant_permissions(self.pending_author, "viewForum", "startDiscussion", "discussion.reply")
        self.grant_permissions(self.pending_replier, "viewForum", "startDiscussion", "discussion.reply")
        self.grant_permissions(
            self.permission_moderator,
            "viewForum",
            "discussion.reply",
            "replyWithoutApproval",
            "discussion.lock",
            "discussion.sticky",
        )
        self.grant_permissions_for_approval_gate()

    def auth_header(self, user=None):
        token = RefreshToken.for_user(user or self.user).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def grant_permissions(self, user, *permissions):
        from bias_ext_users.backend.models import Group, Permission

        group = Group.objects.create(name=f"group-{user.username}")
        for permission in permissions:
            Permission.objects.create(group=group, permission=permission)
        user.user_groups.add(group)
        if hasattr(user, "_forum_permission_cache"):
            delattr(user, "_forum_permission_cache")

    def grant_permissions_for_approval_gate(self):
        from bias_ext_users.backend.models import Group, Permission

        gate_group = Group.objects.create(name="approval-gate")
        Permission.objects.create(group=gate_group, permission="startDiscussionWithoutApproval")
        Permission.objects.create(group=gate_group, permission="replyWithoutApproval")

    def discussion_create_payload(self, title, content):
        return {
            "data": {
                "attributes": {
                    "title": title,
                    "content": content,
                },
                "relationships": {
                    "tags": {
                        "data": [
                            {"type": "tag", "id": str(self.tag.id)},
                        ],
                    },
                },
            }
        }

    def create_discussion_via_api(self, *, title, content, user):
        return self.client.post(
            "/api/discussions/",
            data=json.dumps(self.discussion_create_payload(title, content)),
            content_type="application/json",
            **self.auth_header(user),
        )

    def create_discussion(self, title="First discussion", content="First post body", user=None):
        from bias_ext_discussions.backend.services import DiscussionService

        return DiscussionService.create_discussion(
            title=title,
            content=content,
            user=user or self.user,
            extension_payload=discussion_tags_payload([self.tag.id]),
        )

    def create_reply(self, discussion, content="Reply body", user=None):
        from bias_ext_posts.backend.services import PostService

        return PostService.create_post(
            discussion_id=discussion.id,
            content=content,
            user=user or self.other_user,
        )

    def search_result_ids(self, response, key):
        self.assertEqual(response.status_code, 200, response.content)
        return {item["id"] for item in response.json()[key]}

    def assert_plain_api_error(self, response, *, status, code, message):
        self.assertEqual(response.status_code, status, response.content)
        payload = response.json()
        self.assertEqual(payload["error"], message)
        self.assertEqual(payload["message"], message)
        self.assertEqual(payload["code"], code)
        self.assertEqual(payload["field_errors"], {})
        self.assertTrue(payload["request_id"])

    def test_discussion_list_endpoint_returns_visible_discussions_with_default_relationships(self):
        discussion = self.create_discussion(title="Visible topic", content="Opening post")
        self.create_reply(discussion, content="Follow-up reply")

        response = self.client.get("/api/discussions/")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["sort"], "latest")
        self.assertIn("available_sorts", payload)
        self.assertIn("available_filters", payload)
        row = payload["data"][0]
        self.assertEqual(row["id"], discussion.id)
        self.assertEqual(row["title"], "Visible topic")
        self.assertEqual(row["user"]["username"], self.user.username)
        self.assertEqual(row["last_posted_user"]["username"], self.other_user.username)
        self.assertEqual(row["most_relevant_post"]["number"], 1)
        self.assertEqual(row["most_relevant_post"]["user"]["username"], self.user.username)

    def test_discussion_list_endpoint_respects_resource_fields_and_includes(self):
        discussion = self.create_discussion(title="Resource list topic", content="Opening resource body")
        reply = self.create_reply(discussion, content="Included resource reply", user=self.other_user)

        response = self.client.get(
            "/api/discussions/",
            {
                "fields[discussion]": "can_reply,can_hide",
                "include": "first_post,last_post.user",
            },
            **self.auth_header(self.user),
        )

        self.assertEqual(response.status_code, 200, response.content)
        row = response.json()["data"][0]
        self.assertEqual(row["id"], discussion.id)
        self.assertEqual(row["title"], "Resource list topic")
        self.assertTrue(row["can_reply"])
        self.assertFalse(row["can_hide"])
        self.assertEqual(row["first_post"]["content"], "Opening resource body")
        self.assertEqual(row["last_post"]["id"], reply.id)
        self.assertEqual(row["last_post"]["user"]["username"], self.other_user.username)

    def test_discussion_list_endpoint_keeps_query_count_within_budget(self):
        for index in range(6):
            discussion = self.create_discussion(
                title=f"Budget topic {index}",
                content=f"Budget opening {index}",
                user=self.user if index % 2 == 0 else self.other_user,
            )
            self.create_reply(
                discussion,
                content=f"Budget reply {index}",
                user=self.other_user if index % 2 == 0 else self.user,
            )

        with CaptureQueriesContext(connection) as context:
            response = self.client.get("/api/discussions/?limit=6", **self.auth_header(self.user))

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["data"]), 6)
        self.assertLessEqual(
            len(context.captured_queries),
            24,
            "\n".join(query["sql"] for query in context.captured_queries),
        )

    def test_discussion_list_endpoint_supports_core_sorts_and_filters(self):
        own_discussion = self.create_discussion(title="Own topic", user=self.user)
        other_discussion = self.create_discussion(title="Other topic", user=self.other_user)
        from bias_ext_discussions.backend.services import DiscussionService

        DiscussionService.update_read_state(
            discussion_id=other_discussion.id,
            user=self.user,
            last_read_post_number=1,
        )
        self.create_reply(other_discussion, content="Unread reply", user=self.other_user)

        newest_response = self.client.get("/api/discussions/?sort=newest")
        top_response = self.client.get("/api/discussions/?sort=top")
        mine_response = self.client.get("/api/discussions/?filter=my", **self.auth_header(self.user))
        unread_response = self.client.get("/api/discussions/?filter=unread", **self.auth_header(self.user))

        self.assertEqual(newest_response.status_code, 200, newest_response.content)
        self.assertEqual(newest_response.json()["sort"], "newest")
        self.assertEqual(top_response.status_code, 200, top_response.content)
        self.assertEqual(top_response.json()["sort"], "top")
        self.assertEqual(mine_response.status_code, 200, mine_response.content)
        self.assertEqual(mine_response.json()["filter"], "my")
        self.assertEqual([item["id"] for item in mine_response.json()["data"]], [own_discussion.id])
        self.assertEqual(unread_response.status_code, 200, unread_response.content)
        self.assertEqual(unread_response.json()["filter"], "unread")
        self.assertEqual([item["id"] for item in unread_response.json()["data"]], [other_discussion.id])

    def test_discussion_detail_endpoint_returns_first_post_and_read_state(self):
        discussion = self.create_discussion(title="Detail topic", content="Opening detail")
        self.create_reply(discussion, content="Second post")

        response = self.client.get(f"/api/discussions/{discussion.id}", **self.auth_header(self.user))

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["id"], discussion.id)
        self.assertEqual(payload["title"], "Detail topic")
        self.assertEqual(payload["first_post"]["number"], 1)
        self.assertEqual(payload["first_post"]["content"], "Opening detail")
        self.assertEqual(payload["user"]["username"], self.user.username)
        self.assertIn("last_read_post_number", payload)
        self.assertIn("unread_count", payload)

    def test_discussion_detail_endpoint_respects_resource_fields_and_includes(self):
        discussion = self.create_discussion(title="Resource detail topic", content="Opening detail body")
        reply = self.create_reply(discussion, content="Detail include reply", user=self.other_user)

        response = self.client.get(
            f"/api/discussions/{discussion.id}",
            {
                "fields[discussion]": "can_reply,can_hide",
                "include": "last_post.user",
            },
            **self.auth_header(self.user),
        )

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["id"], discussion.id)
        self.assertEqual(payload["title"], "Resource detail topic")
        self.assertTrue(payload["can_reply"])
        self.assertFalse(payload["can_hide"])
        self.assertEqual(payload["last_post"]["id"], reply.id)
        self.assertEqual(payload["last_post"]["user"]["username"], self.other_user.username)
        self.assertEqual(payload["first_post"]["content"], "Opening detail body")

    def test_post_stream_endpoint_supports_window_parameters(self):
        discussion = self.create_discussion(title="Post stream", content="Opening")
        post_two = self.create_reply(discussion, content="Second")
        post_three = self.create_reply(discussion, content="Third")

        response = self.client.get(f"/api/discussions/{discussion.id}/posts?near={post_two.number}&limit=2")

        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertEqual(payload["total"], 3)
        self.assertEqual(payload["limit"], 2)
        numbers = [item["number"] for item in payload["data"]]
        self.assertIn(post_two.number, numbers)
        self.assertTrue(all(item["discussion"]["id"] == discussion.id for item in payload["data"]))
        self.assertLessEqual(payload["current_start"], post_two.number)
        self.assertGreaterEqual(payload["current_end"], post_two.number)
        self.assertGreaterEqual(post_three.number, post_two.number)

        before_response = self.client.get(f"/api/discussions/{discussion.id}/posts?before={post_three.number}&limit=1")
        after_response = self.client.get(f"/api/discussions/{discussion.id}/posts?after={post_two.number}&limit=1")

        self.assertEqual(before_response.status_code, 200, before_response.content)
        self.assertEqual([item["number"] for item in before_response.json()["data"]], [post_two.number])
        self.assertTrue(before_response.json()["has_previous"])
        self.assertTrue(before_response.json()["has_more"])
        self.assertEqual(after_response.status_code, 200, after_response.content)
        self.assertEqual([item["number"] for item in after_response.json()["data"]], [post_three.number])
        self.assertTrue(after_response.json()["has_previous"])
        self.assertFalse(after_response.json()["has_more"])

    def test_post_stream_and_detail_endpoints_respect_resource_fields_and_includes(self):
        discussion = self.create_discussion(title="Post resource discussion", content="Opening")
        reply = self.create_reply(discussion, content="Reply with resource fields", user=self.other_user)

        stream_response = self.client.get(
            f"/api/discussions/{discussion.id}/posts",
            {
                "fields[post]": "can_hide,post_type",
                "include": "discussion",
            },
            **self.auth_header(self.moderator),
        )
        detail_response = self.client.get(
            f"/api/posts/{reply.id}",
            {
                "fields[post]": "can_hide,post_type",
                "include": "discussion",
            },
            **self.auth_header(self.moderator),
        )

        self.assertEqual(stream_response.status_code, 200, stream_response.content)
        stream_reply = next(item for item in stream_response.json()["data"] if item["id"] == reply.id)
        self.assertEqual(stream_reply["content"], "Reply with resource fields")
        self.assertTrue(stream_reply["can_hide"])
        self.assertEqual(stream_reply["post_type"]["code"], "comment")
        self.assertEqual(stream_reply["discussion"]["id"], discussion.id)
        self.assertEqual(stream_reply["discussion"]["title"], "Post resource discussion")

        self.assertEqual(detail_response.status_code, 200, detail_response.content)
        detail_payload = detail_response.json()
        self.assertEqual(detail_payload["id"], reply.id)
        self.assertTrue(detail_payload["can_hide"])
        self.assertEqual(detail_payload["post_type"]["code"], "comment")
        self.assertEqual(detail_payload["discussion"]["id"], discussion.id)

    def test_core_forum_resource_endpoints_return_consistent_plain_error_format(self):
        discussion = self.create_discussion(title="Error resource topic", content="Opening")
        reply = self.create_reply(discussion, content="Error resource reply", user=self.other_user)

        missing_discussion_response = self.client.get("/api/discussions/999999")
        forbidden_discussion_response = self.client.post(
            f"/api/discussions/{discussion.id}/lock",
            **self.auth_header(self.other_user),
        )
        missing_stream_response = self.client.get("/api/discussions/999999/posts")
        missing_post_response = self.client.get("/api/posts/999999")
        forbidden_post_response = self.client.patch(
            f"/api/posts/{reply.id}",
            data=json.dumps({"content": "Unauthorized edit"}),
            content_type="application/json",
            **self.auth_header(self.user),
        )

        self.assert_plain_api_error(
            missing_discussion_response,
            status=404,
            code="not_found",
            message="讨论不存在",
        )
        self.assert_plain_api_error(
            forbidden_discussion_response,
            status=403,
            code="forbidden",
            message="没有权限锁定/解锁讨论",
        )
        self.assert_plain_api_error(
            missing_stream_response,
            status=404,
            code="not_found",
            message="讨论不存在",
        )
        self.assert_plain_api_error(
            missing_post_response,
            status=404,
            code="not_found",
            message="帖子不存在",
        )
        self.assert_plain_api_error(
            forbidden_post_response,
            status=403,
            code="forbidden",
            message="没有权限编辑此帖子",
        )

    def test_discussion_read_state_endpoints_mark_single_and_all_discussions_read(self):
        first_discussion = self.create_discussion(title="Read state one", content="Opening", user=self.user)
        second_discussion = self.create_discussion(title="Read state two", content="Opening", user=self.other_user)
        from bias_ext_discussions.backend.services import DiscussionService

        DiscussionService.update_read_state(
            discussion_id=second_discussion.id,
            user=self.user,
            last_read_post_number=1,
        )
        first_reply = self.create_reply(first_discussion, content="Unread first", user=self.other_user)
        second_reply = self.create_reply(second_discussion, content="Unread second", user=self.other_user)

        read_response = self.client.post(
            f"/api/discussions/{first_discussion.id}/read",
            data=json.dumps({"last_read_post_number": first_reply.number}),
            content_type="application/json",
            **self.auth_header(self.user),
        )
        unread_response = self.client.get("/api/discussions/?filter=unread", **self.auth_header(self.user))

        self.assertEqual(read_response.status_code, 200, read_response.content)
        self.assertEqual(read_response.json()["last_read_post_number"], first_reply.number)
        self.assertEqual(unread_response.status_code, 200, unread_response.content)
        self.assertEqual([item["id"] for item in unread_response.json()["data"]], [second_discussion.id])

        mark_all_response = self.client.post("/api/discussions/read-all", **self.auth_header(self.user))
        unread_after_mark_all_response = self.client.get("/api/discussions/?filter=unread", **self.auth_header(self.user))

        self.assertEqual(mark_all_response.status_code, 200, mark_all_response.content)
        self.assertIn("marked_all_as_read_at", mark_all_response.json())
        self.assertEqual(unread_after_mark_all_response.status_code, 200, unread_after_mark_all_response.content)
        self.assertEqual(unread_after_mark_all_response.json()["data"], [])
        self.assertEqual(second_reply.number, 2)

    def test_authenticated_user_can_create_discussion_and_reply(self):
        create_response = self.client.post(
            "/api/discussions/",
            data=json.dumps(self.discussion_create_payload("Created through API", "Created body")),
            content_type="application/json",
            **self.auth_header(self.user),
        )

        self.assertEqual(create_response.status_code, 200, create_response.content)
        created = create_response.json()
        self.assertEqual(created["title"], "Created through API")
        self.assertEqual(created["user"]["username"], self.user.username)

        reply_response = self.client.post(
            f"/api/discussions/{created['id']}/posts",
            data=json.dumps({"content": "Reply through API"}),
            content_type="application/json",
            **self.auth_header(self.other_user),
        )

        self.assertEqual(reply_response.status_code, 200, reply_response.content)
        reply = reply_response.json()
        self.assertEqual(reply["discussion_id"], created["id"])
        self.assertEqual(reply["number"], 2)
        self.assertEqual(reply["content"], "Reply through API")
        self.assertEqual(reply["user"]["username"], self.other_user.username)

    def test_discussion_lifecycle_endpoints_cover_update_pin_lock_hide_and_delete(self):
        discussion = self.create_discussion(title="Lifecycle topic", content="Original body", user=self.user)

        forbidden_response = self.client.post(
            f"/api/discussions/{discussion.id}/lock",
            **self.auth_header(self.other_user),
        )

        self.assertEqual(forbidden_response.status_code, 403, forbidden_response.content)

        update_response = self.client.patch(
            f"/api/discussions/{discussion.id}",
            data=json.dumps({
                "data": {
                    "attributes": {
                        "title": "Renamed topic",
                        "content": "Edited first post",
                    }
                }
            }),
            content_type="application/json",
            **self.auth_header(self.moderator),
        )
        pin_response = self.client.post(
            f"/api/discussions/{discussion.id}/pin",
            **self.auth_header(self.moderator),
        )
        lock_response = self.client.post(
            f"/api/discussions/{discussion.id}/lock",
            **self.auth_header(self.moderator),
        )
        hide_response = self.client.post(
            f"/api/discussions/{discussion.id}/hide",
            **self.auth_header(self.moderator),
        )

        self.assertEqual(update_response.status_code, 200, update_response.content)
        self.assertEqual(update_response.json()["title"], "Renamed topic")
        self.assertEqual(pin_response.status_code, 200, pin_response.content)
        self.assertTrue(pin_response.json()["is_sticky"])
        self.assertEqual(lock_response.status_code, 200, lock_response.content)
        self.assertTrue(lock_response.json()["is_locked"])
        self.assertEqual(hide_response.status_code, 200, hide_response.content)
        self.assertTrue(hide_response.json()["is_hidden"])

        hidden_list_response = self.client.get("/api/discussions/")
        moderator_list_response = self.client.get("/api/discussions/", **self.auth_header(self.moderator))

        self.assertEqual(hidden_list_response.status_code, 200, hidden_list_response.content)
        self.assertEqual(hidden_list_response.json()["data"], [])
        self.assertEqual(moderator_list_response.status_code, 200, moderator_list_response.content)
        self.assertEqual([item["id"] for item in moderator_list_response.json()["data"]], [discussion.id])

        restore_response = self.client.post(
            f"/api/discussions/{discussion.id}/hide",
            **self.auth_header(self.moderator),
        )
        delete_response = self.client.delete(
            f"/api/discussions/{discussion.id}",
            **self.auth_header(self.moderator),
        )
        deleted_show_response = self.client.get(f"/api/discussions/{discussion.id}", **self.auth_header(self.moderator))

        self.assertEqual(restore_response.status_code, 200, restore_response.content)
        self.assertFalse(restore_response.json()["is_hidden"])
        self.assertEqual(delete_response.status_code, 200, delete_response.content)
        self.assertEqual(deleted_show_response.status_code, 404, deleted_show_response.content)

    def test_approval_queue_approves_pending_discussion_and_rejects_pending_reply_over_http(self):
        pending_discussion_response = self.create_discussion_via_api(
            title="Pending discussion through API",
            content="Needs discussion approval",
            user=self.pending_author,
        )
        approved_discussion = self.create_discussion(
            title="Approved discussion for pending reply",
            content="Visible first post",
            user=self.admin,
        )
        pending_reply_response = self.client.post(
            f"/api/discussions/{approved_discussion.id}/posts",
            data=json.dumps({"content": "Needs reply approval"}),
            content_type="application/json",
            **self.auth_header(self.pending_replier),
        )

        self.assertEqual(pending_discussion_response.status_code, 200, pending_discussion_response.content)
        self.assertEqual(pending_discussion_response.json()["approval_status"], "pending")
        self.assertEqual(pending_reply_response.status_code, 200, pending_reply_response.content)
        self.assertEqual(pending_reply_response.json()["approval_status"], "pending")

        queue_response = self.client.get("/api/admin/approval-queue", **self.auth_header(self.admin))

        self.assertEqual(queue_response.status_code, 200, queue_response.content)
        queue_payload = queue_response.json()
        self.assertEqual(queue_payload["total"], 2)
        self.assertEqual(
            {(item["type"], item["id"]) for item in queue_payload["data"]},
            {
                ("discussion", pending_discussion_response.json()["id"]),
                ("post", pending_reply_response.json()["id"]),
            },
        )

        approve_response = self.client.post(
            f"/api/admin/approval-queue/discussion/{pending_discussion_response.json()['id']}/approve",
            data=json.dumps({"note": "Discussion approved"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )
        reject_response = self.client.post(
            f"/api/admin/approval-queue/post/{pending_reply_response.json()['id']}/reject",
            data=json.dumps({"note": "Reply rejected"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        self.assertEqual(approve_response.status_code, 200, approve_response.content)
        self.assertEqual(approve_response.json()["approval_status"], "approved")
        self.assertEqual(reject_response.status_code, 200, reject_response.content)
        self.assertEqual(reject_response.json()["approval_status"], "rejected")

        reader_discussion_response = self.client.get(
            f"/api/discussions/{pending_discussion_response.json()['id']}",
            **self.auth_header(self.other_user),
        )
        reader_rejected_post_response = self.client.get(
            f"/api/posts/{pending_reply_response.json()['id']}",
            **self.auth_header(self.user),
        )
        author_rejected_post_response = self.client.get(
            f"/api/posts/{pending_reply_response.json()['id']}",
            **self.auth_header(self.pending_replier),
        )

        self.assertEqual(reader_discussion_response.status_code, 200, reader_discussion_response.content)
        self.assertEqual(reader_discussion_response.json()["approval_status"], "approved")
        self.assertEqual(reader_rejected_post_response.status_code, 404, reader_rejected_post_response.content)
        self.assertEqual(author_rejected_post_response.status_code, 200, author_rejected_post_response.content)
        self.assertEqual(author_rejected_post_response.json()["approval_note"], "Reply rejected")

    def test_permission_moderator_can_pin_lock_patch_and_reply_to_locked_discussion(self):
        discussion = self.create_discussion(
            title="Permission moderator controls",
            content="Original body",
            user=self.user,
        )

        pin_response = self.client.post(
            f"/api/discussions/{discussion.id}/pin",
            **self.auth_header(self.permission_moderator),
        )
        lock_response = self.client.post(
            f"/api/discussions/{discussion.id}/lock",
            **self.auth_header(self.permission_moderator),
        )
        reply_response = self.client.post(
            f"/api/discussions/{discussion.id}/posts",
            data=json.dumps({"content": "Moderator reply while locked"}),
            content_type="application/json",
            **self.auth_header(self.permission_moderator),
        )

        self.assertEqual(pin_response.status_code, 200, pin_response.content)
        self.assertTrue(pin_response.json()["is_sticky"])
        self.assertEqual(lock_response.status_code, 200, lock_response.content)
        self.assertTrue(lock_response.json()["is_locked"])
        self.assertEqual(reply_response.status_code, 200, reply_response.content)
        self.assertEqual(reply_response.json()["content"], "Moderator reply while locked")

        update_response = self.client.patch(
            f"/api/discussions/{discussion.id}",
            data=json.dumps({
                "data": {
                    "attributes": {
                        "is_locked": False,
                        "is_sticky": False,
                    }
                }
            }),
            content_type="application/json",
            **self.auth_header(self.permission_moderator),
        )

        self.assertEqual(update_response.status_code, 200, update_response.content)
        self.assertFalse(update_response.json()["is_locked"])
        self.assertFalse(update_response.json()["is_sticky"])

    def test_approval_visibility_matrix_for_pending_and_rejected_discussions(self):
        pending_response = self.create_discussion_via_api(
            title="Pending visibility matrix",
            content="Pending matrix body",
            user=self.pending_author,
        )
        rejected_response = self.create_discussion_via_api(
            title="Rejected visibility matrix",
            content="Rejected matrix body",
            user=self.pending_author,
        )
        rejected_id = rejected_response.json()["id"]
        reject_response = self.client.post(
            f"/api/admin/approval-queue/discussion/{rejected_id}/reject",
            data=json.dumps({"note": "Rejected for visibility matrix"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        self.assertEqual(pending_response.status_code, 200, pending_response.content)
        self.assertEqual(rejected_response.status_code, 200, rejected_response.content)
        self.assertEqual(reject_response.status_code, 200, reject_response.content)

        pending_id = pending_response.json()["id"]
        cases = [
            ("guest", {}, False, False),
            ("registered", self.auth_header(self.other_user), False, False),
            ("author", self.auth_header(self.pending_author), True, True),
            ("moderator", self.auth_header(self.moderator), True, True),
            ("admin", self.auth_header(self.admin), True, True),
        ]

        for role, headers, can_see_pending, can_see_rejected in cases:
            with self.subTest(role=role):
                list_response = self.client.get("/api/discussions/", **headers)
                pending_detail_response = self.client.get(f"/api/discussions/{pending_id}", **headers)
                rejected_detail_response = self.client.get(f"/api/discussions/{rejected_id}", **headers)

                self.assertEqual(list_response.status_code, 200, list_response.content)
                visible_ids = {item["id"] for item in list_response.json()["data"]}
                self.assertEqual(pending_id in visible_ids, can_see_pending)
                self.assertEqual(rejected_id in visible_ids, can_see_rejected)
                self.assertEqual(pending_detail_response.status_code, 200 if can_see_pending else 404)
                self.assertEqual(rejected_detail_response.status_code, 200 if can_see_rejected else 404)

    def test_author_can_resubmit_rejected_discussion_over_http(self):
        rejected_response = self.create_discussion_via_api(
            title="Rejected discussion resubmit",
            content="Rejected discussion body",
            user=self.pending_author,
        )
        rejected_id = rejected_response.json()["id"]
        reject_response = self.client.post(
            f"/api/admin/approval-queue/discussion/{rejected_id}/reject",
            data=json.dumps({"note": "Add more context"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        self.assertEqual(rejected_response.status_code, 200, rejected_response.content)
        self.assertEqual(reject_response.status_code, 200, reject_response.content)
        self.assertEqual(reject_response.json()["approval_status"], "rejected")

        with self.captureOnCommitCallbacks(execute=True):
            resubmit_response = self.client.patch(
                f"/api/discussions/{rejected_id}",
                data=json.dumps({
                    "data": {
                        "attributes": {
                            "title": "Rejected discussion resubmitted",
                            "content": "Updated discussion body for review",
                        }
                    }
                }),
                content_type="application/json",
                **self.auth_header(self.pending_author),
            )
        author_detail_response = self.client.get(
            f"/api/discussions/{rejected_id}",
            **self.auth_header(self.pending_author),
        )
        reader_detail_response = self.client.get(
            f"/api/discussions/{rejected_id}",
            **self.auth_header(self.other_user),
        )
        author_stream_response = self.client.get(
            f"/api/discussions/{rejected_id}/posts",
            **self.auth_header(self.pending_author),
        )

        self.assertEqual(resubmit_response.status_code, 200, resubmit_response.content)
        self.assertEqual(resubmit_response.json()["approval_status"], "pending")
        self.assertEqual(resubmit_response.json()["approval_note"], "")
        self.assertEqual(resubmit_response.json()["title"], "Rejected discussion resubmitted")
        self.assertEqual(author_detail_response.status_code, 200, author_detail_response.content)
        self.assertEqual(author_detail_response.json()["first_post"]["content"], "Updated discussion body for review")
        self.assertEqual(author_detail_response.json()["first_post"]["approval_status"], "pending")
        self.assertEqual(reader_detail_response.status_code, 404, reader_detail_response.content)
        self.assertEqual(author_stream_response.status_code, 200, author_stream_response.content)
        self.assertTrue(
            any(item["type"] == "discussionResubmitted" for item in author_stream_response.json()["data"])
        )

    def test_approval_visibility_matrix_for_pending_and_rejected_posts(self):
        discussion = self.create_discussion(
            title="Post approval visibility matrix",
            content="Visible first post",
            user=self.admin,
        )
        pending_response = self.client.post(
            f"/api/discussions/{discussion.id}/posts",
            data=json.dumps({"content": "Pending post matrix"}),
            content_type="application/json",
            **self.auth_header(self.pending_replier),
        )
        rejected_response = self.client.post(
            f"/api/discussions/{discussion.id}/posts",
            data=json.dumps({"content": "Rejected post matrix"}),
            content_type="application/json",
            **self.auth_header(self.pending_replier),
        )
        rejected_id = rejected_response.json()["id"]
        reject_response = self.client.post(
            f"/api/admin/approval-queue/post/{rejected_id}/reject",
            data=json.dumps({"note": "Rejected post visibility matrix"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        self.assertEqual(pending_response.status_code, 200, pending_response.content)
        self.assertEqual(rejected_response.status_code, 200, rejected_response.content)
        self.assertEqual(reject_response.status_code, 200, reject_response.content)

        pending_id = pending_response.json()["id"]
        cases = [
            ("guest", {}, False, False),
            ("registered", self.auth_header(self.other_user), False, False),
            ("author", self.auth_header(self.pending_replier), True, True),
            ("moderator", self.auth_header(self.moderator), True, True),
            ("admin", self.auth_header(self.admin), True, True),
        ]

        for role, headers, can_see_pending, can_see_rejected in cases:
            with self.subTest(role=role):
                stream_response = self.client.get(f"/api/discussions/{discussion.id}/posts", **headers)
                pending_detail_response = self.client.get(f"/api/posts/{pending_id}", **headers)
                rejected_detail_response = self.client.get(f"/api/posts/{rejected_id}", **headers)

                self.assertEqual(stream_response.status_code, 200, stream_response.content)
                visible_post_ids = {item["id"] for item in stream_response.json()["data"]}
                self.assertEqual(pending_id in visible_post_ids, can_see_pending)
                self.assertEqual(rejected_id in visible_post_ids, can_see_rejected)
                self.assertEqual(pending_detail_response.status_code, 200 if can_see_pending else 404)
                self.assertEqual(rejected_detail_response.status_code, 200 if can_see_rejected else 404)

    def test_search_results_follow_discussion_and_post_visibility_matrix(self):
        from bias_ext_discussions.backend.models import Discussion
        from bias_ext_discussions.backend.services import DiscussionService
        from bias_ext_posts.backend.models import Post

        public_discussion = self.create_discussion(
            title="Search public vismatrix",
            content="Search public vismatrix opening",
            user=self.user,
        )
        public_reply = self.create_reply(
            public_discussion,
            content="Search public vismatrix reply",
            user=self.other_user,
        )
        hidden_discussion = self.create_discussion(
            title="Search hidden vismatrix",
            content="Search hidden vismatrix opening",
            user=self.user,
        )
        hidden_reply = self.create_reply(
            hidden_discussion,
            content="Search hidden vismatrix reply",
            user=self.user,
        )
        DiscussionService.set_hidden_state(hidden_discussion, self.moderator, True)
        private_discussion = self.create_discussion(
            title="Search private vismatrix",
            content="Search private vismatrix opening",
            user=self.user,
        )
        private_reply = self.create_reply(
            private_discussion,
            content="Search private vismatrix reply",
            user=self.user,
        )
        Discussion.objects.filter(id=private_discussion.id).update(is_private=True)
        Post.objects.filter(discussion_id=private_discussion.id).update(is_private=True)

        pending_discussion_response = self.create_discussion_via_api(
            title="Search pending vismatrix",
            content="Search pending vismatrix opening",
            user=self.pending_author,
        )
        rejected_discussion_response = self.create_discussion_via_api(
            title="Search rejected vismatrix",
            content="Search rejected vismatrix opening",
            user=self.pending_author,
        )
        rejected_discussion_id = rejected_discussion_response.json()["id"]
        reject_discussion_response = self.client.post(
            f"/api/admin/approval-queue/discussion/{rejected_discussion_id}/reject",
            data=json.dumps({"note": "Rejected search visibility"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        post_discussion = self.create_discussion(
            title="Search post approval vismatrix",
            content="Search post approval vismatrix visible opening",
            user=self.admin,
        )
        pending_post_response = self.client.post(
            f"/api/discussions/{post_discussion.id}/posts",
            data=json.dumps({"content": "Search pending post vismatrix"}),
            content_type="application/json",
            **self.auth_header(self.pending_replier),
        )
        rejected_post_response = self.client.post(
            f"/api/discussions/{post_discussion.id}/posts",
            data=json.dumps({"content": "Search rejected post vismatrix"}),
            content_type="application/json",
            **self.auth_header(self.pending_replier),
        )
        rejected_post_id = rejected_post_response.json()["id"]
        reject_post_response = self.client.post(
            f"/api/admin/approval-queue/post/{rejected_post_id}/reject",
            data=json.dumps({"note": "Rejected post search visibility"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        self.assertEqual(pending_discussion_response.status_code, 200, pending_discussion_response.content)
        self.assertEqual(rejected_discussion_response.status_code, 200, rejected_discussion_response.content)
        self.assertEqual(reject_discussion_response.status_code, 200, reject_discussion_response.content)
        self.assertEqual(pending_post_response.status_code, 200, pending_post_response.content)
        self.assertEqual(rejected_post_response.status_code, 200, rejected_post_response.content)
        self.assertEqual(reject_post_response.status_code, 200, reject_post_response.content)

        pending_discussion_id = pending_discussion_response.json()["id"]
        pending_discussion_first_post_id = Discussion.objects.get(id=pending_discussion_id).first_post_id
        rejected_discussion_first_post_id = Discussion.objects.get(id=rejected_discussion_id).first_post_id
        pending_post_id = pending_post_response.json()["id"]
        expected_discussions = {
            "guest": {public_discussion.id, post_discussion.id},
            "registered": {public_discussion.id, post_discussion.id},
            "discussion_author": {
                public_discussion.id,
                hidden_discussion.id,
                post_discussion.id,
            },
            "approval_author": {
                public_discussion.id,
                pending_discussion_id,
                rejected_discussion_id,
                post_discussion.id,
            },
            "post_author": {public_discussion.id, post_discussion.id},
            "moderator": {
                public_discussion.id,
                hidden_discussion.id,
                private_discussion.id,
                pending_discussion_id,
                rejected_discussion_id,
                post_discussion.id,
            },
            "admin": {
                public_discussion.id,
                hidden_discussion.id,
                private_discussion.id,
                pending_discussion_id,
                rejected_discussion_id,
                post_discussion.id,
            },
        }
        expected_posts = {
            "guest": {public_discussion.first_post_id, public_reply.id, post_discussion.first_post_id},
            "registered": {public_discussion.first_post_id, public_reply.id, post_discussion.first_post_id},
            "discussion_author": {
                public_discussion.first_post_id,
                public_reply.id,
                hidden_discussion.first_post_id,
                hidden_reply.id,
                post_discussion.first_post_id,
            },
            "approval_author": {
                public_discussion.first_post_id,
                public_reply.id,
                pending_discussion_first_post_id,
                rejected_discussion_first_post_id,
                post_discussion.first_post_id,
            },
            "post_author": {
                public_discussion.first_post_id,
                public_reply.id,
                post_discussion.first_post_id,
                pending_post_id,
                rejected_post_id,
            },
            "moderator": {
                public_discussion.first_post_id,
                public_reply.id,
                hidden_discussion.first_post_id,
                hidden_reply.id,
                private_discussion.first_post_id,
                private_reply.id,
                pending_discussion_first_post_id,
                rejected_discussion_first_post_id,
                post_discussion.first_post_id,
                pending_post_id,
                rejected_post_id,
            },
            "admin": {
                public_discussion.first_post_id,
                public_reply.id,
                hidden_discussion.first_post_id,
                hidden_reply.id,
                private_discussion.first_post_id,
                private_reply.id,
                pending_discussion_first_post_id,
                rejected_discussion_first_post_id,
                post_discussion.first_post_id,
                pending_post_id,
                rejected_post_id,
            },
        }
        cases = [
            ("guest", {}),
            ("registered", self.auth_header(self.other_user)),
            ("discussion_author", self.auth_header(self.user)),
            ("approval_author", self.auth_header(self.pending_author)),
            ("post_author", self.auth_header(self.pending_replier)),
            ("moderator", self.auth_header(self.moderator)),
            ("admin", self.auth_header(self.admin)),
        ]

        for role, headers in cases:
            with self.subTest(role=role):
                all_response = self.client.get("/api/search", {"q": "vismatrix", "type": "all"}, **headers)
                discussions_response = self.client.get(
                    "/api/search",
                    {"q": "vismatrix", "type": "discussions", "limit": 20},
                    **headers,
                )
                posts_response = self.client.get(
                    "/api/search",
                    {"q": "vismatrix", "type": "posts", "limit": 20},
                    **headers,
                )

                self.assertEqual(
                    self.search_result_ids(all_response, "discussions") - expected_discussions[role],
                    set(),
                    role,
                )
                self.assertEqual(
                    self.search_result_ids(discussions_response, "discussions"),
                    expected_discussions[role],
                    role,
                )
                self.assertEqual(
                    self.search_result_ids(all_response, "posts") - expected_posts[role],
                    set(),
                    role,
                )
                self.assertEqual(
                    self.search_result_ids(posts_response, "posts"),
                    expected_posts[role],
                    role,
                )

    def test_author_can_resubmit_rejected_post_over_http(self):
        discussion = self.create_discussion(
            title="Rejected post resubmit",
            content="Visible first post",
            user=self.admin,
        )
        rejected_response = self.client.post(
            f"/api/discussions/{discussion.id}/posts",
            data=json.dumps({"content": "Rejected post body"}),
            content_type="application/json",
            **self.auth_header(self.pending_replier),
        )
        rejected_id = rejected_response.json()["id"]
        reject_response = self.client.post(
            f"/api/admin/approval-queue/post/{rejected_id}/reject",
            data=json.dumps({"note": "Add more detail"}),
            content_type="application/json",
            **self.auth_header(self.admin),
        )

        self.assertEqual(rejected_response.status_code, 200, rejected_response.content)
        self.assertEqual(reject_response.status_code, 200, reject_response.content)
        self.assertEqual(reject_response.json()["approval_status"], "rejected")

        with self.captureOnCommitCallbacks(execute=True):
            resubmit_response = self.client.patch(
                f"/api/posts/{rejected_id}",
                data=json.dumps({"content": "Updated post body for review"}),
                content_type="application/json",
                **self.auth_header(self.pending_replier),
            )
        author_detail_response = self.client.get(
            f"/api/posts/{rejected_id}",
            **self.auth_header(self.pending_replier),
        )
        reader_detail_response = self.client.get(
            f"/api/posts/{rejected_id}",
            **self.auth_header(self.other_user),
        )
        author_stream_response = self.client.get(
            f"/api/discussions/{discussion.id}/posts",
            **self.auth_header(self.pending_replier),
        )

        self.assertEqual(resubmit_response.status_code, 200, resubmit_response.content)
        self.assertEqual(resubmit_response.json()["approval_status"], "pending")
        self.assertEqual(resubmit_response.json()["approval_note"], "")
        self.assertEqual(resubmit_response.json()["content"], "Updated post body for review")
        self.assertEqual(author_detail_response.status_code, 200, author_detail_response.content)
        self.assertEqual(author_detail_response.json()["approval_status"], "pending")
        self.assertEqual(reader_detail_response.status_code, 404, reader_detail_response.content)
        self.assertEqual(author_stream_response.status_code, 200, author_stream_response.content)
        self.assertTrue(
            any(item["type"] == "postResubmitted" for item in author_stream_response.json()["data"])
        )

    def test_post_lifecycle_endpoints_cover_update_hide_restore_and_delete(self):
        discussion = self.create_discussion(title="Post lifecycle", content="Original", user=self.user)
        post = self.create_reply(discussion, content="Reply to manage", user=self.other_user)

        forbidden_response = self.client.patch(
            f"/api/posts/{post.id}",
            data=json.dumps({"content": "Unauthorized edit"}),
            content_type="application/json",
            **self.auth_header(self.user),
        )

        self.assertEqual(forbidden_response.status_code, 403, forbidden_response.content)

        update_response = self.client.patch(
            f"/api/posts/{post.id}",
            data=json.dumps({"content": "Moderator edit"}),
            content_type="application/json",
            **self.auth_header(self.moderator),
        )
        hide_response = self.client.post(
            f"/api/posts/{post.id}/hide",
            **self.auth_header(self.moderator),
        )
        hidden_stream_response = self.client.get(f"/api/discussions/{discussion.id}/posts")
        moderator_stream_response = self.client.get(
            f"/api/discussions/{discussion.id}/posts",
            **self.auth_header(self.moderator),
        )

        self.assertEqual(update_response.status_code, 200, update_response.content)
        self.assertEqual(update_response.json()["content"], "Moderator edit")
        self.assertEqual(hide_response.status_code, 200, hide_response.content)
        self.assertTrue(hide_response.json()["is_hidden"])
        self.assertEqual(hidden_stream_response.status_code, 200, hidden_stream_response.content)
        self.assertEqual([item["number"] for item in hidden_stream_response.json()["data"]], [1])
        self.assertEqual(moderator_stream_response.status_code, 200, moderator_stream_response.content)
        self.assertEqual([item["number"] for item in moderator_stream_response.json()["data"]], [1, 2])

        restore_response = self.client.post(
            f"/api/posts/{post.id}/hide",
            **self.auth_header(self.moderator),
        )
        delete_response = self.client.delete(
            f"/api/posts/{post.id}",
            **self.auth_header(self.moderator),
        )
        deleted_show_response = self.client.get(f"/api/posts/{post.id}", **self.auth_header(self.moderator))

        self.assertEqual(restore_response.status_code, 200, restore_response.content)
        self.assertFalse(restore_response.json()["is_hidden"])
        self.assertEqual(delete_response.status_code, 200, delete_response.content)
        self.assertEqual(deleted_show_response.status_code, 404, deleted_show_response.content)
