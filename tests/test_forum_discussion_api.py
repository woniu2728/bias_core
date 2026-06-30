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
        self.moderator = get_user_model().objects.create_user(
            username="forum-moderator",
            email="forum-moderator@example.com",
            password="password123",
            is_email_confirmed=True,
            is_staff=True,
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
        )

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

    def test_authenticated_user_can_create_discussion_and_reply(self):
        create_response = self.client.post(
            "/api/discussions/",
            data=json.dumps({
                "data": {
                    "attributes": {
                        "title": "Created through API",
                        "content": "Created body",
                    },
                    "relationships": {
                        "tags": {
                            "data": [
                                {"type": "tag", "id": str(self.tag.id)},
                            ],
                        },
                    },
                }
            }),
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
