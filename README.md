# transcriber-k8s

Self-hosted speech-to-text service running on a single-node **k3s** Kubernetes cluster on a VPS.
Upload an audio file, a worker transcribes it with **faster-whisper** on CPU, and you poll for the result.

It is a small, production-shaped version of a call-analysis system I built at work (self-hosted WhisperX
replacing a paid speech-to-text API), rebuilt here as a hands-on project to learn Kubernetes.

```
              HTTPS (Let's Encrypt via cert-manager)
client ──► Traefik Ingress ──► api (FastAPI, 2 replicas) ──► Redis (StatefulSet + PVC)
                                                                   ▲
                                              worker (faster-whisper, HPA 1-2) ─┘
                                                     └─ model cache (PVC)
```

## What it demonstrates

| Area | How |
|------|-----|
| Workloads | `Deployment` for stateless API and workers, `StatefulSet` with `volumeClaimTemplates` for Redis |
| Config and secrets | `ConfigMap` via `envFrom`, API key from a `Secret` created out of band (never in git) |
| Storage | `PersistentVolumeClaim` on k3s `local-path` for Redis data and the Whisper model cache |
| Health | Separate liveness (`/healthz`) and readiness (`/readyz`, checks Redis) probes; `startupProbe` covers the first model download; worker liveness via heartbeat file |
| Scaling | `HorizontalPodAutoscaler` on worker CPU (metrics-server ships with k3s) |
| Graceful shutdown | Worker handles `SIGTERM` and finishes the current job within `terminationGracePeriodSeconds` |
| Networking | Traefik `Ingress`, TLS from cert-manager + Let's Encrypt (HTTP-01) |
| Security | `restricted` Pod Security Standard on the namespace, non-root, read-only root filesystem, dropped capabilities, seccomp, default-deny `NetworkPolicy` (only API/worker reach Redis, only Traefik reaches the API) |
| Packaging | Kustomize base + `prod` overlay (image and host) |
| CI | GitHub Actions: pytest, manifest validation with kubeconform, image build and push to GHCR |
| Observability | Prometheus metrics at `/metrics` (jobs created, queue length) |

## API

```bash
# Submit (returns 202 with a job id)
curl -H "X-API-Key: $API_KEY" -F file=@call.wav -F language=es https://transcriber.julian-lizcano.com/v1/transcriptions

# Poll
curl -H "X-API-Key: $API_KEY" https://transcriber.julian-lizcano.com/v1/transcriptions/<id>
```

Job states: `queued` → `processing` → `done` | `failed`. Jobs and audio expire after 24 h.

## Run locally

```bash
docker compose up --build
curl -F file=@call.wav localhost:8000/v1/transcriptions
```

Tests (no model download, uses a fake transcriber and fakeredis):

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Deploy to a VPS

Step-by-step guide (Spanish): [docs/DEPLOY.es.md](docs/DEPLOY.es.md).

## Known limitations and next steps

- **At-most-once processing:** a worker that crashes mid-job loses that job (`BLPOP` removes it from the queue). Next: reliable queue with `BLMOVE` to a processing list plus a reaper.
- Scale workers on **queue length** with KEDA instead of CPU.
- **GitOps** with Argo CD instead of `kubectl apply`.
- Prometheus + Grafana dashboards; keep `/metrics` off the public ingress.
- Pin images by digest and deploy commit-SHA tags instead of `latest`.
