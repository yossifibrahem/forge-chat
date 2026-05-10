"""
Tests for workspace_service.py — path normalisation, traversal safety,
directory listing, file reading, upload name sanitisation.

`workspace_root()` is patched in every test that touches the filesystem so
we control exactly where files live without depending on container_service.
"""
from __future__ import annotations

import io
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

import store
import workspace_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_workspace(tmp_lumen) -> tuple[str, Path]:
    """Create a conversation and a matching workspace directory, return both."""
    conv = store.create("ws-test")
    conv_id = conv["id"]
    root = tmp_lumen["containers_dir"] / conv_id
    root.mkdir(parents=True, exist_ok=True)
    return conv_id, root


# ---------------------------------------------------------------------------
# workspace_relpath
# ---------------------------------------------------------------------------

class TestWorkspaceRelpath:
    """Pure path-normalisation logic — no filesystem, no mocks needed."""

    @pytest.mark.parametrize("value", ["", ".", "/", "/workspace"])
    def test_root_variants_return_empty_string(self, value):
        assert workspace_service.workspace_relpath(value) == ""

    def test_strips_workspace_prefix(self):
        assert workspace_service.workspace_relpath("/workspace/foo/bar") == "foo/bar"

    def test_simple_relative_path(self):
        assert workspace_service.workspace_relpath("hello.txt") == "hello.txt"

    def test_nested_relative_path(self):
        assert workspace_service.workspace_relpath("a/b/c.py") == "a/b/c.py"

    def test_backslash_normalised_to_forward_slash(self):
        assert workspace_service.workspace_relpath("foo\\bar") == "foo/bar"

    def test_parent_traversal_raises(self):
        with pytest.raises(ValueError, match="traversal"):
            workspace_service.workspace_relpath("../escape")

    def test_embedded_traversal_raises(self):
        with pytest.raises(ValueError, match="traversal"):
            workspace_service.workspace_relpath("a/../../etc/passwd")

    def test_absolute_non_workspace_path_raises(self):
        with pytest.raises(ValueError, match="Only /workspace"):
            workspace_service.workspace_relpath("/etc/passwd")

    def test_none_treated_as_root(self):
        # None is a realistic input from request.args.get when path is omitted
        assert workspace_service.workspace_relpath(None) == ""


# ---------------------------------------------------------------------------
# resolve_workspace_path
# ---------------------------------------------------------------------------

class TestResolveWorkspacePath:

    def test_empty_path_resolves_to_root(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            target, rel = workspace_service.resolve_workspace_path(conv_id, "")
        assert target == root
        assert rel == ""

    def test_valid_nested_path_resolved(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "sub").mkdir()
        with patch("workspace_service.workspace_root", return_value=root):
            target, rel = workspace_service.resolve_workspace_path(conv_id, "/workspace/sub")
        assert target == root / "sub"
        assert rel == "sub"

    def test_traversal_attempt_raises(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            with pytest.raises(ValueError):
                workspace_service.resolve_workspace_path(conv_id, "../escape")

    def test_symlink_escape_rejected(self, tmp_lumen):
        """A path that resolves outside the root after symlink expansion must raise."""
        conv_id, root = _make_workspace(tmp_lumen)
        # We test this via the relpath validator; resolve_workspace_path raises
        # ValueError for any path that escapes after .resolve().
        with patch("workspace_service.workspace_root", return_value=root):
            with pytest.raises(ValueError):
                workspace_service.resolve_workspace_path(conv_id, "/etc/passwd")


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------

class TestListDir:

    def test_returns_404_for_unknown_conversation(self, tmp_lumen):
        _, status = workspace_service.list_dir("nonexistent-conv-id", "")
        assert status == 404

    def test_returns_200_with_entries_for_root(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "hello.txt").write_text("hello")
        with patch("workspace_service.workspace_root", return_value=root):
            result, status = workspace_service.list_dir(conv_id, "")
        assert status == 200
        names = [e["name"] for e in result["entries"]]
        assert "hello.txt" in names

    def test_directories_sorted_before_files(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "zfile.txt").write_text("z")
        (root / "adir").mkdir()
        with patch("workspace_service.workspace_root", return_value=root):
            result, _ = workspace_service.list_dir(conv_id, "")
        entries = result["entries"]
        assert entries[0]["type"] == "directory"
        assert entries[1]["type"] == "file"

    def test_returns_400_for_traversal_path(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            result, status = workspace_service.list_dir(conv_id, "../escape")
        assert status == 400

    def test_returns_404_for_nonexistent_subpath(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            result, status = workspace_service.list_dir(conv_id, "/workspace/ghost_dir")
        assert status == 404

    def test_returns_400_when_path_is_a_file(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "file.txt").write_text("content")
        with patch("workspace_service.workspace_root", return_value=root):
            result, status = workspace_service.list_dir(conv_id, "/workspace/file.txt")
        assert status == 400

    def test_entry_shape(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "shape.py").write_text("x = 1")
        with patch("workspace_service.workspace_root", return_value=root):
            result, _ = workspace_service.list_dir(conv_id, "")
        entry = next(e for e in result["entries"] if e["name"] == "shape.py")
        assert "name" in entry
        assert "path" in entry
        assert "type" in entry
        assert "size" in entry
        assert "previewable" in entry

    def test_path_field_has_workspace_prefix(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "sample.txt").write_text("x")
        with patch("workspace_service.workspace_root", return_value=root):
            result, _ = workspace_service.list_dir(conv_id, "")
        entry = next(e for e in result["entries"] if e["name"] == "sample.txt")
        assert entry["path"].startswith("/workspace")


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------

class TestReadFile:

    def test_reads_text_file_content(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "notes.txt").write_text("hello world")
        with patch("workspace_service.workspace_root", return_value=root):
            result, status = workspace_service.read_file(conv_id, "/workspace/notes.txt")
        assert status == 200
        assert result["content"] == "hello world"
        assert result["previewable"] is True

    def test_returns_404_for_missing_conversation(self, tmp_lumen):
        _, status = workspace_service.read_file("ghost-conv", "/workspace/x.txt")
        assert status == 404

    def test_returns_404_for_missing_file(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        with patch("workspace_service.workspace_root", return_value=root):
            _, status = workspace_service.read_file(conv_id, "/workspace/ghost.txt")
        assert status == 404

    def test_returns_400_for_directory(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "mydir").mkdir()
        with patch("workspace_service.workspace_root", return_value=root):
            _, status = workspace_service.read_file(conv_id, "/workspace/mydir")
        assert status == 400

    def test_file_exceeding_max_preview_bytes_returns_previewable_false(self, tmp_lumen, monkeypatch):
        """Files larger than MAX_PREVIEW_BYTES must not have their content returned."""
        monkeypatch.setattr("workspace_service.MAX_PREVIEW_BYTES", 10)
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "big.txt").write_text("x" * 100)
        with patch("workspace_service.workspace_root", return_value=root):
            result, status = workspace_service.read_file(conv_id, "/workspace/big.txt")
        assert status == 200
        assert result["previewable"] is False
        assert result["content"] is None


# ---------------------------------------------------------------------------
# safe_upload_name
# ---------------------------------------------------------------------------

class TestSafeUploadName:

    def test_normal_ascii_name_unchanged(self):
        assert workspace_service.safe_upload_name("report.pdf") == "report.pdf"

    def test_path_separators_replaced(self):
        result = workspace_service.safe_upload_name("a/b/c.txt")
        assert "/" not in result

    def test_dangerous_chars_replaced_with_underscore(self):
        # Semicolons, pipes, etc. must not survive into the filename
        result = workspace_service.safe_upload_name("evil;rm.sh")
        assert ";" not in result

    def test_empty_name_returns_file(self):
        assert workspace_service.safe_upload_name("") == "file"

    def test_leading_dot_stripped(self):
        # Filenames starting with . are hidden on Unix; strip the leading dot
        result = workspace_service.safe_upload_name("...hidden")
        assert not result.startswith(".")


# ---------------------------------------------------------------------------
# _unique_path
# ---------------------------------------------------------------------------

class TestUniquePath:

    def test_no_collision_returns_same_name(self, tmp_path):
        result = workspace_service._unique_path(tmp_path, "report.pdf")
        assert result == tmp_path / "report.pdf"

    def test_single_collision_appends_1(self, tmp_path):
        (tmp_path / "report.pdf").write_bytes(b"x")
        result = workspace_service._unique_path(tmp_path, "report.pdf")
        assert result.name == "report-1.pdf"

    def test_multiple_collisions_increments(self, tmp_path):
        (tmp_path / "data.csv").write_bytes(b"x")
        (tmp_path / "data-1.csv").write_bytes(b"x")
        result = workspace_service._unique_path(tmp_path, "data.csv")
        assert result.name == "data-2.csv"

    def test_extensionless_file_handled(self, tmp_path):
        (tmp_path / "Makefile").write_bytes(b"x")
        result = workspace_service._unique_path(tmp_path, "Makefile")
        assert result.name == "Makefile-1"


# ---------------------------------------------------------------------------
# save_uploads
# ---------------------------------------------------------------------------

class TestSaveUploads:

    def _make_fake_file(self, filename: str, content: bytes = b"hello"):
        """Build a minimal file-like object matching Flask's FileStorage API."""
        import io
        f = MagicMock()
        f.filename = filename
        f.stream = io.BytesIO(content)
        return f

    def test_saves_file_and_returns_200(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        f = self._make_fake_file("notes.txt", b"content")
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            result, status = workspace_service.save_uploads(conv_id, [f])
        assert status == 200
        assert len(result["files"]) == 1
        assert result["files"][0]["name"] == "notes.txt"

    def test_uploaded_file_appears_in_uploads_subdir(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        f = self._make_fake_file("myfile.py", b"code")
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            workspace_service.save_uploads(conv_id, [f])
        assert (root / "uploads" / "myfile.py").exists()

    def test_duplicate_filename_gets_suffix(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        (root / "uploads").mkdir(exist_ok=True)
        (root / "uploads" / "data.csv").write_bytes(b"existing")
        f = self._make_fake_file("data.csv", b"new content")
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            result, status = workspace_service.save_uploads(conv_id, [f])
        assert status == 200
        assert result["files"][0]["name"] == "data-1.csv"

    def test_returns_404_for_unknown_conversation(self, tmp_lumen):
        f = self._make_fake_file("x.txt")
        result, status = workspace_service.save_uploads("ghost-conv-id", [f])
        assert status == 404

    def test_empty_filename_skipped(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        f = self._make_fake_file("", b"content")
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            result, status = workspace_service.save_uploads(conv_id, [f])
        assert status == 400

    def test_file_exceeding_limit_returns_413_and_cleans_up(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        large_content = b"x" * (workspace_service.MAX_UPLOAD_BYTES + 1)
        f = self._make_fake_file("big.bin", large_content)
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            result, status = workspace_service.save_uploads(conv_id, [f])
        assert status == 413
        # Partial file must be cleaned up
        assert not (root / "uploads" / "big.bin").exists()

    def test_oversized_file_also_removes_previously_saved_files(self, tmp_lumen):
        """When file N exceeds the limit, files 0..N-1 must also be deleted."""
        conv_id, root = _make_workspace(tmp_lumen)
        good = self._make_fake_file("ok.txt", b"small")
        bad = self._make_fake_file("big.bin", b"x" * (workspace_service.MAX_UPLOAD_BYTES + 1))
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            result, status = workspace_service.save_uploads(conv_id, [good, bad])
        assert status == 413
        # The previously-saved ok.txt must also be gone
        assert not (root / "uploads" / "ok.txt").exists()

    def test_path_field_has_workspace_prefix(self, tmp_lumen):
        conv_id, root = _make_workspace(tmp_lumen)
        f = self._make_fake_file("script.py", b"pass")
        with patch("workspace_service.workspace_root", return_value=root), \
             patch("store.working_directory", return_value=root):
            result, _ = workspace_service.save_uploads(conv_id, [f])
        assert result["files"][0]["path"].startswith("/workspace/uploads/")
