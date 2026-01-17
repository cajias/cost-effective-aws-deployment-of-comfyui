from aws_cdk import (
    aws_codebuild as codebuild,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_s3_assets as s3_assets,
    RemovalPolicy,
    Stack,
)
from constructs import Construct
from cdk_nag import NagSuppressions


class CodeBuildConstruct(Construct):
    ecr_repository: ecr.Repository
    codebuild_project: codebuild.Project
    image_tag: str

    def __init__(
            self,
            scope: Construct,
            construct_id: str,
            **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create ECR Repository for Docker image
        ecr_repository = ecr.Repository(
            self,
            "ComfyUIRepository",
            repository_name="comfyui-repository",
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )

        # Upload Docker context to S3 as an asset
        docker_asset = s3_assets.Asset(
            self,
            "DockerAsset",
            path="comfyui_aws_stack/docker",
        )

        # Create CodeBuild project
        codebuild_project = codebuild.Project(
            self,
            "ComfyUIBuildProject",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                privileged=True,  # Required for Docker builds
                compute_type=codebuild.ComputeType.LARGE,
            ),
            environment_variables={
                "ECR_REPOSITORY_URI": codebuild.BuildEnvironmentVariable(
                    value=ecr_repository.repository_uri
                ),
                "IMAGE_TAG": codebuild.BuildEnvironmentVariable(
                    value="latest"
                ),
                "AWS_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(
                    value=Stack.of(self).region
                ),
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(
                    value=Stack.of(self).account
                ),
                "DOCKER_ASSET_S3_BUCKET": codebuild.BuildEnvironmentVariable(
                    value=docker_asset.s3_bucket_name
                ),
                "DOCKER_ASSET_S3_KEY": codebuild.BuildEnvironmentVariable(
                    value=docker_asset.s3_object_key
                ),
            },
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "echo Logging in to Amazon ECR...",
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com",
                            "echo Downloading Docker context from S3...",
                            "aws s3 cp s3://$DOCKER_ASSET_S3_BUCKET/$DOCKER_ASSET_S3_KEY docker-context.zip",
                            "unzip docker-context.zip -d docker-context",
                        ]
                    },
                    "build": {
                        "commands": [
                            "echo Build started on `date`",
                            "echo Building the Docker image...",
                            "cd docker-context",
                            "docker build -t $ECR_REPOSITORY_URI:$IMAGE_TAG .",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "echo Build completed on `date`",
                            "echo Pushing the Docker image...",
                            "docker push $ECR_REPOSITORY_URI:$IMAGE_TAG",
                        ]
                    }
                }
            })
        )

        # Grant CodeBuild permissions to push to ECR
        ecr_repository.grant_pull_push(codebuild_project)

        # Grant CodeBuild permissions to read from S3
        docker_asset.grant_read(codebuild_project)

        # Add CDK Nag suppressions
        NagSuppressions.add_resource_suppressions(
            [codebuild_project],
            suppressions=[
                {
                    "id": "AwsSolutions-CB3",
                    "reason": "Privileged mode is required for Docker builds in CodeBuild."
                },
                {
                    "id": "AwsSolutions-CB4",
                    "reason": "Using AWS managed keys is acceptable for sample purposes."
                },
            ],
            apply_to_children=True
        )

        # Output
        self.ecr_repository = ecr_repository
        self.codebuild_project = codebuild_project
        self.image_tag = "latest"
