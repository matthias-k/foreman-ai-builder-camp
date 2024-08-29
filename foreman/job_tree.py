"""Job tree blueprint.

Jobs in R3 can be assigned a virtual path. The job tree uses allows exploring jobs
using this virtual directory structure.
"""
from collections import defaultdict

from flask import Blueprint, make_response, redirect, render_template, request, url_for

from foreman.r3_extension import Repository

job_tree = Blueprint("job_tree", __name__, url_prefix='/tree')


@job_tree.route("/view", defaults={"path": ""}, strict_slashes=False)
@job_tree.route("/view/<path:path>")
def view(path):
    repository = Repository.from_environment()

    if len(path) > 0 and path[-1] != "/":
        path += "/"

    all_jobs = repository.find({ "path": { "$glob": path + "*" } })

    directories = dict()
    jobs = defaultdict(list)

    for job in all_jobs:
        job_path = job.virtual_path[len(path):]
        if "/" in job_path:
            name = job_path.split("/")[0]
            directories[name] = path + name
        else:
            jobs[job_path].append(job)

    for name in jobs.keys():
        jobs[name] = sorted(jobs[name], key=lambda job: job.timestamp, reverse=True)

    jobs = { key: value for key, value in sorted(jobs.items()) }
    directories = { key: value for key, value in sorted(directories.items()) }

    breadcrumbs = dict()
    if path != "":
        full_path = ""
        for name in path.split("/"):
            if name == "":
                continue
            full_path += name + "/"
            breadcrumbs[name] = full_path

    if request.headers.get("Hx-Target", "root") == "root":
        return render_template(
            "job_tree/view.html.jinja",
            breadcrumbs=breadcrumbs,
            jobs=jobs,
            directories=directories,
            path=path,
        )
    else:
        return render_template(
            "job_tree/contents.html.jinja",
            breadcrumbs=breadcrumbs,
            jobs=jobs,
            directories=directories,
            path=path,
        )


@job_tree.route("/directory_tree")
def directory_tree():
    repository = Repository.from_environment()
    jobs = repository.find({ "path": { "$glob": "*/*" } })
    directories = sorted(job.virtual_path.rsplit("/", 1)[0] for job in jobs)

    directory_tree = dict()
    for directory in directories:
        parts = directory.split("/")
        current = directory_tree
        for part in parts:
            if part not in current:
                current[part] = {
                    "path": "/".join(parts[:parts.index(part) + 1]),
                    "children": {},
                }
            current = current[part]["children"]

    return render_template(
        "job_tree/sidebar_directory_tree.html.jinja",
        directory_tree=directory_tree,
    )


@job_tree.route("/view_revisions/<path:path>")
def view_revisions(path: str):
    repository = Repository.from_environment()
    jobs = repository.find({ "path": path })
    jobs = sorted(jobs, key=lambda revision: revision.timestamp, reverse=True)

    breadcrumbs = dict()
    if path != "":
        full_path = ""
        for name in path.split("/"):
            if name == "":
                continue
            full_path += name + "/"
            breadcrumbs[name] = full_path

    return render_template(
        "job_tree/view_revisions.html.jinja", breadcrumbs=breadcrumbs, revisions=jobs
    )


@job_tree.route("/move_form/<path:path>")
def move_form(path):
    return render_template("job_tree/move_form.html.jinja", path=path)


@job_tree.route("/move", methods=["POST"])
def move():
    source = request.form["source"]
    destination = request.form["destination"]
    merge_confirmed = request.form.get("merge_confirmed", False)

    repository = Repository.from_environment()

    affected_jobs = []

    jobs = repository.find({ "path": source })
    for job in jobs:
        job.r3_job.metadata["path"] = destination
        affected_jobs.append(job)

    jobs = repository.find({ "path": { "$glob": f"{source}/*" } })
    for job in jobs:
        job.r3_job.metadata["path"] = f"{destination}/{job.virtual_path[len(source) + 1:]}"  # noqa: E501
        affected_jobs.append(job)

    redirect_to = "" if "/" not in source else source.rsplit("/", 1)[0]

    if not merge_confirmed:
        conflicts = set()
        for job in affected_jobs:
            if repository.find({ "path": job.r3_job.metadata["path"] }):
                conflicts.add(job.r3_job.metadata["path"])

        if len(conflicts) > 0 and not merge_confirmed:
            response = make_response(render_template(
                "job_tree/move_confirm_merge.html.jinja",
                source=source,
                destination=destination,
                conflicts=sorted(conflicts),
                redirect_to=redirect_to,
            ))
            response.headers["HX-Retarget"] = "#modal"
            return response

    for job in affected_jobs:
        job.r3_job.save_metadata()
        repository.r3_repository._index.remove(job.r3_job)
        repository.r3_repository._index.add(job.r3_job)

    response = make_response("")
    response.headers["HX-Redirect"] = url_for("job_tree.view", path=redirect_to)
    return response
