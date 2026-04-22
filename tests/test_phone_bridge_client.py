import unittest
from unittest.mock import patch

import phone_bridge_client


class PhoneBridgeClientTests(unittest.TestCase):
    def test_create_phone_link_reads_admin_token_at_call_time(self):
        with patch.object(
            phone_bridge_client, "get_shared_admin_token", return_value="fresh-token"
        ), patch.object(
            phone_bridge_client,
            "_request_json",
            return_value={"status": "ok", "session": {"token": "phone-link"}},
        ) as request_json:
            session = phone_bridge_client.create_phone_link(minutes=0)

        self.assertEqual(session, {"token": "phone-link"})
        self.assertEqual(
            request_json.call_args.kwargs["headers"],
            {"X-AgentCockpit-Admin": "fresh-token"},
        )


if __name__ == "__main__":
    unittest.main()
