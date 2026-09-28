ARG PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.14-slim@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2
FROM ${PYTHON_BASE_IMAGE}

ARG JUPYTERLAB_VERSION=4.4.10
ARG UVICORN_VERSION=0.37.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    JUPYTER_CONFIG_DIR=/tmp/jupyter \
    HOME=/tmp/workspace

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
      "jupyterlab==${JUPYTERLAB_VERSION}" \
      "uvicorn[standard]==${UVICORN_VERSION}"

RUN addgroup --system workspace && adduser --system --ingroup workspace workspace \
    && mkdir -p /workspace /tmp/jupyter /tmp/workspace \
    && chown -R workspace:workspace /workspace /tmp/jupyter /tmp/workspace

COPY contract_server.py /workspace/contract_server.py
RUN chown -R workspace:workspace /workspace

USER workspace
WORKDIR /workspace
EXPOSE 8080
CMD ["uvicorn", "contract_server:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
