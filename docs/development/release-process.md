# Omega - Release Process

This document describes how an Omega release is built, approved, and promoted. A release is official only after its Docker image has been approved and the version tag and `latest` have been applied. Publishing a GitHub Release starts that attempt. It does not, by itself, put the image into production.

The tags promoted to production point at a manifest assembled from the images the release tests executed. Promotion does not build another image.

## Process overview

The release process has two phases:

1. **Development and validation.** Changes are developed, reviewed, tested, and merged.
2. **Release publication and promotion.** A published GitHub Release builds the image from the release tag, waits for approval, and promotes that image.

| Phase | Stage | What happens |
| --- | --- | --- |
| 1 | Pull request | Code is developed and tested before merge. |
| 1 | QA validation | QA builds and tests the pull request locally. A Docker image can also be published manually. |
| 1 | Merge | The approved pull request is merged into `main`, or into a patch branch when the change is a fix for an existing release. |
| 2 | GitHub Release | A version such as `v0.2.0` is published. The tag points at the commit to ship. |
| 2 | Release build | The workflow tests that commit and publishes `singularitynet/omega:<commit-sha>`. |
| 2 | QA approval | QA approves the published image. |
| 2 | Community testing | Minor and major releases are tested by the community before administrative approval. Patch releases skip this. |
| 2 | Administrative approval | Final approval is granted. |
| 2 | Promotion | The published image receives `v0.2.0` and `latest`. |

There are two kinds of builds:

* The **pull-request build** runs in continuous integration and, when QA needs it, on a local machine. It does not publish the formal release image.
* The **release build** runs after a GitHub Release is published. It produces the image that can be promoted.

For a published release, GitHub reads the workflow file from the default branch (`main`). The jobs then check out the release tag and build that commit. These release jobs behave as described here after this workflow is on `main`. Publishing a release before that merge still runs the workflow file that is on `main` at that moment.

## Workflow responsibilities

| Workflow | Trigger | Responsibility | Publishes a Docker image? |
| --- | --- | --- | --- |
| `build.yml` | Push or pull request to `main` or `patch-to-v*`, and manual dispatch | Runs the build and tests on `linux/amd64` | No |
| `manual.yml` | Manual dispatch of the selected ref | Optionally tests and publishes an image tagged with that commit's SHA | Only when requested |
| `release.yml` | GitHub Release published | Resolves the tag commit, publishes its image, waits for approval, and promotes it | Yes |
| `common.yml` | Called by the workflows above | Runs tests and the publication logic | Depends on the caller |
| `autotests.yml` | Called by `common.yml` | Builds a local image per platform, tests it, and pushes that image when publication was requested | Only the tested platform images, when publication was requested |

`cleanup.yml`, `sonar.yml`, and `renovate.yml` are not part of the release process.

## 1. Development and validation

Changes land through pull requests. `build.yml` runs on every pull request and push to `main` and to branches named `patch-to-v*`, and when someone starts it manually. It calls `common.yml` with `publish_docker: false` and `platforms: linux/amd64`.

That run executes the test suite, including the image tests in `autotests.yml`. It does not publish an image to Docker Hub. Because the tests already built the image, the workflow does not build it a second time.

The `patch-to-v*` trigger is in this branch's `build.yml`. It is not on `main` until this branch is merged. A later fix branch receives that continuous integration only when the trigger is in the workflow file on the branch that is pushed.

QA still validates a pull request by building the selected commit locally. That local build is not published.

When a Docker image is needed before the formal release, start `manual.yml` on the commit to test. Inputs:

| Input | Default | Effect |
| --- | --- | --- |
| `publish_docker` | `false` | Push the image to Docker Hub when `true`. |
| `no_build_cache` | `false` | Build without cached Docker layers when `true`. |
| `platforms` | `linux/amd64,linux/arm64` | Platforms to build and test. |
| `run_tests` | `true` | Run the test suite. Set `false` to skip it. |

`manual.yml` always tags the image with `github.sha` for the ref selected in the GitHub UI, and it does not move `latest`. On a manual run, `github.sha` is the commit of the selected ref.

When tests run and publication is on, the image that is pushed is the image the tests executed. When tests are turned off and publication is on, there is no tested image, so the workflow builds and pushes a new one. Leaving tests on is the path that publishes the tested image.

Example images from a manual publication:

```text
singularitynet/omega:764ec8251cc09632d2d92566a3e5d7817eb948e6
singularitynet/omega:6e9f0fbb944b64d15a4ee5b668be874619d9378a
```

Manual publication is optional. It is not required for every pull request, and it is not the formal release.

Merging into `main` runs `build.yml` again. That run still does not publish the release image. The formal release has not started.

## 2. Release publication and promotion

### 2.1. Publish the GitHub Release

Create the GitHub Release with the version name, for example `v0.2.0`. The tag must point at the exact commit that should be built. The workflow checks that commit out. It does not build the current tip of `main` unless the tag points there.

`release.yml` starts when the release is published. Its first job checks out `github.event.release.tag_name` and records `git rev-parse HEAD` as the release SHA. Later jobs check out that same tag and fail if `HEAD` is not that SHA.

```yaml
publish_docker: true
tag_name: <sha of the release tag>
checkout_ref: <release tag name>
move_latest: false
```

`move_latest` stays false, so this build does not move `latest`.

The Git tag is not moved after publication. It keeps pointing at the commit that was built. GitHub runs this workflow from `main`, so the workflow file on `main` must already contain this checkout. The source that gets built is still the tag, including a tag on a `patch-to-v*` branch.

### 2.2. Test and publish the image

`common.yml` runs `autotests.yml` first. For a release, the default platforms are `linux/amd64` and `linux/arm64`. Each platform is built and tested on its own runner. The arm64 image is built on `ubuntu-24.04-arm`. The tests run against that local image. Mandatory tests must pass. Optional autotests do not fail the job.

After those tests, the same local image is pushed to:

```text
singularitynet/omega:<commit-sha>-linux-amd64
singularitynet/omega:<commit-sha>-linux-arm64
```

A transient Docker Hub failure retries that `docker push` once. The retry does not build the image again.

The following job does not build. It creates the multi-platform manifest with `docker buildx imagetools create`:

```text
singularitynet/omega:<commit-sha>
```

That manifest is made from the platform images the tests executed. The version tag and `latest` are not applied yet.

If one requested platform fails, the `<commit-sha>` manifest is not created. A platform tag that was already pushed can remain on Docker Hub. It is not a production tag.

The published name is always `singularitynet/omega`, not a short `omega` name.

### 2.3. QA approval

After the image is published, `qa-approval` runs in the GitHub Environment `dockerhub-production`. The environment requires reviewers. The job waits until QA approves.

The job does not build an image and does not inspect it. QA approves the already published `singularitynet/omega:<commit-sha>` image.

### 2.4. Community testing

Minor and major releases need external community testing in the `Omega community testing` channel. Patch releases do not.

This is a manual step. The workflow has no job for it. It happens while the run is waiting on administrative approval. Approving the administrative environment promotes the image even if community testing has not finished, so that approval waits until community testing is done.

### 2.5. Administrative approval

`admin-approval` runs in the GitHub Environment `dockerhub-admin-approval`. A second approval is required. This job does not build an image.

### 2.6. Promote the image

After both approvals, `update-tags` points the version tag and `latest` at the manifest that was already published. It uses `docker buildx imagetools create`. It does not build.

For `v0.2.0`:

```text
singularitynet/omega:<commit-sha>
              │
              ├──► singularitynet/omega:v0.2.0
              │
              └──► singularitynet/omega:latest
```

`latest` is the most recently promoted production release. It is not applied to an image that has not finished both approvals. A release that was published but not promoted does not receive a production version tag and does not become `latest`.

Only one release workflow should be active at a time. `update-tags` always moves `latest`, so two overlapping runs can attach `latest` to the wrong image. Work on the next change can continue on `main`. The next GitHub Release waits until the current run is promoted or canceled.

## 3. Versioning

Versions follow the [Semantic Versioning specification](https://semver.org/). The Git tag and the Docker version tag use `v<major>.<minor>.<patch>`.

* Increment the patch version for a compatible fix, including a small time-sensitive change or a production hotfix.
* Increment the minor version for backward-compatible functionality.
* Increment the major version for a breaking change.

A patch must not include a breaking change. Breaking changes include:

* APIs available to plugins
* the format of configuration files
* the format of imported or exported data, such as the knowledge base or exported memory
* the layout of directories and files that keep the agent state between sessions

Major version 0 is the beta period. Until the project is released as 1.0.0, a breaking change increments the minor version instead of the major version.

Every published Git tag is permanent. It is not deleted, moved, or reused, even when the attempt is canceled before promotion. The next attempt uses a new version number. This applies to minor, major, and patch releases.

Git tags and Docker tags are different:

| Tag | Meaning |
| --- | --- |
| Git tag, such as `v0.2.0` | The source commit of a published GitHub Release. It stays on that commit. |
| Docker SHA tag, `singularitynet/omega:<commit-sha>` | The multi-platform image built from that commit. A later rebuild of the same commit pushes this tag again. |
| Docker platform tags, `singularitynet/omega:<commit-sha>-linux-amd64` and `...-linux-arm64` | The exact images the tests ran, one per platform. |
| Docker version tag, `singularitynet/omega:v0.2.0` | The production image of a release that completed promotion. |
| Docker `latest` | The most recently promoted production image. Promotion and a deliberate rollback are what move it. |

## 4. Patch releases

A fix is developed from the Git tag of the release being fixed, never from `main`. That covers both a defect found before promotion and a hotfix after promotion. `main` may already contain commits that must not ship in the fix.

The branch name is `patch-to-<version>`, for example `patch-to-v0.2.0`, created from the tag of the release being fixed. Further fixes in that cycle stay on that branch.

`build.yml` tests pushes and pull requests to `patch-to-v*` on `linux/amd64` and does not publish an image.

When the branch is ready, publish a new GitHub Release whose tag points at the patch commit. Use the next patch version. The release workflow checks out that tag, tests it, and publishes `singularitynet/omega:<patch-commit-sha>`. Approval and promotion then add the patch version tag and `latest`.

If a patch attempt is canceled, keep the same branch, fix it there, and publish the next patch number from the corrected commit. For example, `v0.2.1` is published and then canceled. The fix stays on `patch-to-v0.2.0`. The next publication is `v0.2.2`.

After the patch release has been promoted, open a pull request that merges the patch branch into `main`. Then stop using that branch. The next fix cycle starts a new `patch-to-<version>` branch from the tag being fixed.

A patch can be prepared while the next minor or major release continues on `main`. Only one release workflow may be active at a time.

## 5. Failure and cancellation

### 5.1. Technical failure

Docker Hub sometimes fails the upload of a large layer. On a release, tests have already run, so the workflow retries that `docker push` once and does not build the image again. A manual publication with tests turned off has no tested image to reuse, so its retry builds and pushes again.

Other transient failures, such as a GitHub Actions interruption, can be retried by re-running the workflow when the source does not need to change. A re-run builds the images again and pushes the same commit SHA. The in-job retry is the one that reuses the image already tested in that run.

### 5.2. The source needs to change

If QA, community testing, or another check finds a product defect, cancel the attempt.

1. Cancel any workflow run that can still reach `update-tags`. The workflow has no rejected state. A later approval would still promote that image. Removing the GitHub Release does not stop a run that is already going, so cancel the run first.
2. Remove the GitHub Release from the releases page so it is not shown as a current release.
3. Keep the Git tag. If GitHub offers to delete the tag together with the Release, keep the tag. The version stays reserved.
4. Fix the code on the patch branch cut from that tag, not by committing the fix onto `main`.
5. Publish a new GitHub Release with a new version, pointing at the corrected commit.

A canceled attempt remains traceable through its Git tag. It is not an official production release, and it must not be promoted.

## 6. Rollback

Rollback is manual. No workflow performs it.

If a promoted release must be taken out of production:

1. Cancel any release run that could still move `latest`.
2. Identify the last known-good production image, by its version tag or its commit SHA.
3. Restore production to that image. Do not rebuild it.
4. If production follows `latest`, point `latest` at that same image.
5. Leave version-specific Docker tags unchanged. `v0.2.0` keeps pointing at the image that was promoted for `v0.2.0`.
6. Confirm that production is running the restored image, not only that a tag was updated.

## 7. Key points

* A release is official only after `update-tags` applies the version tag and `latest`.
* The release workflow checks out the Git tag and publishes that commit. It does not publish the tip of `main` unless the tag points there.
* The published SHA manifest is assembled from the images the tests executed. Promotion does not build another image.
* `build.yml` tests `main` and `patch-to-v*` and does not publish.
* `manual.yml` can publish a SHA-tagged image for any selected ref. Publication is off unless requested. With tests left on, the pushed image is the tested image.
* QA approval uses the `dockerhub-production` environment. Administrative approval uses `dockerhub-admin-approval`.
* Community testing for minor and major releases is a manual wait before administrative approval. Patch releases skip it.
* `latest` moves only in `update-tags`, together with the version tag, or when an operator points it back during rollback.
* Published Git tags are never deleted, moved, or reused. The next attempt uses a new version.
* A fix branch is always created from the release tag, named `patch-to-<version>`, and merged back to `main` by a pull request after promotion.
* Only one release workflow is active at a time.
