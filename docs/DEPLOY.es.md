# Guía de despliegue en tu VPS (k3s)

Orden recomendado. Cada fase termina con algo funcionando, así puedes parar en cualquier punto
y ya tienes algo que contar en una entrevista.

## 0. Antes de empezar

### Requisitos del VPS
| Recurso | Mínimo | Recomendado |
|---------|--------|-------------|
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB |
| Disco | 30 GB | 40 GB+ |
| SO | Ubuntu 22.04/24.04 o Debian 12 | |

k3s consume ~500 MB; el worker con Whisper `base` ~1 GB; con 4 GB vas justo pero funciona.
Si tu VPS tiene 2 GB, usa `WHISPER_MODEL: tiny` en `k8s/base/configmap.yaml`.

### ⚠️ Conflicto con Dokploy
Dokploy ya usa Docker Swarm y su propio Traefik en los puertos **80 y 443**. k3s también trae
Traefik y querría esos puertos. Opciones:

1. **VPS aparte (recomendado).** Uno de 4 GB cuesta ~USD 5-8/mes (Hetzner, Contabo, etc.).
   Cero riesgo para lo que ya tienes corriendo. Esta guía asume esta opción.
2. **Mismo VPS.** Instala k3s sin su Traefik (`--disable=traefik`), expón el Service del API
   como `NodePort` y enruta un subdominio desde el Traefik de Dokploy a ese puerto. Funciona,
   pero mezclas dos orquestadores en una máquina; hazlo solo si tienes RAM de sobra (8 GB+).

### Otras cosas que necesitas
- **Cuenta de GitHub** con este repo público (también lo necesitas para tu CV).
- **Subdominio** apuntando al VPS: registro `A` `transcriber.julian-lizcano.com` → IP del VPS.
- **kubectl** en tu PC (ya lo tienes).

## 1. Subir el repo a GitHub y generar la imagen

Antes del primer commit, firma con un correo que esté en tu cuenta de GitHub
(Settings → Emails); si no, los commits no aparecen en tu perfil:

```bash
cd transcriber-k8s
git init -b main
git config user.email "kradnah@gmail.com"   # o tu correo noreply de GitHub
git config user.name "Julian Lizcano"
git add .
git commit -m "Initial transcriber service with k3s manifests"
gh repo create transcriber-k8s --public --source . --push   # o créalo en la web y haz git push
```

El workflow `ci` corre tests, valida los manifiestos y publica la imagen en
`ghcr.io/<tu-usuario>/transcriber-k8s`. Después del primer push:

1. GitHub → tu perfil → **Packages** → `transcriber-k8s` → *Package settings* →
   **Change visibility → Public** (así el clúster la descarga sin credenciales).
2. `k8s/overlays/prod/kustomization.yaml` ya apunta a `ghcr.io/kradnah/transcriber-k8s`.

## 2. Instalar k3s en el VPS

```bash
# En el VPS
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
curl -sfL https://get.k3s.io | sh -
sudo kubectl get nodes        # debe salir Ready
```

No abras el puerto **6443** (la API de Kubernetes) a internet. Para manejar el clúster desde
tu PC usa un túnel SSH:

```bash
# En tu PC: copia el kubeconfig
scp root@IP_DEL_VPS:/etc/rancher/k3s/k3s.yaml ~/.kube/k3s-vps.yaml
# Deja 127.0.0.1 en el archivo y abre un túnel en otra terminal:
ssh -N -L 6443:127.0.0.1:6443 root@IP_DEL_VPS
# Usa ese kubeconfig
export KUBECONFIG=~/.kube/k3s-vps.yaml      # PowerShell: $env:KUBECONFIG="$HOME\.kube\k3s-vps.yaml"
kubectl get nodes
```

**Qué aprendes:** qué es un nodo, el kubeconfig, por qué la API del clúster no se expone.

## 3. Instalar cert-manager (certificados HTTPS)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.yaml
kubectl -n cert-manager rollout status deploy/cert-manager-webhook
kubectl apply -f k8s/cluster/cluster-issuer.yaml
```

**Qué aprendes:** CRDs (recursos personalizados), controladores, operadores.

## 4. Crear el secreto y desplegar

```bash
kubectl apply -f k8s/base/namespace.yaml
# Genera una clave y guárdala en tu gestor de contraseñas
API_KEY=$(openssl rand -hex 24)
kubectl -n transcriber create secret generic transcriber-secrets --from-literal=api-key="$API_KEY"

kubectl apply -k k8s/overlays/prod
kubectl -n transcriber get pods -w
```

El primer arranque del worker tarda unos minutos (descarga el modelo). Mira el progreso:

```bash
kubectl -n transcriber logs deploy/worker -f
kubectl -n transcriber get certificate        # READY=True cuando el HTTPS está listo
```

## 5. Probarlo

```bash
curl -H "X-API-Key: $API_KEY" -F file=@audio.wav -F language=es \
  https://transcriber.julian-lizcano.com/v1/transcriptions
# copia el id y consulta
curl -H "X-API-Key: $API_KEY" https://transcriber.julian-lizcano.com/v1/transcriptions/<id>
```

## 6. Experimentos (aquí es donde realmente aprendes)

Haz cada uno, observa qué pasa y anótalo; son tus respuestas de entrevista.

| Experimento | Comando | Qué observar |
|-------------|---------|--------------|
| Matar un pod del API | `kubectl -n transcriber delete pod -l app.kubernetes.io/name=api` | El Deployment lo recrea; el servicio no se cae porque hay 2 réplicas |
| Tumbar Redis | `kubectl -n transcriber delete pod redis-0` | El API pasa a *not ready* (readiness) pero no se reinicia (liveness); los datos sobreviven por el PVC |
| Despliegue sin downtime | cambia algo, push, `kubectl -n transcriber rollout restart deploy/api` | `rollout status`, `maxUnavailable: 0` |
| Rollback | `kubectl -n transcriber rollout undo deploy/api` | Historial de ReplicaSets |
| Autoescalado | manda 10 audios seguidos y mira `kubectl -n transcriber get hpa -w` | El HPA sube a 2 workers |
| Límite de memoria | pon `WHISPER_MODEL: small` y `limits.memory: 512Mi` | `OOMKilled` en `kubectl describe pod` |
| NetworkPolicy | `kubectl -n transcriber run t --rm -it --image=redis:7.4-alpine -- redis-cli -h redis ping` | Se queda colgado: solo api/worker pueden hablar con Redis |
| Pod Security | intenta un pod con `runAsUser: 0` en el namespace | Lo rechaza el admission controller |

## 7. Siguiente nivel (cuando lo anterior esté claro)

1. **Argo CD** (GitOps): el clúster se sincroniza solo con el repo.
2. **KEDA**: escalar workers por longitud de la cola de Redis en vez de CPU.
3. **Prometheus + Grafana** (kube-prometheus-stack): dashboard con la métrica `transcriber_queue_length`.
4. **Cola confiable**: `BLMOVE` a una lista de "processing" para no perder trabajos si un worker muere.
5. Certificación **CKAD** si quieres una credencial formal.

## Qué poner en el CV (solo lo que realmente hayas hecho)

> **Self-hosted transcription service on Kubernetes (k3s)** - Deployed a FastAPI + Redis +
> faster-whisper worker service on a single-node k3s cluster: Kustomize, Traefik ingress with
> cert-manager TLS, HPA, liveness/readiness/startup probes, NetworkPolicies, restricted Pod
> Security, and GitHub Actions CI publishing to GHCR. github.com/Kradnah/transcriber-k8s
