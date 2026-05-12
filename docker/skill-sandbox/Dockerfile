# Skill script sandbox image.
# Build example:
#   docker build -f docker/skill-sandbox/Dockerfile -t st49-skill-sandbox:latest .
# Then set SANDBOX_BASE_IMAGE=st49-skill-sandbox:latest for the backend container.
ARG PYTHON_IMAGE=python:3.12-bookworm
FROM ${PYTHON_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Common CLI/runtime dependencies for Skill scripts.
# Keep this list conservative: broadly useful, non-interactive, and safe for a shared sandbox base.
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    ca-certificates \
    coreutils \
    curl \
    dnsutils \
    file \
    findutils \
    gawk \
    git \
    gnupg \
    grep \
    gzip \
    jq \
    less \
    make \
    nano \
    openssh-client \
    patch \
    procps \
    ripgrep \
    sed \
    tar \
    tini \
    tree \
    unzip \
    vim-tiny \
    wget \
    xz-utils \
    zip \
    nodejs \
    npm \
    ffmpeg \
    imagemagick \
    poppler-utils \
    tesseract-ocr \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Frequently used Python libraries for file, data, web, image and document-processing skills.
RUN python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install \
    beautifulsoup4 \
    httpx \
    lxml \
    markdown \
    matplotlib \
    numpy \
    openpyxl \
    pandas \
    pillow \
    pydantic \
    pymupdf \
    python-docx \
    python-pptx \
    pyyaml \
    requests \
    rich \
    tqdm

# Basic JS tooling used by browser/file-processing skills.
RUN npm install -g yarn pnpm typescript tsx

WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/bin/sh", "-lc", "while true; do sleep 3600; done"]
