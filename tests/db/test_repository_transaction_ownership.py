from pathlib import Path


def test_repositories_do_not_own_transactions_with_sync_commits():
    repository_dir = Path("db/repositories")
    offenders = []

    for path in repository_dir.glob("*.py"):
        if path.name == "__init__.py":
            continue
        text = path.read_text()
        if "self.session.commit()" in text:
            offenders.append(str(path))

    assert offenders == []
