FROM xiongan-traffic-platform-backend:phase1

USER root
WORKDIR /workspace
RUN python -m pip install --no-cache-dir \
      "mypy>=1.14,<2" \
      "pytest>=8.3,<9" \
      "pytest-asyncio>=0.25,<1" \
      "ruff>=0.9,<1" \
      "types-jsonschema>=4.23" \
      "types-networkx>=3.4" \
      "types-psutil>=7.0" \
      "types-PyYAML>=6.0"
COPY tests ./tests
RUN chown -R traffic:traffic /workspace/tests
USER traffic

ENTRYPOINT ["python", "-m", "pytest"]
