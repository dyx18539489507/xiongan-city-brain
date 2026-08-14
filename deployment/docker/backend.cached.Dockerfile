# Local recovery build used when the package index is temporarily unavailable.
# Create the base tag from the last verified Phase 1 backend image first:
#   docker tag xiongan-traffic-platform-backend:phase1 \
#     xiongan-traffic-platform-backend:phase1-base
FROM xiongan-traffic-platform-backend:phase1-base

USER root
WORKDIR /workspace
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-deps .
COPY specs ./specs
COPY scenarios ./scenarios
COPY generated ./generated
COPY deployment ./deployment
COPY alembic.ini ./
RUN chown -R traffic:traffic /workspace
USER traffic

ENTRYPOINT ["traffic-platform"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
