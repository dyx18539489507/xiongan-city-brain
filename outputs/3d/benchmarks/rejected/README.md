# Rejected benchmark artifacts

`matrix-20260808T081628Z.json` and its screenshot were produced before the
benchmark harness required a matching digital-twin `experimentId`. The backend
was running, but the sampled browser frame was still the static `IDLE` scene.
They are retained only as a recoverable audit trail and must not be used as FPS
evidence.
