FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SUMO_HOME=/opt/sumo \
    PATH=/opt/sumo/bin:$PATH \
    PYTHONPATH=/opt/sumo/tools

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      libfontconfig1 \
      libgl1 \
      libglu1-mesa \
      libgomp1 \
      libice6 \
      libsm6 \
      libx11-6 \
      libxext6 \
      libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# The official wheels contain SUMO, TraCI, tools, and runtime libraries. Direct
# URLs and PyPI-published SHA-256 digests keep this supply-chain step auditable.
# The smaller manylinux2014 build is sufficient for the headless Phase 1 path;
# the required SUMO and netconvert binaries are verified in the next layer.
RUN python -m pip install --no-cache-dir \
      "https://files.pythonhosted.org/packages/73/9d/1c4e7bb11044372fdeafad36a753b2c919b328d280820a14e1ac74f18290/sumo_data-1.27.1-py3-none-any.whl#sha256=2e547fd20558e07d6004d576eeaf85f4aa061efb4a9bab7675233726364fba61" \
    && python -m pip install --no-cache-dir --no-deps \
      "https://files.pythonhosted.org/packages/b2/00/0b88a931c50e277a46ee6110216ef8ca299b064cca82d1fc481d4155754a/eclipse_sumo-1.27.1-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl#sha256=97abddcb7395c25538f22a272ef67ca77c8a625d3eec6010eed5b62dfac011f3" \
    && SUMO_PACKAGE_DIR="$(python -c 'import sumo; print(sumo.SUMO_HOME)')" \
    && ln -s "${SUMO_PACKAGE_DIR}" /opt/sumo

RUN sumo --version \
    && netconvert --version

# Large scientific wheels are isolated so a transient proxy failure cannot
# invalidate all successfully downloaded dependencies in the same Docker layer.
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/b8/a9/6e73d68500f80773f65f0654ea932019d6694329a0eb0ed0533de38df376/numpy-2.5.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl#sha256=59fda5e192b570217ec2580c96f00e9a7e12ef6866a900eb089b62c1a32545ca"
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/dd/aa/1b939f6c67ed68635bb538e6752d3dacc02f66535182e939a89581a44e9c/scipy-1.18.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl#sha256=1f55797419e16e7f30cf88ffb3113ce0467f00cfe3f70d5c281730b21769bfc2"
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/e5/63/cd7d615331b328e287d8233ba9fdf191a9c2d11b6af0c7a59cfcec23de68/pandas-2.3.3-cp312-cp312-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl#sha256=b3d11d2fda7eb164ef27ffc14b4fcab16a80e1ce67e9f57e19ec0afaf715ba89"
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/6c/c2/63fdda36c56437eeb44aaf9493c8bcd62ce230ab1598924fc626ffbfa943/scikit_learn-1.9.0-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl#sha256=056c92bb67ad4c28463c2f2653d9701449201e7e7a9e94e321be0f71c4fef2b8"
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/7c/b1/b83136c6e510593d9b0c759ba5384337bc4ad82d19fda675adc4b2703c84/psycopg_binary-3.3.4-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl#sha256=e7510c37550f91a187e3660a8cc50d4b760f8c3b8b2f89ebc5698cd2c7f2c85d"
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/b8/be/212882c450bba74fc8d7d35cbd57e4af84792f0a56194819d98106b075af/pyproj-3.7.2-cp312-cp312-manylinux_2_28_x86_64.whl#sha256=1edc34266c0c23ced85f95a1ee8b47c9035eae6aca5b6b340327250e8e281630"
RUN python -m pip install --no-cache-dir --no-deps \
    "https://files.pythonhosted.org/packages/e5/6d/b53b99a9f2766d095985947a5782f1702cabb129a34f7a802d7197af832f/tzdata-2026.3-py2.py3-none-any.whl#sha256=dc096730c87af6cab1b171c9d532be840741ff5d459015e7f6947bd7d7e54931"

WORKDIR /workspace
COPY pyproject.toml README.md ./
# Keep third-party dependencies independent from source layers so an ordinary
# code edit does not redownload the full Python dependency graph.
RUN python -m pip install --no-cache-dir --retries 10 --timeout 120 \
      "alembic>=1.14,<2" \
      "fastapi>=0.116,<1" \
      "httpx>=0.28,<1" \
      "jsonschema>=4.23,<5" \
      "networkx>=3.4,<4" \
      "numpy>=2.1,<3" \
      "openpyxl>=3.1,<4" \
      "paho-mqtt>=2.1,<3" \
      "pandas>=2.2,<3" \
      "prometheus-client>=0.21,<1" \
      "psycopg[binary]>=3.2,<4" \
      "psutil>=6.1,<8" \
      "pyproj>=3.7,<4" \
      "pydantic>=2.10,<3" \
      "pydantic-settings>=2.7,<3" \
      "pyyaml>=6.0,<7" \
      "scikit-learn>=1.6,<2" \
      "sqlalchemy>=2.0,<3" \
      "structlog>=24.4,<26" \
      "uvicorn>=0.34,<1" \
      "websockets>=15,<17"
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps .

COPY specs ./specs
COPY scenarios ./scenarios
COPY generated ./generated
COPY deployment ./deployment
COPY alembic.ini ./

RUN useradd --create-home --uid 10001 traffic \
    && chown -R traffic:traffic /workspace
USER traffic

ENTRYPOINT ["traffic-platform"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
