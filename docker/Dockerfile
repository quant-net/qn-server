FROM python:3.11-slim AS build

RUN apt-get update && \
    apt-get install --yes --no-install-recommends \
    openssh-client \ 
    git \
    && apt-get clean

# Update pip
RUN pip install --upgrade pip setuptools wheel

# Pre-install some known dependency constraints to avoid backtracking
RUN pip install "pluggy<1.0.0" "readme-renderer>=42.0" "docutils>=0.21.2"

ARG BRANCH

RUN echo "Dockerfile BRANCH value is: ${BRANCH}"


RUN git clone --single-branch --branch ${BRANCH} https://github.com/quant-net/qn-mq qn-mq && \
    cd qn-mq && pip install --no-cache-dir .

RUN git clone --single-branch --branch ${BRANCH} https://github.com/quant-net/qn-plugins qn-plugins

RUN git clone --single-branch --branch ${BRANCH} https://github.com/quant-net/qn-server qn-server


# Install Python dependencies with pip cache mount
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install ./qn-mq && \
    pip install ./qn-server