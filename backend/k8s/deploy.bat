@echo off
REM FluxKart Kubernetes Deploy Script (Windows)
REM Run from D:\FluxKart\backend directory
REM Usage: k8s\deploy.bat

echo Enabling metrics-server addon (required for HPA)...
minikube addons enable metrics-server

echo Applying namespace...
kubectl apply -f k8s/namespace.yaml

echo Applying secrets and configmap...
kubectl apply -f k8s/secrets.yaml
kubectl apply -f k8s/configmap.yaml

echo Deploying Redis...
kubectl apply -f k8s/redis/deployment.yaml

echo Deploying RabbitMQ...
kubectl apply -f k8s/rabbitmq/deployment.yaml

echo Deploying PgBouncer...
kubectl apply -f k8s/pgbouncer/deployment.yaml

echo Waiting for Redis to be ready...
kubectl wait --for=condition=ready pod -l app=redis -n fluxkart --timeout=60s

echo Waiting for RabbitMQ to be ready...
kubectl wait --for=condition=ready pod -l app=rabbitmq -n fluxkart --timeout=120s

echo Deploying API...
kubectl apply -f k8s/api/deployment.yaml

echo Deploying Consumer...
kubectl apply -f k8s/consumer/deployment.yaml

echo Deploying Nginx...
kubectl apply -f k8s/nginx/deployment.yaml

echo.
echo All manifests applied.
echo.
echo Check pod status:
echo   kubectl get pods -n fluxkart
echo.
echo Check HPA:
echo   kubectl get hpa -n fluxkart
echo.
echo Get minikube IP:
echo   minikube ip
echo.

pause