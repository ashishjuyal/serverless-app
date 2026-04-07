#!/usr/bin/env bash
# =============================================================================
# aws-setup.sh  —  One-time AWS setup for the GitHub Actions OIDC pipeline
#
# What this script does:
#   1. Creates the GitHub OIDC Identity Provider in IAM
#   2. Creates an IAM Role that GitHub Actions can assume via OIDC
#   3. Attaches a permissions policy to the role
#   4. Bootstraps CDK for the target account/region
#   5. Prints the secrets you need to add in GitHub
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure / SSO login)
#   - Node.js + aws-cdk installed  (npm install -g aws-cdk)
#   - jq installed (brew install jq / apt install jq)
# =============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION — edit these before running
# =============================================================================

AWS_ACCOUNT_ID="775937640988"
AWS_REGION="us-east-1"

GITHUB_ORG="ashishjuyal"
GITHUB_REPO="serverless-app"
GITHUB_BRANCH="elk"                         # branch the pipeline runs on

IAM_ROLE_NAME="github-actions-deploy-role"  # name for the IAM role
POLICY_NAME="GitHubActionsCDKDeployPolicy"  # name for the inline policy

# Set to "AdministratorAccess" for dev/demo, or "inline" to use the scoped
# policy defined in the build_permissions_policy() function below.
PERMISSIONS_MODE="AdministratorAccess"      # "AdministratorAccess" | "inline"

# =============================================================================
# HELPERS
# =============================================================================

OIDC_PROVIDER_URL="https://token.actions.githubusercontent.com"
OIDC_AUDIENCE="sts.amazonaws.com"
OIDC_PROVIDER_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

log()  { echo "[INFO]  $*"; }
ok()   { echo "[OK]    $*"; }
warn() { echo "[WARN]  $*"; }
die()  { echo "[ERROR] $*" >&2; exit 1; }

check_prerequisites() {
    log "Checking prerequisites..."
    command -v aws  >/dev/null 2>&1 || die "aws CLI not found. Install it first."
    command -v cdk  >/dev/null 2>&1 || die "aws-cdk not found. Run: npm install -g aws-cdk"
    command -v jq   >/dev/null 2>&1 || die "jq not found. Install it (brew install jq)."

    CALLER=$(aws sts get-caller-identity --query 'Account' --output text 2>/dev/null) \
        || die "AWS CLI is not authenticated. Run 'aws configure' or 'aws sso login'."

    if [[ "$CALLER" != "$AWS_ACCOUNT_ID" ]]; then
        die "Logged-in account ($CALLER) does not match AWS_ACCOUNT_ID ($AWS_ACCOUNT_ID). Check your credentials."
    fi
    ok "Authenticated as account $CALLER in region $AWS_REGION"
}

# =============================================================================
# STEP 1 — GitHub OIDC Identity Provider
# =============================================================================

create_oidc_provider() {
    log "Step 1/4 — GitHub OIDC Identity Provider"

    # Check if it already exists
    EXISTING=$(aws iam list-open-id-connect-providers \
        --query "OpenIDConnectProviderList[?ends_with(Arn, 'token.actions.githubusercontent.com')].Arn" \
        --output text)

    if [[ -n "$EXISTING" ]]; then
        ok "OIDC provider already exists: $EXISTING"
        return
    fi

    # GitHub's OIDC thumbprint — this is the SHA-1 of the root CA certificate
    # for token.actions.githubusercontent.com, published by GitHub and AWS docs.
    # AWS no longer uses the thumbprint for verification with this provider, but
    # the API still requires a valid 40-character hex value.
    THUMBPRINT="6938fd4d98bab03faadb97b34396831e3780aea1"

    aws iam create-open-id-connect-provider \
        --url "$OIDC_PROVIDER_URL" \
        --client-id-list "$OIDC_AUDIENCE" \
        --thumbprint-list "$THUMBPRINT" \
        --query 'OpenIDConnectProviderArn' \
        --output text

    ok "OIDC provider created."
}

# =============================================================================
# STEP 2 — IAM Role trust policy
# =============================================================================

build_trust_policy() {
    cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "${OIDC_PROVIDER_ARN}"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:${GITHUB_ORG}/${GITHUB_REPO}:ref:refs/heads/${GITHUB_BRANCH}"
        },
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "${OIDC_AUDIENCE}"
        }
      }
    }
  ]
}
EOF
}

create_iam_role() {
    log "Step 2/4 — IAM Role"

    EXISTING_ROLE=$(aws iam get-role --role-name "$IAM_ROLE_NAME" \
        --query 'Role.Arn' --output text 2>/dev/null || true)

    if [[ -n "$EXISTING_ROLE" ]]; then
        ok "IAM role already exists: $EXISTING_ROLE"
        ROLE_ARN="$EXISTING_ROLE"
        return
    fi

    TRUST_POLICY=$(build_trust_policy)

    ROLE_ARN=$(aws iam create-role \
        --role-name "$IAM_ROLE_NAME" \
        --assume-role-policy-document "$TRUST_POLICY" \
        --description "Assumed by GitHub Actions via OIDC for CDK deployments" \
        --query 'Role.Arn' \
        --output text)

    ok "IAM role created: $ROLE_ARN"
}

# =============================================================================
# STEP 3 — Permissions policy
# =============================================================================

build_permissions_policy() {
    # Scoped policy — covers what CDK needs to deploy Lambda/S3/IAM/CloudFormation stacks.
    # Extend as needed based on what your CDK stacks actually provision.
    cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CloudFormation",
      "Effect": "Allow",
      "Action": ["cloudformation:*"],
      "Resource": "*"
    },
    {
      "Sid": "S3ForCDKStaging",
      "Effect": "Allow",
      "Action": ["s3:*"],
      "Resource": "*"
    },
    {
      "Sid": "Lambda",
      "Effect": "Allow",
      "Action": ["lambda:*"],
      "Resource": "*"
    },
    {
      "Sid": "IAMForCDKRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole", "iam:DeleteRole", "iam:AttachRolePolicy",
        "iam:DetachRolePolicy", "iam:PutRolePolicy", "iam:DeleteRolePolicy",
        "iam:GetRole", "iam:PassRole", "iam:TagRole", "iam:UntagRole",
        "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies"
      ],
      "Resource": "*"
    },
    {
      "Sid": "SSMForCDKBootstrap",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"],
      "Resource": "arn:aws:ssm:${AWS_REGION}:${AWS_ACCOUNT_ID}:parameter/cdk-bootstrap/*"
    },
    {
      "Sid": "ECR",
      "Effect": "Allow",
      "Action": ["ecr:*"],
      "Resource": "*"
    },
    {
      "Sid": "OpenSearch",
      "Effect": "Allow",
      "Action": ["es:*"],
      "Resource": "*"
    },
    {
      "Sid": "CloudWatchLogs",
      "Effect": "Allow",
      "Action": ["logs:*"],
      "Resource": "*"
    },
    {
      "Sid": "SNSSQSForNotifier",
      "Effect": "Allow",
      "Action": ["sns:*", "sqs:*"],
      "Resource": "*"
    }
  ]
}
EOF
}

attach_permissions() {
    log "Step 3/4 — Attaching permissions to role"

    if [[ "$PERMISSIONS_MODE" == "AdministratorAccess" ]]; then
        aws iam attach-role-policy \
            --role-name "$IAM_ROLE_NAME" \
            --policy-arn "arn:aws:iam::aws:policy/AdministratorAccess"
        ok "Attached AdministratorAccess (fine for dev — lock down before prod)"
    else
        POLICY_DOC=$(build_permissions_policy)
        aws iam put-role-policy \
            --role-name "$IAM_ROLE_NAME" \
            --policy-name "$POLICY_NAME" \
            --policy-document "$POLICY_DOC"
        ok "Attached scoped inline policy: $POLICY_NAME"
    fi
}

# =============================================================================
# STEP 4 — CDK Bootstrap
# =============================================================================

cdk_bootstrap() {
    log "Step 4/4 — CDK Bootstrap"

    # Check if already bootstrapped by looking for the CDKToolkit stack
    STATUS=$(aws cloudformation describe-stacks \
        --stack-name CDKToolkit \
        --region "$AWS_REGION" \
        --query 'Stacks[0].StackStatus' \
        --output text 2>/dev/null || true)

    if [[ "$STATUS" == "CREATE_COMPLETE" || "$STATUS" == "UPDATE_COMPLETE" ]]; then
        ok "CDK already bootstrapped (CDKToolkit stack status: $STATUS)"
        return
    fi

    log "Running: cdk bootstrap aws://${AWS_ACCOUNT_ID}/${AWS_REGION}"
    cdk bootstrap "aws://${AWS_ACCOUNT_ID}/${AWS_REGION}"
    ok "CDK bootstrap complete."
}

# =============================================================================
# FINAL — Print GitHub secrets
# =============================================================================

print_github_secrets() {
    ROLE_ARN=$(aws iam get-role --role-name "$IAM_ROLE_NAME" \
        --query 'Role.Arn' --output text)

    echo ""
    echo "============================================================"
    echo "  Add these secrets in GitHub:"
    echo "  Repo → Settings → Secrets and variables → Actions → New secret"
    echo "============================================================"
    echo ""
    echo "  Secret name : AWS_DEPLOY_ROLE_ARN"
    echo "  Secret value: ${ROLE_ARN}"
    echo ""
    echo "  Secret name : AWS_REGION"
    echo "  Secret value: ${AWS_REGION}"
    echo ""
    echo "============================================================"
}

# =============================================================================
# MAIN
# =============================================================================

main() {
    echo ""
    echo "============================================================"
    echo "  AWS Pipeline Setup"
    echo "  Account : $AWS_ACCOUNT_ID"
    echo "  Region  : $AWS_REGION"
    echo "  Repo    : $GITHUB_ORG/$GITHUB_REPO  (branch: $GITHUB_BRANCH)"
    echo "============================================================"
    echo ""

    check_prerequisites
    create_oidc_provider
    create_iam_role
    attach_permissions
    cdk_bootstrap
    print_github_secrets

    echo ""
    ok "All done. Push to the '$GITHUB_BRANCH' branch to trigger the pipeline."
}

main
