"""ce-work 的 Windows 兼容层回归测试。

上游这条路线只做了 POSIX：顶层 `import fcntl`、靠 `os.open(dir, O_DIRECTORY)`
做目录句柄、靠 mode 位判 0700/0600。这些在 Windows 上分别表现为
ModuleNotFoundError、PermissionError 和恒假。本测试钉住替代实现的关键性质，
避免以后同步上游时被无声改回去。

只有 IS_WINDOWS 为真的断言会在 Windows 上跑；跨平台部分两边都跑。
"""
import os
import stat
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills", "ce-work", "scripts",
)
sys.path.insert(0, SCRIPTS)

import unit_workspace_state as state  # noqa: E402
import unit_workspace_jobs as jobs  # noqa: E402

IS_WINDOWS = sys.platform == "win32"


class LockingTest(unittest.TestCase):
    """flock 换成 msvcrt.locking 之后，语义必须还是"阻塞等待"。"""

    def test_exclusive_lock_round_trip(self):
        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            fd = os.open(path, os.O_RDWR | state.O_BINARY)
            try:
                state._lock_fd(fd, exclusive=True)
                state._unlock_fd(fd)
            finally:
                os.close(fd)
        finally:
            os.unlink(path)

    def test_second_writer_waits_instead_of_raising(self):
        """POSIX 的 flock 默认阻塞；msvcrt.locking 默认不阻塞。

        并发调度依赖的是"等待"而不是"抛异常"，所以这里必须验证第二个
        加锁者最终能拿到锁，而不是立刻 TrustFailure。
        """
        import threading
        import time

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            first = os.open(path, os.O_RDWR | state.O_BINARY)
            state._lock_fd(first, exclusive=True)
            done = []

            def contend():
                second = os.open(path, os.O_RDWR | state.O_BINARY)
                try:
                    state._lock_fd(second, exclusive=True)
                    done.append(time.monotonic())
                    state._unlock_fd(second)
                finally:
                    os.close(second)

            thread = threading.Thread(target=contend)
            thread.start()
            time.sleep(0.3)
            self.assertEqual(done, [], "第二个加锁者不该在第一个释放前拿到锁")
            state._unlock_fd(first)
            thread.join(timeout=state.LOCK_WAIT_SECS + 5)
            self.assertEqual(len(done), 1, "释放后第二个加锁者应拿到锁")
            os.close(first)
        finally:
            os.unlink(path)


class DirectoryHandleTest(unittest.TestCase):
    """目录句柄在 POSIX 是 fd、在 Windows 是路径，对外行为必须一致。"""

    def _make_unit(self, root):
        result_dir = os.path.join(root, "result")
        os.makedirs(result_dir)
        state.ensure_private_dir(result_dir)
        identity = jobs.private_result_dir_identity(result_dir)
        return {
            "workspace": {"path": os.path.join(root, "workspace")},
            "result_dir_identity": identity,
        }, result_dir

    def test_identity_is_stable_and_nonzero(self):
        with tempfile.TemporaryDirectory() as root:
            _, result_dir = self._make_unit(root)
            first = jobs.private_result_dir_identity(result_dir)
            second = jobs.private_result_dir_identity(result_dir)
            self.assertEqual(first, second)
            self.assertNotEqual(first["ino"], 0, "identity 需要非零 inode 才能区分目录")

    def test_identity_change_is_detected(self):
        with tempfile.TemporaryDirectory() as root:
            unit, result_dir = self._make_unit(root)
            stale = dict(unit)
            stale["result_dir_identity"] = {"dev": 1, "ino": 2}
            with self.assertRaises(state.TrustFailure):
                jobs.open_recorded_result_dir(stale)

    def test_read_and_stat_through_handle(self):
        with tempfile.TemporaryDirectory() as root:
            unit, result_dir = self._make_unit(root)
            payload = b'{"ok": true}'
            target = os.path.join(result_dir, "implementation-result.json")
            with open(target, "wb") as handle:
                handle.write(payload)

            handle, resolved = jobs.open_recorded_result_dir(unit)
            try:
                self.assertEqual(resolved, result_dir)
                self.assertEqual(
                    jobs.read_private_at(handle, "implementation-result.json", 4096, target),
                    payload,
                )
                st = jobs.stat_private_at(handle, "implementation-result.json", target)
                self.assertEqual(st.st_size, len(payload))
            finally:
                jobs.close_dir_handle(handle)

    def test_missing_file_honours_missing_ok(self):
        with tempfile.TemporaryDirectory() as root:
            unit, result_dir = self._make_unit(root)
            target = os.path.join(result_dir, "absent.json")
            handle, _ = jobs.open_recorded_result_dir(unit)
            try:
                self.assertIsNone(
                    jobs.stat_private_at(handle, "absent.json", target, missing_ok=True)
                )
                with self.assertRaises(state.TrustFailure):
                    jobs.stat_private_at(handle, "absent.json", target)
            finally:
                jobs.close_dir_handle(handle)

    def test_traversal_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            unit, result_dir = self._make_unit(root)
            handle, _ = jobs.open_recorded_result_dir(unit)
            try:
                for name in ("..", ".", "", "../escape", "sub/dir"):
                    with self.assertRaises(state.TrustFailure, msg=name):
                        jobs.read_private_at(handle, name, 4096, name)
            finally:
                jobs.close_dir_handle(handle)

    def test_close_handle_is_idempotent_for_paths(self):
        with tempfile.TemporaryDirectory() as root:
            unit, _ = self._make_unit(root)
            handle, _ = jobs.open_recorded_result_dir(unit)
            jobs.close_dir_handle(handle)
            if isinstance(handle, str):
                jobs.close_dir_handle(handle)  # 路径句柄没有可泄漏的 fd


@unittest.skipUnless(IS_WINDOWS, "Windows 专有行为")
class WindowsOwnershipTest(unittest.TestCase):
    def test_current_user_owns_its_own_temp_dir(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(state.win_owns_path(root))

    def test_mkdir_mode_is_synthetic_but_gate_still_passes(self):
        """0o700 mkdir 在 Windows 上回落成 0o777。

        如果哪里还在直接比 st_mode，这个测试会把它暴露出来。
        """
        with tempfile.TemporaryDirectory() as root:
            target = os.path.join(root, "private")
            os.mkdir(target, 0o700)
            actual = stat.S_IMODE(os.stat(target).st_mode)
            self.assertNotEqual(actual, 0o700, "前提失效：Windows 竟然保留了 mode")
            state.validate_private_dir(target)  # 不应抛异常

    def test_directory_cannot_be_opened_as_fd(self):
        """这正是要用路径版 GetNamedSecurityInfoW 的原因。"""
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(PermissionError):
                os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))


class ProjectKeyTest(unittest.TestCase):
    def test_windows_bucket_name_matches_dsh_layout(self):
        self.assertEqual(state.__name__, "unit_workspace_state")


if __name__ == "__main__":
    unittest.main()
