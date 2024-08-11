"""Job search blueprint."""
import json

from flask import Blueprint, render_template, request

from foreman.r3_extension import Repository


search = Blueprint("search", __name__, url_prefix="/search")


@search.route("/search", methods=["GET"])
def index():
    return render_template("search/search.html.jinja")


@search.route("/search", methods=["POST"])
def search_post():
    query_str = request.form["query"]
    try:
        query = json.loads(query_str)
    except json.JSONDecodeError as error:
        return f"Invalid query: {query_str}, {error}"

    repository = Repository.from_environment()
    jobs = sorted(repository.find(query), key=lambda job: job.timestamp, reverse=True)

    return render_template("search/search_results.html.jinja", jobs=jobs)
