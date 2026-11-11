#!/usr/bin/env bash
# Vercel's Ignored Build Step (hosted/vercel.json's ignoreCommand): exit 0 skips the build, 1 builds.
# Every deployment keeps its own copy of the ~280 MB function bundle, and a preview for each push
# to a PR branch was most of the project's deployments. So only production builds, unless the
# commit message asks for a preview with "[preview]".
if [ "${VERCEL_ENV:-}" = "production" ]; then
  exit 1
fi
case "${VERCEL_GIT_COMMIT_MESSAGE:-}" in
  *"[preview]"*) exit 1 ;;
esac
echo "Skipping the ${VERCEL_ENV:-preview} build (add [preview] to the commit message to build one)."
exit 0
