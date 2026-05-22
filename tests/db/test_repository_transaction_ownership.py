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


def test_repositories_do_not_use_sync_db_calls():
    repository_dir = Path("db/repositories")
    offenders = []

    for path in repository_dir.glob("*.py"):
        if path.name == "__init__.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if "self.session.query(" in stripped:
                offenders.append(f"{path}:{lineno}: {stripped}")
            if "self.session.execute(" in stripped and "await self.session.execute(" not in stripped:
                offenders.append(f"{path}:{lineno}: {stripped}")
            if "self.session.flush()" in stripped and "await self.session.flush()" not in stripped:
                offenders.append(f"{path}:{lineno}: {stripped}")

    assert offenders == []
