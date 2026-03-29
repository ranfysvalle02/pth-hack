kubectl get pods -n staging
kubectl logs -f deploy/api-service -n staging
ssh deploy@staging-01.internal
scp release.tar.gz deploy@staging-01.internal:/opt/releases/
terraform plan -var-file=staging.tfvars
aws s3 sync ./dist s3://staging-assets-bucket/
docker push registry.internal/api-service:v2.1.4
