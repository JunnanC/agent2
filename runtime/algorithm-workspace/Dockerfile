ARG PYTHON_BASE_IMAGE=m.daocloud.io/docker.io/library/python:3.14-slim
FROM ${PYTHON_BASE_IMAGE}

ARG DEBIAN_MIRROR=https://mirrors.aliyun.com/debian
ARG DEBIAN_SECURITY_MIRROR=https://mirrors.aliyun.com/debian-security

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp/workspace

RUN sed -i \
    -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
    -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
    /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "uvicorn[standard]==0.37.0"

RUN addgroup --system workspace \
    && adduser --system --ingroup workspace workspace \
    && mkdir -p /opt/runtime /workspace /tmp/workspace \
    && chown -R workspace:workspace /opt/runtime /workspace /tmp/workspace

COPY contract_server.py /opt/runtime/contract_server.py
RUN chown workspace:workspace /opt/runtime/contract_server.py

USER workspace
WORKDIR /opt/runtime
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "contract_server:app", "--host", "0.0.0.0", "--port", "8080"]
