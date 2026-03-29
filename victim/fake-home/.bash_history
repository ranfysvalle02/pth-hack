kubectl get secrets -A
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
ssh -i ~/.ssh/prod-key.pem ubuntu@10.0.1.50
mysql -u root -p's3cretPa$$w0rd' production_db
curl -H "Authorization: Bearer sk-live-abc123" https://api.stripe.com/v1/charges
docker login -u admin -p registry-password registry.internal.company.com
