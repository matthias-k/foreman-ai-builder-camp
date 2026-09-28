import pathlib

import pytest
import r3
import yaml

from foreman.r3_extension import Repository


@pytest.fixture
def repo(tmp_path):
    """A temp r3 repo: a <- b <- c, plus d depending on both b and c (a diamond)."""
    repo_path = tmp_path / "repo"
    r3.Repository.init(str(repo_path))
    r3repo = r3.Repository(str(repo_path))

    def make(name, deps=()):
        job_dir = tmp_path / name
        job_dir.mkdir()
        (job_dir / "run.py").write_text("print('hi')\n")
        if deps:
            (job_dir / "r3.yaml").write_text(
                yaml.safe_dump(
                    {"dependencies": [
                        {"job": uuid, "destination": f"dep_{i}"}
                        for i, uuid in enumerate(deps)
                    ]}
                )
            )
        (job_dir / "metadata.yaml").write_text(
            yaml.safe_dump({"path": f"test/{name}", "tags": [name]})
        )
        job = r3repo.commit(r3.Job(str(job_dir)))
        # Write a done marker so foreman resolves status offline (no SLURM needed).
        output = pathlib.Path(job.path, "output")
        output.mkdir(exist_ok=True)
        (output / "done").write_text("completed")
        return job.id

    ids = {}
    ids["a"] = make("a")
    ids["b"] = make("b", [ids["a"]])
    ids["c"] = make("c", [ids["b"]])
    ids["d"] = make("d", [ids["b"], ids["c"]])
    return Repository(r3repo), ids
