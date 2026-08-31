from langchain_aws import ChatBedrock

# Uses cross-region inference profile for Nova Pro
# https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
MODEL_ID = "us.amazon.nova-pro-v1:0"


def load_model() -> ChatBedrock:
    """Get Bedrock model client using IAM credentials."""
    return ChatBedrock(model_id=MODEL_ID)
