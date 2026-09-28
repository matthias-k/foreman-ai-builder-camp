def _paths(jobs):
    return sorted(job.virtual_path for job in jobs)


def test_find_dependents_direct(repo):
    repository, ids = repo
    a = repository.get(ids["a"])
    assert _paths(repository.find_dependents(a)) == ["test/b"]


def test_find_dependents_recursive(repo):
    repository, ids = repo
    a = repository.get(ids["a"])
    paths = [j.virtual_path for j in repository.find_dependents(a, recursive=True)]
    assert paths == ["test/b", "test/c", "test/d"]


def test_find_dependents_multiple_direct(repo):
    repository, ids = repo
    b = repository.get(ids["b"])
    paths = [j.virtual_path for j in repository.find_dependents(b)]
    assert paths == ["test/c", "test/d"]


def test_find_dependents_leaf_empty(repo):
    repository, ids = repo
    d = repository.get(ids["d"])
    assert repository.find_dependents(d) == []


def test_find_dependencies_direct(repo):
    repository, ids = repo
    d = repository.get(ids["d"])
    assert _paths(repository.find_dependencies(d)) == ["test/b", "test/c"]


def test_find_dependencies_recursive_dedupes(repo):
    repository, ids = repo
    d = repository.get(ids["d"])
    # d -> b, c ; b -> a ; c -> b : recursive set is {a, b, c}, b listed once
    assert _paths(repository.find_dependencies(d, recursive=True)) == [
        "test/a", "test/b", "test/c",
    ]
