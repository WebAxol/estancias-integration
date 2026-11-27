#!/bin/sh
# Runs inside the `tests` container of docker-compose.ci.yml.
set -eu
cd /app
python -m pytest -ra -p no:cacheprovider --junitxml=/tmp/results.xml "$@"
# A missing variable or database would make the tests skip and pass.
python /ci/check_no_skips.py /tmp/results.xml
