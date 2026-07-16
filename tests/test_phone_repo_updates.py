import inspect
import unittest
from unittest.mock import patch

import phone_bridge_server as bridge


class RepoUpdateTrackerTests(unittest.TestCase):
    def _repo_state(self, **overrides):
        payload = {
            "available": True,
            "repo_root": "C:/repo",
            "branch": "main",
            "head_sha": "a" * 40,
            "short_sha": "aaaaaaa",
            "subject": "Ilk commit",
            "signature": f"main:{'a' * 40}",
            "commit_ts": 100,
            "checked_at": 100,
            "tracked_dirty": False,
            "untracked_dirty": False,
            "dirty": False,
            "upstream_ref": "origin/main",
            "upstream_sha": "b" * 40,
            "upstream_short_sha": "bbbbbbb",
            "upstream_subject": "Remote commit",
            "ahead_count": 0,
            "behind_count": 1,
            "update_available": True,
            "can_update": True,
            "remote_error": "",
            "error": "",
        }
        payload.update(overrides)
        return payload

    def test_read_repo_state_returns_unavailable_when_git_lookup_fails(self):
        with patch.object(bridge, "_run_git_command", side_effect=RuntimeError("git missing")):
            state = bridge._read_repo_state()

        self.assertFalse(state["available"])
        self.assertIn("git missing", state["error"])

    def _fake_git(self, *, counts="0\t27", tracked=""):
        mapping = {
            ("rev-parse", "--show-toplevel"): "C:/repo",
            ("rev-parse", "HEAD"): "a" * 40,
            ("rev-parse", "--short=7", "HEAD"): "aaaaaaa",
            ("branch", "--show-current"): "main",
            ("status", "--porcelain", "--untracked-files=no"): tracked,
            ("status", "--porcelain", "--untracked-files=normal"): tracked,
            ("log", "-1", "--format=%ct%n%s", "HEAD"): "100\nIlk commit",
            ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"): "origin/main",
            ("rev-parse", "@{upstream}"): "b" * 40,
            ("rev-parse", "--short=7", "@{upstream}"): "bbbbbbb",
            ("rev-list", "--left-right", "--count", "HEAD...@{upstream}"): counts,
            ("log", "-1", "--format=%s", "@{upstream}"): "Remote commit",
        }

        def run(repo_root, *args, **kwargs):
            return mapping[args]

        return run

    def test_read_repo_state_allows_auto_update_when_clean_and_behind(self):
        with patch.object(bridge, "_run_git_command", side_effect=self._fake_git(counts="0\t27")):
            state = bridge._read_repo_state()

        self.assertTrue(state["update_available"])
        self.assertTrue(state["can_update"])
        self.assertEqual(state["behind_count"], 27)

    def test_read_repo_state_disables_auto_update_when_branch_diverged(self):
        with patch.object(bridge, "_run_git_command", side_effect=self._fake_git(counts="1\t27")):
            state = bridge._read_repo_state()

        self.assertTrue(state["update_available"])
        self.assertEqual(state["ahead_count"], 1)
        self.assertFalse(state["can_update"])

    def test_read_repo_state_disables_auto_update_when_tracked_dirty(self):
        with patch.object(
            bridge,
            "_run_git_command",
            side_effect=self._fake_git(counts="0\t27", tracked=" M phone_bridge_server.py"),
        ):
            state = bridge._read_repo_state()

        self.assertTrue(state["update_available"])
        self.assertTrue(state["tracked_dirty"])
        self.assertFalse(state["can_update"])

    def test_repo_tracker_increments_update_seq_when_head_changes(self):
        first = self._repo_state()
        second = self._repo_state(
            head_sha="b" * 40,
            short_sha="bbbbbbb",
            subject="Yeni commit",
            signature=f"main:{'b' * 40}",
            commit_ts=200,
            checked_at=200,
            upstream_sha="c" * 40,
            upstream_short_sha="ccccccc",
            upstream_subject="Yeni remote",
        )

        with patch.object(bridge, "_read_repo_state", side_effect=[first, second]), patch.object(
            bridge.time,
            "time",
            side_effect=[150],
        ):
            tracker = bridge.RepoUpdateTracker(check_interval=30)
            initial = tracker.snapshot(force=True)
            refreshed = tracker.snapshot(force=True)

        self.assertEqual(initial["update_seq"], 0)
        self.assertEqual(initial["changed_at"], 100)
        self.assertEqual(refreshed["update_seq"], 1)
        self.assertEqual(refreshed["changed_at"], 150)
        self.assertEqual(refreshed["short_sha"], "bbbbbbb")

    def test_apply_update_runs_ff_only_pull_and_refreshes_state(self):
        tracker = bridge.RepoUpdateTracker(check_interval=30)
        current = self._repo_state()
        updated = self._repo_state(
            head_sha="d" * 40,
            short_sha="ddddddd",
            subject="Pulled commit",
            signature=f"main:{'d' * 40}",
            commit_ts=220,
            checked_at=220,
            upstream_sha="d" * 40,
            upstream_short_sha="ddddddd",
            upstream_subject="Pulled commit",
            behind_count=0,
            update_available=False,
            can_update=False,
        )
        snapshots = [dict(current), dict(updated)]

        def fake_refresh(*, force_fetch=False):
            tracker._snapshot = snapshots.pop(0)

        with patch.object(tracker, "_refresh_locked", side_effect=fake_refresh), patch.object(
            bridge,
            "_run_git_command",
            return_value="Updating aaaaaaa..ddddddd",
        ) as run_git:
            result = tracker.apply_update()

        run_git.assert_called_once_with(
            tracker._repo_root,
            "pull",
            "--ff-only",
            timeout=20,
        )
        self.assertTrue(result["updated"])
        self.assertEqual(result["repo_state"]["short_sha"], "ddddddd")
        self.assertFalse(result["repo_state"]["update_available"])

    def test_repo_tracker_retains_last_good_state_on_transient_failure(self):
        good = self._repo_state()
        failure = {"available": False, "checked_at": 300, "error": "index.lock tutuluyor"}

        with patch.object(bridge, "_read_repo_state", side_effect=[good, dict(failure)]):
            tracker = bridge.RepoUpdateTracker(check_interval=30)
            tracker.snapshot(force=True)
            retained = tracker.snapshot(force=True)

        self.assertTrue(retained["available"])
        self.assertTrue(retained["update_available"])
        self.assertEqual(retained["checked_at"], 300)
        self.assertIn("index.lock", retained["error"])

    def test_repo_tracker_reports_unavailable_after_repeated_failures(self):
        good = self._repo_state()
        failure = {"available": False, "checked_at": 300, "error": "git missing"}
        reads = [good] + [dict(failure) for _ in range(bridge.RepoUpdateTracker.MAX_TRANSIENT_READ_FAILURES)]

        with patch.object(bridge, "_read_repo_state", side_effect=reads):
            tracker = bridge.RepoUpdateTracker(check_interval=30)
            snapshots = [tracker.snapshot(force=True) for _ in reads]

        self.assertTrue(all(item["available"] for item in snapshots[:-1]))
        self.assertFalse(snapshots[-1]["available"])
        self.assertIn("git missing", snapshots[-1]["error"])

    def test_apply_update_rejects_tracked_dirty_repo(self):
        tracker = bridge.RepoUpdateTracker(check_interval=30)

        def fake_refresh(*, force_fetch=False):
            tracker._snapshot = self._repo_state(tracked_dirty=True, dirty=True, can_update=False)

        with patch.object(tracker, "_refresh_locked", side_effect=fake_refresh):
            with self.assertRaises(RuntimeError) as ctx:
                tracker.apply_update()

        self.assertIn("Yerel takip edilen degisiklikler", str(ctx.exception))

    def test_phone_bridge_routes_expose_repo_state_for_pwa_notifications(self):
        get_source = inspect.getsource(bridge.PhoneBridgeHandler.do_GET)
        post_source = inspect.getsource(bridge.PhoneBridgeHandler.do_POST)

        self.assertIn('payload["repo_state"] = self.server.repo_tracker.snapshot()', get_source)
        self.assertIn("repo_state = self.server.repo_tracker.snapshot()", post_source)
        self.assertIn('screenshot_payload["repo_state"] = repo_state', post_source)
        self.assertIn('if payload.get("screenshot", True) is False:', post_source)
        self.assertIn("if skip_screenshot:", post_source)
        self.assertIn('"repo_state": repo_state,', post_source)
        self.assertIn('if route == "/api/repo-update":', post_source)
        self.assertIn('payload.get("confirm") is not True', post_source)


if __name__ == "__main__":
    unittest.main()
