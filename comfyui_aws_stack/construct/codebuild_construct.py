from aws_cdk import (
    aws_codebuild as codebuild,
    aws_ecr as ecr,
    aws_iam as iam,
    aws_s3_assets as s3_assets,
    custom_resources as cr,
    RemovalPolicy,
    CfnOutput,
    Duration,
)
from constructs import Construct
from cdk_nag import NagSuppressions
import os


class CodeBuildConstruct(Construct):
    repository: ecr.Repository
    image_tag: str
    project: codebuild.Project

    def __init__(
            self,
            scope: Construct,
            construct_id: str,
            suffix: str,
            **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Create ECR Repository
        repository = ecr.Repository(
            scope,
            "ComfyUIRepository",
            repository_name=f"comfyui-{suffix}",
            removal_policy=RemovalPolicy.RETAIN,
            image_scan_on_push=True,
        )

        # Upload Docker context as S3 asset
        docker_context = s3_assets.Asset(
            self,
            "DockerContext",
            path=os.path.join(os.path.dirname(__file__), "..", "docker"),
        )

        # Create CodeBuild project
        project = codebuild.Project(
            scope,
            "ComfyUIBuildProject",
            project_name=f"comfyui-docker-build-{suffix}",
            description="Builds ComfyUI Docker image",
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.LARGE,
                privileged=True,  # Required for Docker builds
            ),
            environment_variables={
                "AWS_ACCOUNT_ID": codebuild.BuildEnvironmentVariable(
                    value=scope.account
                ),
                "AWS_DEFAULT_REGION": codebuild.BuildEnvironmentVariable(
                    value=scope.region
                ),
                "REPOSITORY_URI": codebuild.BuildEnvironmentVariable(
                    value=repository.repository_uri
                ),
            },
            source=codebuild.Source.s3(
                bucket=docker_context.bucket,
                path=docker_context.s3_object_key,
            ),
            build_spec=codebuild.BuildSpec.from_object({
                "version": "0.2",
                "phases": {
                    "pre_build": {
                        "commands": [
                            "echo Logging in to Amazon ECR...",
                            "aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $AWS_ACCOUNT_ID.dkr.ecr.$AWS_DEFAULT_REGION.amazonaws.com",
                            "IMAGE_TAG=${CODEBUILD_RESOLVED_SOURCE_VERSION:=latest}",
                        ]
                    },
                    "build": {
                        "commands": [
                            "echo Build started on `date`",
                            "echo Building the Docker image...",
                            "docker build -t $REPOSITORY_URI:latest .",
                            "docker tag $REPOSITORY_URI:latest $REPOSITORY_URI:$IMAGE_TAG",
                        ]
                    },
                    "post_build": {
                        "commands": [
                            "echo Build completed on `date`",
                            "echo Pushing the Docker images...",
                            "docker push $REPOSITORY_URI:latest",
                            "docker push $REPOSITORY_URI:$IMAGE_TAG",
                        ]
                    }
                }
            }),
            timeout=Duration.minutes(60),
        )

        # Grant CodeBuild permission to push to ECR
        repository.grant_pull_push(project)

        # Grant CodeBuild permission to read from S3
        docker_context.grant_read(project)

        # Nag suppressions
        NagSuppressions.add_resource_suppressions(
            [project],
            suppressions=[
                {"id": "AwsSolutions-CB3",
                 "reason": "Privileged mode required for Docker builds"},
                {"id": "AwsSolutions-CB4",
                 "reason": "Using AWS managed key for sample purposes"},
            ],
            apply_to_children=True
        )

        # Outputs
        self.repository = repository
        self.image_tag = "latest"
        self.project = project

        CfnOutput(scope, "ECRRepositoryUri", value=repository.repository_uri)
        CfnOutput(scope, "CodeBuildProjectName", value=project.project_name)
