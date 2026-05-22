# Kubernetes Deployment Notes

These manifests provide a baseline self-hosted deployment:
- `namespace.yaml`
- `postgres.yaml` (StatefulSet + Service)
- `app.yaml` (2-replica Deployment + Service)

## Apply
```bash
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/postgres.yaml
kubectl apply -f deploy/k8s/app.yaml
```

## Required secret (optional if using only `mock` provider)
```bash
kubectl -n inferlog create secret generic inferlog-secrets \
  --from-literal=openai-api-key=YOUR_KEY \
  --from-literal=anthropic-api-key=YOUR_KEY
```

## Important
- Build and load/push `inferlog-app:latest` image before applying app deployment.
- For production, add Ingress, resource limits, pod autoscaling, network policies, and managed secrets.
