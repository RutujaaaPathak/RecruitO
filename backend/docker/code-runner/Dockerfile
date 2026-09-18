# RecruitO sandbox image for the coding-test code executor
# (backend/app/services/code_executor.py).
#
# Candidate code (Python / Java / C++) runs inside this image with a hardened
# container: --network none, --read-only, --user 1000, CPU/memory/PID/fsize
# limits and a /tmp tmpfs for compiler scratch space.
#
#   Build:  docker build -t recruito-code-runner:latest backend/docker/code-runner
#
# The image has no default ENTRYPOINT: the executor always passes an explicit
# `sh -c` command so nothing untrusted is executed implicitly at startup.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    TMPDIR=/tmp \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      g++ \
      openjdk-17-jdk-headless \
      python3 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 --shell /usr/sbin/nologin code \
 && mkdir -p /workspace /scratch \
 && chown code:code /scratch

# Everything the executor mounts is provided at container creation time:
#   /workspace  (read-only) candidate source + test input
#   /scratch    (writable)  program output and compile artifacts
#   /tmp        (tmpfs)     compiler scratch space
USER 1000
WORKDIR /home/code