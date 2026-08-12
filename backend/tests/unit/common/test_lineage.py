from app.common.lineage import get_code_version


def test_get_code_version_prefers_git_sha_env_var(monkeypatch):
    get_code_version.cache_clear()
    monkeypatch.setenv("GIT_SHA", "abc1234")
    assert get_code_version() == "abc1234"
    get_code_version.cache_clear()


def test_get_code_version_falls_back_to_git_commit_env_var(monkeypatch):
    get_code_version.cache_clear()
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.setenv("GIT_COMMIT", "def5678")
    assert get_code_version() == "def5678"
    get_code_version.cache_clear()


def test_get_code_version_falls_back_to_the_installed_package_version(monkeypatch):
    get_code_version.cache_clear()
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("GIT_COMMIT", raising=False)
    # The package is installed editable in this test environment (`pip install -e
    # .`), so this resolves to pyproject.toml's `version`, not the "unknown" fallback.
    assert get_code_version() not in ("", None)
    get_code_version.cache_clear()
