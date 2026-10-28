#!/usr/bin/env bash
# Installs k3s next to Dokploy on the same VPS. Run once as root: sudo bash install-k3s.sh
#
# - Dokploy keeps ports 80/443. k3s runs without servicelb, and its Traefik is a NodePort
#   reachable only on the docker0 address (172.17.0.1:30080), never on the public IP.
# - Dokploy's Traefik routes transcriber.julian-lizcano.com (with Let's Encrypt) to it.
# - The kubeconfig is copied to the admin user so the cluster can be managed without sudo.
set -euo pipefail

DOMAIN="transcriber.julian-lizcano.com"
ADMIN_USER="admin"
DOCKER_BRIDGE_IP="172.17.0.1"

echo "== 1/5 Traefik de k3s como NodePort (antes de instalar, k3s lo lee al arrancar)"
mkdir -p /var/lib/rancher/k3s/server/manifests
cat > /var/lib/rancher/k3s/server/manifests/traefik-config.yaml <<'EOF'
apiVersion: helm.cattle.io/v1
kind: HelmChartConfig
metadata:
  name: traefik
  namespace: kube-system
spec:
  valuesContent: |-
    service:
      type: NodePort
    ports:
      web:
        nodePort: 30080
      websecure:
        nodePort: 30443
EOF

echo "== 2/5 Instalar k3s"
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
  --disable=servicelb \
  --kube-proxy-arg=nodeport-addresses=${DOCKER_BRIDGE_IP}/32 \
  --write-kubeconfig-mode=600" sh -

echo "== 3/5 Firewall: tráfico interno de pods y servicios de k3s"
ufw allow from 10.42.0.0/16 to any comment 'k3s pods'
ufw allow from 10.43.0.0/16 to any comment 'k3s services'
ufw allow from 172.16.0.0/12 to any port 30080 proto tcp comment 'Dokploy Traefik -> k3s Traefik'

echo "== 4/5 kubeconfig para ${ADMIN_USER}"
install -d -m 700 -o "$ADMIN_USER" -g "$ADMIN_USER" "/home/${ADMIN_USER}/.kube"
install -m 600 -o "$ADMIN_USER" -g "$ADMIN_USER" /etc/rancher/k3s/k3s.yaml "/home/${ADMIN_USER}/.kube/config"

echo "== 5/5 Ruta en el Traefik de Dokploy"
cat > /etc/dokploy/traefik/dynamic/transcriber-k8s.yml <<EOF
http:
  routers:
    transcriber-k8s-router:
      rule: Host(\`${DOMAIN}\`)
      service: transcriber-k8s-service
      middlewares:
        - redirect-to-https
      entryPoints:
        - web
    transcriber-k8s-router-websecure:
      rule: Host(\`${DOMAIN}\`)
      service: transcriber-k8s-service
      entryPoints:
        - websecure
      tls:
        certResolver: letsencrypt
  services:
    transcriber-k8s-service:
      loadBalancer:
        servers:
          - url: http://${DOCKER_BRIDGE_IP}:30080
        passHostHeader: true
EOF

k3s kubectl get nodes
echo "Listo. Avísale a Claude para que despliegue la app."
