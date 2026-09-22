<<<<<<< HEAD
ARG PYTHON_BASE_IMAGE=python:3.14-slim
FROM ${PYTHON_BASE_IMAGE} AS runtime

ARG DEBIAN_MIRROR=http://deb.debian.org/debian
ARG DEBIAN_SECURITY_MIRROR=http://deb.debian.org/debian-security
=======
FROM python:3.12-slim

ARG DEBIAN_MIRROR_URL=https://mirrors.tuna.tsinghua.edu.cn/debian
>>>>>>> 095cb95dbd191b982308a1c90a37a23c8e42cc47

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

<<<<<<< HEAD
RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${DEBIAN_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian|${DEBIAN_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install --no-install-recommends -y default-libmysqlclient-dev build-essential pkg-config curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements/base.txt /tmp/requirements.txt
RUN python -m pip install -r /tmp/requirements.txt

COPY education_experiment_platform /app
RUN addgroup --system app && adduser --system --ingroup app app \
    && chown -R app:app /app
USER app

EXPOSE 8000
CMD ["uvicorn", "education_experiment_platform.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
=======
WORKDIR /app

COPY . /app
RUN sed -i "s|http://deb.debian.org/debian|${DEBIAN_MIRROR_URL}|g" /etc/apt/sources.list.d/debian.sources \
    && sed -i "s|http://deb.debian.org/debian-security|${DEBIAN_MIRROR_URL}-security|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        pkg-config \
        default-libmysqlclient-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir .

EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
>>>>>>> 095cb95dbd191b982308a1c90a37a23c8e42cc47
