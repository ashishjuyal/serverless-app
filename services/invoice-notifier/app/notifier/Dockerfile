FROM public.ecr.aws/lambda/python:3.12

# copy function code
COPY . ${LAMBDA_TASK_ROOT}

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Build-time args (provided by CDK)
ARG LOG_LEVEL=INFO
ARG MODEL_ID
ARG AWS_REGION=ap-southeast-2

# Runtime env
ENV LOG_LEVEL=$LOG_LEVEL
ENV MODEL_ID=$MODEL_ID
ENV AWS_REGION=$AWS_REGION
ENV AWS_DEFAULT_REGION=$AWS_REGION
ENV DOCKER_CONTAINER=1

# Command to run the function
CMD ["lambda_function.lambda_handler"]
