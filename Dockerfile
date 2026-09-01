# easy-tdx 容器镜像（配合 docker-compose.yml 使用）
FROM python:3.12-slim

WORKDIR /app

# 先装依赖层（利用构建缓存）
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .[web,warehouse]

# 装本地源码（开发机构建；发布镜像可直接从 PyPI 装 easy-tdx）
COPY . .
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000
CMD ["easy-tdx", "serve", "--host", "0.0.0.0", "--port", "8000", "--no-open-browser"]
