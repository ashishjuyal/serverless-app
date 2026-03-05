#!/usr/bin/env python3
import os

import aws_cdk as cdk

from stack.log_forwarder_stack import LogForwarderStack


app = cdk.App()

account  = app.node.try_get_context("account")  or os.getenv("CDK_DEFAULT_ACCOUNT")
region   = app.node.try_get_context("region")   or os.getenv("CDK_DEFAULT_REGION")
env_name = app.node.try_get_context("env_name") or "dev"

if not account or not region:
    raise ValueError(
        "Provide AWS account and region via CDK context "
        "(-c account=... -c region=...) or set CDK_DEFAULT_ACCOUNT / CDK_DEFAULT_REGION."
    )

env = cdk.Environment(account=account, region=region)

LogForwarderStack(app, "LogForwarderStack", env=env)

app.synth()
