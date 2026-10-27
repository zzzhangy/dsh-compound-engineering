#!/usr/bin/env python3
"""dsh_session.py 的测试。

重点覆盖两处容易出错的地方：
1. zstd 多帧容器的边界扫描（少算一次 RLE 字节就会满盘解不出来）；
2. projectKey 编码必须与 dsh 自己逐字一致，否则读不到本项目的历史会话。

生成测试用 zstd 文件时用 `compression.zstd.compress` 逐段压缩再拼接，
精确复现 dsh 每次 append 追加一帧的写法。
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "ce-compound", "scripts", "session-history")
sys.path.insert(0, SCRIPTS)

import dsh_session  # noqa: E402


class ProjectKeyTest(unittest.TestCase):
    def test_windows_drive_path(self):
        self.assertEqual(dsh_session.project_key("E:\\project\\jpt"), "--E-project-jpt--")

    def test_posix_path(self):
        self.assertEqual(dsh_session.project_key("/home/me/repo"), "--home-me-repo--")

    def test_separator_run_collapses(self):
        # 连续分隔符（含盘符冒号加反斜杠）只出一个短横线
        self.assertEqual(dsh_session.project_key("C:\\Users\\me"), "--C-Users-me--")

    def test_special_characters_are_escaped(self):
        self.assertEqual(dsh_session.project_key("/tmp/my repo"), "--tmp-my~0020repo--")

    def test_empty_path_is_rejected(self):
        with self.assertRaises(ValueError):
            dsh_session.project_key("")


class SessionFileTest(unittest.TestCase):
    def test_recognises_generation_suffixes(self):
        for name in ("session.jsonl.zstd", "session.v3.jsonl.zstd", "session.v4.jsonl.zstd"):
            self.assertTrue(dsh_session.is_session_file(os.path.join("a", "b", name)), name)

    def test_rejects_plain_jsonl_and_other_names(self):
        self.assertFalse(dsh_session.is_session_file("history.jsonl"))
        self.assertFalse(dsh_session.is_session_file("session.jsonl"))
        self.assertFalse(dsh_session.is_session_file("notes.txt"))


@unittest.skipUnless(dsh_session.available(), "需要 Python 3.14+ 的 compression.zstd")
class FrameScanTest(unittest.TestCase):
    def test_single_frame_round_trip(self):
        data = dsh_session._zstd.compress(b'{"type":"session"}\n')
        frames, torn = dsh_session.scan_frames(data)
        self.assertEqual(torn, None)
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0], (0, len(data)))

    def test_concatenated_frames_are_all_found(self):
        # dsh 每 append 一次追加一帧；只解第一帧会静默丢掉整个后缀。
        parts = [b'{"a":1}\n', b'{"b":2}\n', b'{"c":3}\n']
        blob = b"".join(dsh_session._zstd.compress(part) for part in parts)
        frames, torn = dsh_session.scan_frames(blob)
        self.assertEqual(torn, None)
        self.assertEqual(len(frames), 3)
        decoded = b"".join(dsh_session._zstd.decompress(blob[s:e]) for s, e in frames)
        self.assertEqual(decoded, b"".join(parts))

    def test_truncated_tail_is_reported_not_thrown(self):
        blob = dsh_session._zstd.compress(b'{"a":1}\n')
        torn_blob = blob + blob[: len(blob) // 2]
        frames, torn = dsh_session.scan_frames(torn_blob)
        self.assertEqual(len(frames), 1)
        self.assertEqual(torn, len(blob))

    def test_garbage_is_reported_as_torn(self):
        frames, torn = dsh_session.scan_frames(b"not a zstd frame at all")
        self.assertEqual(frames, [])
        self.assertEqual(torn, 0)

    def test_empty_file(self):
        self.assertEqual(dsh_session.scan_frames(b""), ([], None))


@unittest.skipUnless(dsh_session.available(), "需要 Python 3.14+ 的 compression.zstd")
class ReadLinesTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.directory = tempfile.mkdtemp()
        self.path = os.path.join(self.directory, "session.v4.jsonl.zstd")

    def tearDown(self):
        import shutil

        shutil.rmtree(self.directory, ignore_errors=True)

    def _write_frames(self, parts):
        with open(self.path, "wb") as handle:
            for part in parts:
                handle.write(dsh_session._zstd.compress(part))

    def test_reads_every_appended_frame(self):
        self._write_frames([b'{"n":1}\n{"n":2}\n', b'{"n":3}\n'])
        self.assertEqual(dsh_session.read_lines(self.path), ['{"n":1}', '{"n":2}', '{"n":3}'])

    def test_max_lines_truncates(self):
        self._write_frames([b'{"n":1}\n', b'{"n":2}\n'])
        self.assertEqual(dsh_session.read_lines(self.path, max_lines=1), ['{"n":1}'])

    def test_read_objects_skips_bad_lines(self):
        self._write_frames([b'{"n":1}\nnot json\n{"n":2}\n'])
        self.assertEqual(dsh_session.read_objects(self.path), [{"n": 1}, {"n": 2}])

    def test_session_header_returns_first_session_record(self):
        self._write_frames([b'{"type":"user/message"}\n{"type":"session","id":"s1"}\n'])
        header = dsh_session.session_header(dsh_session.read_objects(self.path))
        self.assertEqual(header, {"type": "session", "id": "s1"})


class TimestampTest(unittest.TestCase):
    def test_epoch_millis_to_iso(self):
        self.assertEqual(dsh_session.iso_from_millis(0), "1970-01-01T00:00:00+00:00")

    def test_non_numeric_returns_empty(self):
        for value in (None, "", "123", {}):
            self.assertEqual(dsh_session.iso_from_millis(value), "", repr(value))


class ContentTextTest(unittest.TestCase):
    def test_only_text_blocks_are_returned(self):
        blocks = [
            {"type": "text", "text": "人说的话"},
            {"type": "reasoning", "text": "内心独白"},
            {"type": "tool-call", "name": "read"},
            {"type": "image", "data": "..."},
        ]
        self.assertEqual(dsh_session.content_text(blocks), ["人说的话"])

    def test_bare_string_is_accepted(self):
        self.assertEqual(dsh_session.content_text("纯文本"), ["纯文本"])

    def test_non_list_returns_empty(self):
        self.assertEqual(dsh_session.content_text(None), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
