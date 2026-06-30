from tests.common import *
from django.contrib.auth import get_user_model


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
