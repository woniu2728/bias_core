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
        from bias_ext_tags.backend.models import Tag

        self.tag = Tag.objects.create(
            name="General",
            slug="general",
            position=1,
            is_primary=True,
        )

    def auth_header(self, user=None):
        token = RefreshToken.for_user(user or self.user).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

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
