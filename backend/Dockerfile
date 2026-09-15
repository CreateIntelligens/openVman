# syntax=docker/dockerfile:1.7
#
# The toolchain, parser stack (docling / firecrawl / pdf-inspector) and runtime
# apt packages live in Dockerfile.base, published as openvman-backend-base.
# This file is deliberately single-stage: installing requirements.txt straight
# into the base image's venv adds only the delta as a layer, whereas a
# builder→runner copy of /opt/venv would re-emit the whole multi-GB venv on
# every build and defeat the point of the base image.
ARG BASE_IMAGE=tbdavid2019/openvman-backend-base:latest
FROM ${BASE_IMAGE}

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install -r requirements.txt

COPY app /app/app

COPY docker /app/docker

RUN sed -i 's/\r$//' /app/docker/start-backend-container.sh \
    && chmod +x /app/docker/start-backend-container.sh

EXPOSE 8200

ENTRYPOINT ["/app/docker/start-backend-container.sh"]
