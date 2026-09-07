#!/bin/bash
# Backup do workspace do novel-translator (banco + artefatos) para o
# Object Storage da OCI. Espelha o padrão do dojo-full.
#
# Uso: ./backup.sh <bucket> <namespace-os> [k8s-namespace]
set -e

BUCKET_NAME=${1:?"informe o bucket: $0 <bucket> <os-namespace> [k8s-namespace]"}
OS_NAMESPACE=${2:?"informe o namespace do Object Storage"}
NAMESPACE=${3:-"novel-translator"}
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="novel_translator_backup_${DATE}.tar.gz"

echo "=== Novel Translator - Backup ==="
echo "Date: $DATE"

# Quiesce writes: SQLite WAL cannot be copied safely under write load.
# The trap restores service even if the copy or upload fails mid-way.
trap 'sudo k3s kubectl scale deployment/novel-translator-web -n "$NAMESPACE" --replicas=1 || true' EXIT
echo "Scaling deployment to zero..."
sudo k3s kubectl scale deployment/novel-translator-web -n "$NAMESPACE" --replicas=0
sudo k3s kubectl wait --for=delete pod -l app=novel-translator-web -n "$NAMESPACE" --timeout=120s || true

# Copy the workspace through a throwaway pod sharing the same PVC.
# The override must reuse the generated container name or merge patching
# discards the --command/--image flags and busybox exits silently.
echo "Copying workspace from PVC..."
sudo k3s kubectl run backup-copy --rm -i --restart=Never -n "$NAMESPACE" \
  --image=busybox:1.36 \
  --overrides='{"spec":{"volumes":[{"name":"workspace","persistentVolumeClaim":{"claimName":"novel-translator-data"}}],"containers":[{"name":"backup-copy","image":"busybox:1.36","stdin":true,"command":["tar","czf","-","-C","/data","."],"volumeMounts":[{"name":"workspace","mountPath":"/data"}]}]}}' \
  > /tmp/"$BACKUP_FILE"
test -s /tmp/"$BACKUP_FILE" || { echo "Backup is empty; aborting before upload."; exit 1; }
echo "Restarting deployment..."
sudo k3s kubectl scale deployment/novel-translator-web -n "$NAMESPACE" --replicas=1
sudo k3s kubectl rollout status deployment/novel-translator-web -n "$NAMESPACE" --timeout=300s

echo "Uploading to Object Storage: ${BUCKET_NAME}"
oci os object put \
  --bucket-name "$BUCKET_NAME" \
  --namespace-name "$OS_NAMESPACE" \
  --file /tmp/"$BACKUP_FILE" \
  --name "backups/${BACKUP_FILE}"

rm /tmp/"$BACKUP_FILE"

echo ""
echo "=== Backup Complete ==="
echo "Location: ${BUCKET_NAME}/backups/${BACKUP_FILE}"
