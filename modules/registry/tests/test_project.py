from agent_registry.project import project_key


def test_project_key_basename_fallback(tmp_path):
    d = tmp_path / "lindris"
    d.mkdir()
    assert project_key(str(d)) == "lindris"


def test_project_key_prefers_git_root(tmp_path):
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    nested = root / "packages" / "api"
    nested.mkdir(parents=True)
    assert project_key(str(nested)) == "repo"


def test_project_key_missing_dir_uses_basename(tmp_path):
    # path does not exist on disk
    missing = tmp_path / "projects" / "lindris"
    assert project_key(str(missing)) == "lindris"

def test_project_key_not_swallowed_by_home_git(tmp_path, monkeypatch):
    # Even if home has .git, ~/projects/foo must stay "foo"
    from agent_registry import project as project_mod
    monkeypatch.setattr(project_mod.Path, "home", classmethod(lambda cls: tmp_path))
    (tmp_path / ".git").mkdir()
    projects = tmp_path / "projects"
    projects.mkdir()
    missing = projects / "lindris"
    assert project_key(str(missing)) == "lindris"
