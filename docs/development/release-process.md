# Omega - Release Process

This document describes the current process for releasing a new version of Omega, using the `v0.2.0` release as an example.

## Process Overview

The Omega release process has two main phases:

* **Phase 1: Version Preparation and Validation**
* **Phase 2: Release Publication and Promotion**

| **Phase** | **Stage**                   | **What happens**                                                | 
| --------- | --------------------------- | --------------------------------------------------------------- |
| **1**     | **PR development**          | Code is developed and tested before merging to `main`           |
|           | **QA validation**           | QA builds and tests the PR code locally. When needed, a <br>Docker image can also be built and published manually           |
|           | **Merge to `main`**         | The approved PR is merged into `main`                           |
| **2**     | **GitHub Release**          | A version such as `v0.2.0` is created and published             |
|           | **Release build**           | The release workflow builds the formal release Docker image     |
|           | **QA approval**             | QA approves the release image                                   |
|           | **Administrative approval** | Final administrative approval is granted                        |
|           | **Promotion**               | The release image receives the final tags `v0.2.0` and `latest` |

### Important Distinction

There are two different types of builds in the current process:

* The **PR build**, which QA typically performs locally while the code is still under development. This build does not normally result in a Docker image being published to Docker Hub.

* The **release build**, which is performed after the PR is merged and the GitHub Release is published. This build produces the formal release Docker image that is ultimately promoted to the final Docker tags.

For PR testing, the `manual.yml` workflow can be triggered to build and publish a Docker image to Docker Hub. This is a manual process and is not required for every PR.

---

# Phase 1: Version Preparation and Validation

## 1. PR Development and Testing

During development, the code remains in a Pull Request (PR).

QA manually tests the PR by building the code locally on their machine using the current PR commit.

As an alternative, when a Docker image is needed for testing or other purposes, the image can be built and published manually through the manual.yml workflow.

The workflow is manually triggered with:

```yaml
publish_docker: true
```

When this option is enabled, the workflow builds the Docker image from the selected commit and publishes it to Docker Hub. The image is tagged with the corresponding Git commit SHA.

The workflow then calls the reusable `common.yml` workflow.

Example images:

```text
singularitynet/omega:764ec8251cc09632d2d92566a3e5d7817eb948e6
singularitynet/omega:6e9f0fbb944b64d15a4ee5b668be874619d9378a
```

The manual Docker image publication is optional and does not represent a mandatory step in the PR validation process.

---

## 2. Merge the PR into `main`

Once QA has completed testing and any required fixes have been made, the PR is merged into `main`.

The merge automatically triggers `build.yml`.

`build.yml`:

* Runs the test suite.
* Builds the application.
* Performs the normal CI checks.
* Does **not** publish the formal release Docker image.

At this point, the code is in `main`, but the formal release process has not started yet.

---

# Phase 2: Release Publication and Promotion

## 3. Create and Publish the GitHub Release

Once the code intended for release is in `main`, a GitHub Release is created through the GitHub UI, for example, `v0.2.0`.

Publishing the GitHub Release generates the `release.published` event. This event triggers:

```text
.github/workflows/release.yml
```

This is the point at which the formal release process begins.

---

## 4. Build the Release Image

`release.yml` calls the reusable `common.yml` workflow with the following parameters:

```yaml
publish_docker: true
tag_name: ${{ github.sha }}
move_latest: false
```

The workflow then:

1. Builds the application.
2. Builds the Docker image.
3. Runs the required tests.
4. Publishes the image to Docker Hub using the release commit SHA.

The resulting image has a tag similar to:

```text
singularitynet/omega:<release-sha>
```

---

## 5. QA Approval

After the release image has been built and published, the workflow reaches the `qa-approval` job.

This job uses the GitHub Environment:

```text
dockerhub-production
```

The environment is configured to require approval.

The workflow waits until the required QA approval is granted.

No new Docker image is built during this step.

---

## 6. Administrative Approval

After QA approval, the workflow reaches the `admin-approval` job.

This job uses the GitHub Environment:

```text
dockerhub-admin-approval
```

A second approval is required before the image can be promoted to the final tags.

Again, no new Docker image is built during this step.

---

## 7. Promote the Image to the Final Tags

Once both approvals have been granted, the `update-tags` job promotes the SHA-tagged release image.

For the `v0.2.0` release, the final tags are:

```text
singularitynet/omega:v0.2.0
singularitynet/omega:latest
```

No new Docker image is built at this stage.

Instead, `docker buildx imagetools create` is used to create new references to the already-published release image.

Conceptually:

```text
singularitynet/omega:<release-sha>
              │
              ├──► singularitynet/omega:v0.2.0
              │
              └──► singularitynet/omega:latest
```

This means that the final tags point to the same image that was built and approved during the release process.

---

# Versioning strategy

Project versioning should be compatible to [Semantic versioning specification](https://semver.org/).
Each version consists of three numbers major, minor and patch version.
The whole version name looks like `v<major>.<minor>.<patch>`.

Patch version is incremented when small, time-sensitive changes and production fixes are made (see [Patch release](#patch_release)).
Patch cannot include non-backward compatible changes which trigger major version change (see below).
Once a version tag has been created for a release, its version number must not be reused, even if the release is not promoted to production.
Each subsequent release attempt must use a new version number to avoid ambiguity and potential inconsistencies for users or automation that may already have referenced the original release tag.

If release contains new functionality or features which are backward-compatible then minor version should be incremented.
If release contains breaking or incompatible changes that require consumers to adapt then major version should be incremented.
The breaking changes include changes to the following areas:
- all APIs available to the plugins
- format of the configuration files
- the format of the imported exported data such as knowledge base or exported memory
- the layout of the directories and files which keep the state of the agent between sessions

For this project, major version 0 is reserved for the beta version of software.
During this phase, breaking changes trigger a minor version increment rather than a major one, until the project is explicitly promoted out of beta with version 1.0.0.

---

# Patch release

There are two situations which require adding changes via a patch release to a major or minor release candidate version:
1. critical bug is found before current release tag is promoted to the latest version
2. hotfix is required after release is published and tag is promoted to the latest version

In both situations there is a chance other PRs are merged to the `main` branch after the release tag.
It means we cannot create a patch release from the `main` branch because it may contain changes merged after the current release tag, including changes that are not intended to be part of the patch release.
The proper way to handle it is making patch release branch from the release tag.
The name of the branch should be `patch-to-<current release version>`.
All release fixes should be merged into the patch release branch.

When the branch includes all necessary fixes new patch release is initiated from the branch.
The release process is similar to [Release publication process](#phase-2-release-publication-and-promotion) but the patch release branch is used instead of `main` branch.
Patch version should be chosen according to the [Versioning strategy](#versioning_strategy).
After release is promoted to the production the patch release branch should be merged into the `main` branch of the repository by separate PR.

The processes described in this document allow a patch release to be prepared while development of the next major or minor release continues on the main branch. However, only one release process should be active at a time, and each release process must be completed by promoting the release to production or cancelling it before another release process can begin.

---

# Key Points

* QA builds and tests the PR code locally before it is merged into `main`.
* The Git commit SHA identifies the specific PR commit being tested.
* A Docker image can optionally be built and published to Docker Hub through the manually triggered `manual.yml` workflow.
* When `manual.yml` is used to publish an image, the image is tagged with the corresponding Git commit SHA.
* Merging into `main` triggers the normal CI workflow through `build.yml`.
* `build.yml` does **not** publish the formal release image.
* The formal release starts when a GitHub Release is published.
* `release.yml` builds and publishes a new release image.
* The release image is identified by the release commit SHA.
* QA approval happens after the release image has been built.
* Administrative approval happens after QA approval.
* The final `v0.2.0` and `latest` tags are created by referencing the already-built release image.
* No new image is built during the final tag promotion.

