#!/usr/bin/env python3

import logging

logging.basicConfig(
    level=logging.INFO, 
    format="%(asctime)s.%(msecs)03d %(levelname)s %(module)s - %(funcName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logging.info("Importing libraries")

from aiohttp import web
from argparse import ArgumentParser
from aiohttp_basicauth import BasicAuthMiddleware
from mako.lookup import TemplateLookup

from jobstate import *
from nodestate import *
from serverutil import simple_cache

import logging
import stat
from pathlib import Path

parser = ArgumentParser()
parser.add_argument("--port", type=int, default=51024)
args = parser.parse_args()

class PasswordDefinitionException(Exception):
    pass

def get_auth_secret() -> str:
    password_file = Path("./password.txt").absolute()

    if not password_file.exists():
        raise PasswordDefinitionException(
            "Password file not found, please see README.md!"
        )

    password_permissions = stat.S_IMODE(os.lstat(password_file).st_mode)

    non_owner_mask = 0b000_111_111
    if (password_permissions & non_owner_mask) != 0:
        raise PasswordDefinitionException(
            "Password file has incorrect permissions, please see README.md!"
        )
    
    with open(password_file, "r+") as f:
        auth_secret = f.read().split("\n")[0]

    logging.info(f"Successfully read credentials from {password_file}")

    return auth_secret

auth_secret = get_auth_secret()

lookup = TemplateLookup(
    directories=["html/"],
    default_filters=["h"]
)

def get_state_rank(state: str):
    return {
        "CANCELLED": 0,
        "FAILED": 1,
        "TIMEOUT": 2,
        "OUT_OF_MEMORY": 3,
        "RUNNING": 10,
        "COMPLETED": 20
    }.get(state, -1)

def make_job_sort_key():
    def job_sorter(job: JobState):
        return (
            -job.is_mine(),
            get_state_rank(job.job_state),
            job.partition,
            -job.job_id
        )

    return job_sorter

async def list_jobs(request: web.Request):
    jobs = (await simple_cache(query_jobs)).values()

    jobs = sorted(jobs, key=make_job_sort_key())

    if "partition" in request.query:
        jobs = filter(lambda job: job.partition == request.query["partition"], jobs)

    if "state" in request.query:
        jobs = filter(lambda job: job.job_state in request.query["state"], jobs)

    if "node" in request.query:
        jobs = filter(lambda job: job.nodes is not None and request.query["node"] in job.nodes, jobs)

    jobs = list(jobs)

    table_template = lookup.get_template("joblist.html")

    response = web.Response(content_type="text/html", body=table_template.render(jobs=jobs))
    response.enable_compression()
    return response

async def list_nodes(request: web.Request):
    nodes, jobs = await asyncio.gather(
        simple_cache(query_nodes),
        simple_cache(query_jobs)
    )

    nodes = list(nodes.values())

    jobs = jobs.values()
    jobs = sorted(jobs, key=make_job_sort_key())

    table_template = lookup.get_template("nodelist.html")

    response = web.Response(content_type="text/html", body=table_template.render(nodes=nodes, jobs=jobs))
    response.enable_compression()
    return response

# async def read_log_file(request: web.Request):
#     job_id = request.query["jobId"]
#     job = await query_job(job_id)
#     return web.FileResponse(headers={"Content-Type": "text/plain"}, path=job.stdout_path)

auth = BasicAuthMiddleware(username="swatch", password=auth_secret)
app = web.Application(middlewares=[auth])

app.add_routes([
    web.get("/", list_nodes),
    web.get("/nodes", list_nodes),
    web.get("/jobs", list_jobs),

    web.static("/vendor/", "vendor/"),
    web.static("/assets/", "assets/")
])

logging.info(f"Server running and listening on localhost:{args.port}")
logging.info(f"If you followed the README, go to: http://localhost:51024")
web.run_app(app, host="localhost", port=args.port, print=False)