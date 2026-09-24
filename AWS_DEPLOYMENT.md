# LeadFlow — AWS deployment guide

> **Status (24 Sep 2026): repository ready, AWS NOT deployed.**
> No AWS resources have been created yet. The AWS CLI on the preparation machine
> had only an expired root-user sign-in session. Everything below that says
> "rehearsed" was run locally against real copies of the production data.

```
                     INTERNET
                         |
                  HTTPS 443 (80 -> 443 redirect)
                         v
           Application Load Balancer  (public subnets, idle timeout 3600 s)
                         |  HTTP 8501 + WebSocket, sticky sessions
                         v
           ECS Fargate: LeadFlow container (2 vCPU / 8 GB, Streamlit :8501)
                         |                         |
                         v                         v
                  Supabase Auth              RDS PostgreSQL 17 (:5432, TLS)
            (login + public.profiles)        (private subnets, encrypted)

   Secrets Manager (leadflow/app) --> ECS task secrets --> environment variables
```

* **Auth stays on Supabase.** Login, logout, sessions and roles (`public.profiles`) keep using
  the Supabase project. The Supabase project must stay active after the migration.
* **Only LeadFlow's data tables move to RDS** (Master, MQL, Bounce, Unsub, upload history).
* The image contains code only. All settings come from environment variables.

---

## 1. Configuration

| Variable | Production value |
|---|---|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_KEY` | Supabase anon (public) key |
| `PG_HOST` | RDS endpoint (`localhost` for local development) |
| `PG_PORT` | `5432` |
| `PG_DATABASE` | `leadflow` |
| `PG_USER` | `leadflow_app` (dedicated app role, **not** the RDS master user) |
| `PG_PASSWORD` | app role password |
| `PGSSLMODE` | `require` (`PG_SSLMODE` is also accepted) |
| `PG_STORAGE_QUOTA_MB` | allocated RDS storage in MB: 20 GB = `20480` |

Precedence: `.streamlit/secrets.toml` (local development) first for Supabase, environment
second; for PostgreSQL the environment overrides secrets. Switching between a local database,
Supabase and RDS is only a change of these variables.

---

## 2. Facts measured before migration (24 Sep 2026)

| Item | Value |
|---|---|
| Source | Supabase PostgreSQL **17.6**, database `postgres`, schema `public` |
| Source database size | 452 MB (LeadFlow tables ≈ 440 MB) |
| Master (`master_contacts`) | 1,479,585 rows, 1 list |
| MQL (`mql_emails`) | 17,744 rows, 1 list |
| Bounce (`bounce_emails`) | 0 |
| Unsub (`unsub_emails`) | 0 |
| `upload_history` | 1 row |
| Size after restore (fresh, no bloat) | ≈ 380 MB, ≈ 250 MB per 1M Master rows |
| Roles in `public.profiles` | enum `user_role` = `admin`, `user` (5 accounts, all admin) |

Findings that shape the plan:

1. **Use RDS PostgreSQL 17, not 16.** The source is 17.6, so the dump needs a v17 `pg_dump`.
   Restoring it into 16 raises `unrecognized configuration parameter "transaction_timeout"`
   and `pg_restore` exits with code 1. The data still arrives intact (verified), but a migration
   whose success signal is an error is fragile. Into 17 the restore is clean (exit 0).
2. **Dump through the Supabase session pooler, port 5432.** The app uses the transaction pooler
   (port 6543), which is not suitable for `pg_dump`.
3. **Do not migrate `public.profiles`.** It belongs to Supabase Auth (foreign key to `auth.users`)
   and the app reads it through the Supabase API.

### Rehearsal results (local PostgreSQL 16.15 and 17.11)

* `pg_dump` 17.11 from Supabase: 260 s, 49 MB custom-format dump. Source verified unchanged afterwards.
* `pg_restore --jobs=4` as the non-superuser app role: ≈ 20 s.
* `deploy/compare_inventory.py`: **PASS on both versions** — identical row counts, id ranges,
  distinct emails, columns, indexes, constraints and a content fingerprint of every row.
  Sequences resume above the highest id.
* LeadFlow container against each copy: 19/19 functional checks passed (uploads, upload
  history, Master merge preserving all existing rows, Database page counts, storage panel,
  RBAC, compare options, cleaning pipeline with Master/Bounce/MQL/Unsub suppression, output
  file, Industry search).
* Timings on the copy: all-category counts ≈ 2 s cold / 0.3 s warm; duplicate check of
  20,002 emails against 1.48M Master rows 0.2–0.33 s (index-only scan on `idx_master_contacts_email`).

---

## 3. Local Docker run

```bash
docker build -t leadflow:latest .
cp .env.example .env                       # fill in; .env is git- and docker-ignored
docker run -d --name leadflow -p 8501:8501 --env-file .env leadflow:latest
curl http://localhost:8501/_stcore/health  # -> ok
docker logs -f leadflow
docker stop leadflow && docker rm leadflow
```

---

## 4. AWS runbook (not yet executed)

Run in **AWS CloudShell** (region `ap-southeast-1`) or any bash shell with AWS CLI v2 and Docker.
Use an **IAM user or role with admin rights, not the root user.** Values in `<...>` are yours.

```bash
export AWS_REGION=ap-southeast-1
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
export VPC_ID=<vpc-id>
export PUBLIC_SUBNETS="<subnet-public-a> <subnet-public-b>"     # ALB, two AZs
export PRIVATE_SUBNETS="<subnet-private-a> <subnet-private-b>"  # ECS + RDS, two AZs, route to a NAT gateway
```

### 4.1 Security groups

```bash
ALB_SG=$(aws ec2 create-security-group --group-name leadflow-alb --description "LeadFlow ALB" --vpc-id $VPC_ID --query GroupId --output text)
APP_SG=$(aws ec2 create-security-group --group-name leadflow-app --description "LeadFlow ECS tasks" --vpc-id $VPC_ID --query GroupId --output text)
RDS_SG=$(aws ec2 create-security-group --group-name leadflow-rds --description "LeadFlow RDS" --vpc-id $VPC_ID --query GroupId --output text)

aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 443 --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80  --cidr 0.0.0.0/0
aws ec2 authorize-security-group-ingress --group-id $APP_SG --protocol tcp --port 8501 --source-group $ALB_SG
aws ec2 authorize-security-group-ingress --group-id $RDS_SG --protocol tcp --port 5432 --source-group $APP_SG
```

| SG | Inbound | Source |
|---|---|---|
| `leadflow-alb` | 443, 80 | internet |
| `leadflow-app` | 8501 | `leadflow-alb` only |
| `leadflow-rds` | 5432 | `leadflow-app` only (+ migration host, temporarily) |

ECS tasks need outbound HTTPS to Supabase, ECR, Secrets Manager and CloudWatch: private
subnets with a NAT gateway (≈ $32/month + data). Cheaper alternative: run tasks in the public
subnets with `assignPublicIp=ENABLED`; `leadflow-app` still only admits the ALB.

### 4.2 RDS PostgreSQL 17

```bash
aws rds create-db-subnet-group --db-subnet-group-name leadflow-db \
  --db-subnet-group-description "LeadFlow RDS" --subnet-ids $PRIVATE_SUBNETS

aws rds create-db-instance --db-instance-identifier leadflow-db \
  --engine postgres --engine-version 17 --db-instance-class db.t4g.small \
  --storage-type gp3 --allocated-storage 20 --max-allocated-storage 100 --storage-encrypted \
  --master-username leadflow_admin --manage-master-user-password \
  --db-subnet-group-name leadflow-db --vpc-security-group-ids $RDS_SG --no-publicly-accessible \
  --backup-retention-period 7 --preferred-backup-window 18:00-18:30 \
  --deletion-protection --copy-tags-to-snapshot --auto-minor-version-upgrade \
  --enable-cloudwatch-logs-exports postgresql

aws rds wait db-instance-available --db-instance-identifier leadflow-db
RDS_ENDPOINT=$(aws rds describe-db-instances --db-instance-identifier leadflow-db --query 'DBInstances[0].Endpoint.Address' --output text)
```

* The master password lives in Secrets Manager (created by `--manage-master-user-password`).
* `rds.force_ssl` is on by default for PostgreSQL 15+; RDS refuses non-TLS connections.
* If you must stay on 16, use `--engine-version 16` and expect the `transaction_timeout` restore errors described in section 2.

### 4.3 Dedicated application role

From a host that can reach RDS (see 4.4), connected as `leadflow_admin` to database `postgres`:

```sql
CREATE ROLE leadflow_app LOGIN PASSWORD '<APP_PASSWORD>';
GRANT leadflow_app TO leadflow_admin;          -- lets the master user create a database owned by it
CREATE DATABASE leadflow OWNER leadflow_app;
```

`leadflow_app` owns the LeadFlow tables but has no superuser, CREATEDB or CREATEROLE rights.
LeadFlow never uses `leadflow_admin`.

### 4.4 Migration host

RDS is private, so migrate from inside the VPC: an **AWS CloudShell VPC environment** or a small
temporary EC2 instance in a private subnet. Give it security group `leadflow-migration` and allow it temporarily:

```bash
MIG_SG=$(aws ec2 create-security-group --group-name leadflow-migration --description "Temporary migration host" --vpc-id $VPC_ID --query GroupId --output text)
aws ec2 authorize-security-group-ingress --group-id $RDS_SG --protocol tcp --port 5432 --source-group $MIG_SG
# install PostgreSQL 17 client tools (pg_dump / pg_restore / psql) and Python 3.11 + requirements.txt
```

Remove that rule after the migration.

### 4.5 Migration (section 6 has the full order)

```bash
# 1. Dump from Supabase — SESSION pooler port 5432, v17 client. Prompts for the password (or use ~/.pgpass).
PGSSLMODE=require pg_dump --host=<SUPABASE_POOLER_HOST> --port=5432 --username=<SUPABASE_USER> \
  --dbname=postgres --format=custom --no-owner --no-privileges \
  --table=public.master_lists --table=public.master_contacts \
  --table=public.bounce_lists --table=public.bounce_emails \
  --table=public.mql_lists    --table=public.mql_emails \
  --table=public.unsub_lists  --table=public.unsub_emails \
  --table=public.upload_history \
  --file=leadflow.dump

# 2. Restore into RDS as the app role (objects become owned by leadflow_app)
PGSSLMODE=require pg_restore --host=$RDS_ENDPOINT --port=5432 --username=leadflow_app \
  --dbname=leadflow --no-owner --no-privileges --jobs=4 leadflow.dump
```

`leadflow.dump` contains every contact. It is git- and docker-ignored; delete it after the migration.

### 4.6 Secrets Manager

Write the payload to a local file named `leadflow-app.secret.json` (ignored by git and Docker):

```json
{
  "SUPABASE_URL": "<...>", "SUPABASE_KEY": "<...>",
  "PG_HOST": "<RDS_ENDPOINT>", "PG_PORT": "5432", "PG_DATABASE": "leadflow",
  "PG_USER": "leadflow_app", "PG_PASSWORD": "<APP_PASSWORD>",
  "PGSSLMODE": "require", "PG_STORAGE_QUOTA_MB": "20480"
}
```

```bash
SECRET_ARN=$(aws secretsmanager create-secret --name leadflow/app \
  --secret-string file://leadflow-app.secret.json --query ARN --output text)
rm leadflow-app.secret.json
```

Keep `PG_STORAGE_QUOTA_MB` equal to the allocated RDS storage. If storage autoscaling grows the
volume, update the secret and redeploy.

### 4.7 IAM, ECR, logs, cluster

```bash
aws iam create-role --role-name leadflow-ecs-execution --assume-role-policy-document \
  '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name leadflow-ecs-execution \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy
aws iam put-role-policy --role-name leadflow-ecs-execution --policy-name leadflow-read-secret --policy-document \
  "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"$SECRET_ARN\"}]}"

aws ecr create-repository --repository-name leadflow --image-scanning-configuration scanOnPush=true
aws ecr get-login-password | docker login --username AWS --password-stdin $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build -t $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/leadflow:$IMAGE_TAG .
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/leadflow:$IMAGE_TAG

aws logs create-log-group --log-group-name /ecs/leadflow
aws logs put-retention-policy --log-group-name /ecs/leadflow --retention-in-days 30
aws ecs create-cluster --cluster-name leadflow
```

### 4.8 Task definition

`deploy/ecs-task-definition.json` is the template: 2 vCPU / 8 GB, port 8501, all nine variables
from the secret, container health check on `/_stcore/health` (60 s start period), `awslogs`.

```bash
sed -e "s#<ACCOUNT_ID>#$ACCOUNT_ID#g" -e "s#<REGION>#$AWS_REGION#g" \
    -e "s#<IMAGE_TAG>#$IMAGE_TAG#g"   -e "s#<SECRET_ARN>#$SECRET_ARN#g" \
    deploy/ecs-task-definition.json > /tmp/leadflow-td.json
aws ecs register-task-definition --cli-input-json file:///tmp/leadflow-td.json
```

### 4.9 HTTPS certificate (needs your domain)

```bash
CERT_ARN=$(aws acm request-certificate --domain-name <LEADFLOW_DOMAIN> --validation-method DNS --query CertificateArn --output text)
aws acm describe-certificate --certificate-arn $CERT_ARN --query 'Certificate.DomainValidationOptions[0].ResourceRecord'
# create that CNAME at your DNS provider, then:
aws acm wait certificate-validated --certificate-arn $CERT_ARN
```

### 4.10 Load balancer

```bash
ALB_ARN=$(aws elbv2 create-load-balancer --name leadflow-alb --type application --scheme internet-facing \
  --subnets $PUBLIC_SUBNETS --security-groups $ALB_SG --query 'LoadBalancers[0].LoadBalancerArn' --output text)
aws elbv2 modify-load-balancer-attributes --load-balancer-arn $ALB_ARN \
  --attributes Key=idle_timeout.timeout_seconds,Value=3600

TG_ARN=$(aws elbv2 create-target-group --name leadflow-tg --protocol HTTP --port 8501 --vpc-id $VPC_ID \
  --target-type ip --health-check-path /_stcore/health --matcher HttpCode=200 \
  --health-check-interval-seconds 30 --healthy-threshold-count 2 --unhealthy-threshold-count 3 \
  --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 modify-target-group-attributes --target-group-arn $TG_ARN --attributes \
  Key=stickiness.enabled,Value=true Key=stickiness.type,Value=lb_cookie \
  Key=stickiness.lb_cookie.duration_seconds,Value=86400 Key=deregistration_delay.timeout_seconds,Value=30

aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 \
  --default-actions 'Type=redirect,RedirectConfig={Protocol=HTTPS,Port=443,StatusCode=HTTP_301}'
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTPS --port 443 \
  --certificates CertificateArn=$CERT_ARN --ssl-policy ELBSecurityPolicy-TLS13-1-2-2021-06 \
  --default-actions Type=forward,TargetGroupArn=$TG_ARN
```

Point `<LEADFLOW_DOMAIN>` at the ALB (Route 53 alias, or a CNAME to the ALB DNS name).
Sticky sessions matter once more than one task runs: Streamlit keeps each session in process memory.

### 4.11 ECS service (only after the migration is verified — section 6)

```bash
aws ecs create-service --cluster leadflow --service-name leadflow --task-definition leadflow \
  --desired-count 1 --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-private-a>,<subnet-private-b>],securityGroups=[$APP_SG],assignPublicIp=DISABLED}" \
  --load-balancers targetGroupArn=$TG_ARN,containerName=leadflow,containerPort=8501 \
  --health-check-grace-period-seconds 120 \
  --deployment-configuration "deploymentCircuitBreaker={enable=true,rollback=true},minimumHealthyPercent=100,maximumPercent=200"
aws ecs wait services-stable --cluster leadflow --services leadflow
```

ECS restarts a task whose container health check fails; the circuit breaker rolls back a bad deployment.

### 4.12 Monitoring (low cost)

```bash
TOPIC_ARN=$(aws sns create-topic --name leadflow-alerts --query TopicArn --output text)
aws sns subscribe --topic-arn $TOPIC_ARN --protocol email --notification-endpoint <ops-email>   # confirm the email

ALB_DIM=$(echo $ALB_ARN | sed 's#.*:loadbalancer/##'); TG_DIM=$(echo $TG_ARN | sed 's#.*:##')
aws cloudwatch put-metric-alarm --alarm-name leadflow-no-healthy-task --namespace AWS/ApplicationELB \
  --metric-name HealthyHostCount --dimensions Name=LoadBalancer,Value=$ALB_DIM Name=TargetGroup,Value=$TG_DIM \
  --statistic Minimum --period 60 --evaluation-periods 3 --threshold 1 --comparison-operator LessThanThreshold \
  --treat-missing-data breaching --alarm-actions $TOPIC_ARN
aws cloudwatch put-metric-alarm --alarm-name leadflow-rds-low-storage --namespace AWS/RDS \
  --metric-name FreeStorageSpace --dimensions Name=DBInstanceIdentifier,Value=leadflow-db \
  --statistic Minimum --period 300 --evaluation-periods 1 --threshold 2147483648 \
  --comparison-operator LessThanThreshold --alarm-actions $TOPIC_ARN
aws cloudwatch put-metric-alarm --alarm-name leadflow-rds-cpu --namespace AWS/RDS \
  --metric-name CPUUtilization --dimensions Name=DBInstanceIdentifier,Value=leadflow-db \
  --statistic Average --period 300 --evaluation-periods 3 --threshold 80 \
  --comparison-operator GreaterThanThreshold --alarm-actions $TOPIC_ARN
```

* App logs: CloudWatch log group `/ecs/leadflow` (30-day retention).
* Restarts: `aws ecs describe-services --cluster leadflow --services leadflow --query 'services[0].events[:10]'`.
* RDS: standard CloudWatch metrics plus the exported `postgresql` log.

---

## 5. Updating the app

```bash
IMAGE_TAG=$(git rev-parse --short HEAD)
docker build -t $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/leadflow:$IMAGE_TAG .
docker push $ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/leadflow:$IMAGE_TAG
# re-run the sed + register-task-definition step from 4.8, then:
aws ecs update-service --cluster leadflow --service leadflow --task-definition leadflow
aws ecs wait services-stable --cluster leadflow --services leadflow
```

After changing only the secret: `aws ecs update-service --cluster leadflow --service leadflow --force-new-deployment`.

---

## 6. Cut-over order and verification

1. Create RDS, the app role and the migration host (4.1–4.4). Supabase stays live and unchanged.
2. **Freeze writes**: tell admins not to upload to the Database page until step 8.
3. Record the source (from any machine with the current secrets.toml; read-only):
   `python deploy/db_inventory.py source source.json`
4. Dump and restore (4.5).
5. Record the target (on the migration host, with `PG_HOST=$RDS_ENDPOINT PG_USER=leadflow_app PG_PASSWORD=... PG_DATABASE=leadflow PGSSLMODE=require`):
   `python deploy/db_inventory.py rds target.json`
6. `python deploy/compare_inventory.py source.json target.json` must print `OVERALL: PASS`.
   **If it fails, stop.** Do not start the ECS service; investigate.
7. Create the secret and the ECS service (4.6–4.11).
8. Verify production, then lift the freeze:

| # | Check | Expected |
|---|---|---|
| 1 | `curl https://<domain>/_stcore/health` | `ok`; target group healthy |
| 2 | Log in with a real account | sidebar shows email and role |
| 3 | F5, change page, F5 again, reopen the tab | still logged in |
| 4 | Log out | login form; log in again works |
| 5 | Database page caption | `Connected to leadflow at <RDS endpoint>:5432` |
| 6 | Database tab counts | equal to `target.json` (Master 1,479,585 / MQL 17,744 / Bounce 0 / Unsub 0 as of 24 Sep) |
| 7 | Storage panel | real sizes; Available ≈ 20 GB − used |
| 8 | Upload a 3-row test file to MQL, Bounce and Unsub | counts rise by exactly 3; history row with date/time |
| 9 | Merge a small Master file with 1 new + 2 existing emails | total +1, 2 skipped |
| 10 | Main page: compare options visible under the uploader; run the pipeline; download | report shows Steps 6, 7, 7b, 7c; CSV downloads |
| 11 | Split by field → type "Software" in the search | matching groups only; clearing shows all |
| 12 | Log in as a `user`-role account | Database and Manage Users show "You need Admin access" |
| 13 | UI in a dark-mode browser | all text readable |

Use clearly named test lists (e.g. `__test_mql__`) so they can be deleted from the Database page afterwards.

---

## 7. Backup and rollback

* **Backups**: RDS automated backups, 7-day retention, point-in-time restore; storage encrypted.
  Manual snapshot before any risky change:
  `aws rds create-db-snapshot --db-instance-identifier leadflow-db --db-snapshot-identifier leadflow-pre-change-<date>`
* **Restore**: `aws rds restore-db-instance-to-point-in-time --source-db-instance-identifier leadflow-db --target-db-instance-identifier leadflow-db-restore --restore-time <UTC time> --db-subnet-group-name leadflow-db --vpc-security-group-ids $RDS_SG --no-publicly-accessible`, then point `PG_HOST` at the new endpoint.
* **Bad app release**: `aws ecs update-service --cluster leadflow --service leadflow --task-definition leadflow:<previous-revision>`.
* **Stop the app safely**: `aws ecs update-service --cluster leadflow --service leadflow --desired-count 0` (RDS keeps running; data is untouched).
* **Fall back to Supabase**: set `PG_HOST`, `PG_PORT` (6543), `PG_DATABASE` (`postgres`), `PG_USER`, `PG_PASSWORD` in `leadflow/app` back to the Supabase pooler values and force a new deployment. Writes made on RDS after cut-over are not in Supabase; dump/restore them back if needed.
* **Keep the Supabase data** untouched until production has run cleanly on RDS for an agreed period. The Supabase project itself stays permanently (Auth + profiles).

---

## 8. Cost (ap-southeast-1, on-demand, approximate)

| Item | ≈ per month |
|---|---|
| RDS db.t4g.small + 20 GB gp3 + backups | $30 |
| Fargate 2 vCPU / 8 GB, 1 task 24×7 | $80–90 |
| ALB | $20 + LCU |
| NAT gateway (if private subnets) | $32 + data |
| Secrets Manager, CloudWatch logs/alarms, ECR | < $5 |
