"""Repository configuration helper and plugin packaging."""

from __future__ import annotations

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import configure_repo  # noqa: E402
import package_plugin  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SETTINGS_TEMPLATE = """---
name: Kotoba
custom_fields:
  - keyname: data_base_url
    field_type: url
    name: Data endpoint
    default: {endpoint}
"""


def write_settings(tmp_path: Path, endpoint: str) -> Path:
    path = tmp_path / "settings.yml"
    path.write_text(SETTINGS_TEMPLATE.format(endpoint=endpoint), encoding="utf-8")
    return path


def run_configure(args: list[str]) -> int:
    argv = sys.argv
    sys.argv = ["configure_repo.py", *args]
    try:
        return configure_repo.main()
    finally:
        sys.argv = argv


class TestConfigureRepo:
    def test_replaces_the_placeholder(self, tmp_path, capsys):
        path = write_settings(tmp_path, configure_repo.PLACEHOLDER_URL)
        assert run_configure(
            ["--owner", "simonjgreen", "--repo", "trmnl-japanese-vocab",
             "--settings", str(path)]
        ) == 0
        text = path.read_text(encoding="utf-8")
        assert "GITHUB_OWNER" not in text
        assert "https://simonjgreen.github.io/trmnl-japanese-vocab/api/v1" in text

    def test_is_idempotent(self, tmp_path):
        path = write_settings(tmp_path, configure_repo.PLACEHOLDER_URL)
        args = ["--owner", "me", "--repo", "mine", "--settings", str(path)]
        run_configure(args)
        first = path.read_text(encoding="utf-8")
        assert run_configure(args) == 0
        assert path.read_text(encoding="utf-8") == first

    def test_refuses_to_overwrite_a_custom_endpoint(self, tmp_path):
        path = write_settings(tmp_path, "https://my.own.host/api/v1")
        assert run_configure(
            ["--owner", "me", "--repo", "mine", "--settings", str(path)]
        ) == 1
        assert "my.own.host" in path.read_text(encoding="utf-8")

    def test_force_overwrites_a_custom_endpoint(self, tmp_path):
        path = write_settings(tmp_path, "https://my.own.host/api/v1")
        assert run_configure(
            ["--owner", "me", "--repo", "mine", "--settings", str(path), "--force"]
        ) == 0
        assert "https://me.github.io/mine/api/v1" in path.read_text(encoding="utf-8")

    @pytest.mark.parametrize("owner", ["", "-bad", "bad-", "a" * 40, "has space", "a/b"])
    def test_rejects_invalid_owners(self, tmp_path, owner):
        path = write_settings(tmp_path, configure_repo.PLACEHOLDER_URL)
        # `--owner=X` form: a leading hyphen would otherwise be parsed as a flag.
        assert run_configure(
            [f"--owner={owner}", "--repo", "mine", "--settings", str(path)]
        ) == 1

    @pytest.mark.parametrize("repo", ["", "has space", "a" * 101, "a/b"])
    def test_rejects_invalid_repos(self, tmp_path, repo):
        path = write_settings(tmp_path, configure_repo.PLACEHOLDER_URL)
        assert run_configure(
            ["--owner", "me", f"--repo={repo}", "--settings", str(path)]
        ) == 1

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("git@github.com:me/mine.git", ("me", "mine")),
            ("https://github.com/me/mine.git", ("me", "mine")),
            ("https://github.com/me/mine", ("me", "mine")),
            ("ssh://git@github.com/me/mine.git", ("me", "mine")),
        ],
    )
    def test_detects_owner_and_repo_from_a_remote(self, tmp_path, url, expected, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout=url + "\n", stderr="")

        monkeypatch.setattr(configure_repo.subprocess, "run", fake_run)
        assert configure_repo.detect_from_git() == expected

    def test_returns_none_for_a_non_github_remote(self, monkeypatch):
        def fake_run(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="https://gitlab.com/a/b\n", stderr="")

        monkeypatch.setattr(configure_repo.subprocess, "run", fake_run)
        assert configure_repo.detect_from_git() is None


class TestPackagePlugin:
    def test_produces_a_flat_archive(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        for name in ("settings.yml", "full.liquid", "shared.liquid",
                     "half_horizontal.liquid", "half_vertical.liquid", "quadrant.liquid"):
            (src / name).write_text("x", encoding="utf-8")
        output = tmp_path / "out" / "plugin.zip"

        argv = sys.argv
        sys.argv = ["package_plugin.py", "--src", str(src), "--output", str(output)]
        try:
            assert package_plugin.main() == 0
        finally:
            sys.argv = argv

        with zipfile.ZipFile(output) as archive:
            names = archive.namelist()
        assert sorted(names) == sorted(
            ["settings.yml", "full.liquid", "shared.liquid",
             "half_horizontal.liquid", "half_vertical.liquid", "quadrant.liquid"]
        )
        assert all("/" not in name for name in names), "archive must be flat"

    def test_fails_without_required_files(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        argv = sys.argv
        sys.argv = ["package_plugin.py", "--src", str(src),
                    "--output", str(tmp_path / "p.zip")]
        try:
            assert package_plugin.main() == 1
        finally:
            sys.argv = argv


class TestShippedSettings:
    """Checks against the real src/settings.yml."""

    @pytest.fixture
    def settings(self):
        return yaml.safe_load((REPO / "src" / "settings.yml").read_text(encoding="utf-8"))

    def test_description_fits_trmnls_limit(self, settings):
        assert len(settings["description"]) <= 35

    def test_a_slot_is_no_longer_than_a_render_interval(self, settings):
        """Consecutive renders must always land in different slots.

        The card is chosen as `floor(now / slot) % deck_size`. If a slot were
        longer than the render interval, two renders in a row could fall
        inside the same slot and draw the same card — the screen would look
        stuck. Slot <= interval guarantees the index advances every time.

        TRMNL rounds refresh_interval up to its own allowed values (10
        becomes 15), so this is checked against whatever is actually
        committed rather than what was asked for.
        """
        import yaml as _yaml

        build = _yaml.safe_load(
            (REPO / "config" / "build.yml").read_text(encoding="utf-8")
        )
        slot_seconds = build["deck"]["slot_seconds"]
        interval_seconds = settings["refresh_interval"] * 60
        assert settings["strategy"] == "polling"
        assert slot_seconds <= interval_seconds, (
            f"deck.slot_seconds ({slot_seconds}) exceeds the render interval "
            f"({interval_seconds}s); cards would repeat across refreshes"
        )

    def test_polling_url_uses_level_and_local_date(self, settings):
        url = settings["polling_url"]
        assert "{{ data_base_url }}" in url
        assert "{{ jlpt_level }}" in url
        assert "trmnl.user.utc_offset" in url
        assert '"%Y-%m-%d"' in url

    def test_all_expected_fields_exist_with_the_right_defaults(self, settings):
        fields = {f["keyname"]: f for f in settings["custom_fields"]}
        assert set(fields) == {
            "jlpt_level", "show_example_translation",
            "show_rotation_progress", "data_base_url",
        }
        assert fields["jlpt_level"]["default"] == "n5"
        assert fields["show_example_translation"]["default"] is False
        assert fields["show_rotation_progress"]["default"] is False
        assert fields["data_base_url"]["group"] == "Advanced"

    def test_all_five_levels_are_offered(self, settings):
        fields = {f["keyname"]: f for f in settings["custom_fields"]}
        options = fields["jlpt_level"]["options"]
        values = [list(o.values())[0] for o in options]
        assert values == ["n5", "n4", "n3", "n2", "n1"]

    def test_data_endpoint_has_no_trailing_slash(self, settings):
        fields = {f["keyname"]: f for f in settings["custom_fields"]}
        assert not fields["data_base_url"]["default"].endswith("/")

    def test_no_secrets_are_committed(self, settings):
        """No credential values. Naming the env var in a comment is fine."""
        text = (REPO / "src" / "settings.yml").read_text(encoding="utf-8")
        assert not re.search(r"user_[A-Za-z0-9]{12,}", text), "TRMNL API key committed"
        assert not re.search(
            r"(?i)(api[_-]?key|token|secret)\s*:\s*\S", text
        ), "credential-shaped setting committed"
        # Headers are where a key would most plausibly be smuggled in.
        assert settings.get("polling_headers", "") == ""

    def test_plugin_id_is_committed(self, settings):
        """Without an id, CI would create a new plugin on every deploy."""
        assert isinstance(settings.get("id"), int), (
            "src/settings.yml needs the plugin id from the first `trmnlp push`"
        )
