"""
Job list blueprint.

The job list shows all jobs in the repository in a single list.
"""
from flask import Blueprint, render_template

from foreman.r3_extension import Repository

job_list = Blueprint("job_list", __name__, url_prefix="/list")


@job_list.route("/")
def view():
    repository = Repository.from_environment()
    jobs = sorted(repository.jobs(), key=lambda job: job.timestamp, reverse=True)
    return render_template("job_list/view.html.jinja", jobs=jobs)
